"""기존 글은 자동 추정하지 않고, 운영자가 본문 검토 후 유형만 지정한다."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from community.column_tracks import TRACKS
from community.models import Question


class Command(BaseCommand):
    help = '기존 칼럼 유형을 조회하거나, 본문 검토 사유와 함께 분류해요. 본문·발행일은 유지해요.'

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int)
        parser.add_argument('--track', choices=[*TRACKS, 'legacy'])
        parser.add_argument('--reason', default='')

    @transaction.atomic
    def handle(self, *args, **opts):
        qs = Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False, series__isnull=True)
        if not opts['track']:
            for q in qs.filter(pk=opts['question']) if opts['question'] else qs.order_by('-create_date'):
                self.stdout.write(f'{q.pk}\t{q.get_column_track_display()}\t{q.subject}')
            return
        if not opts['question'] or not opts['reason'].strip():
            raise CommandError('분류할 --question과 본문 검토 근거 --reason이 필요해요.')
        q = qs.select_for_update().filter(pk=opts['question']).first()
        if q is None:
            raise CommandError('해당 단편 칼럼을 찾을 수 없어요.')
        old = q.column_track
        q.column_track = '' if opts['track'] == 'legacy' else opts['track']
        q.save(update_fields=['column_track'])
        from office.audit import append
        append('column_classified', payload={'question_id': q.pk, 'before': old,
            'after': q.column_track, 'reason': opts['reason'].strip()[:1000]})
        self.stdout.write(f'#{q.pk} — {q.get_column_track_display()}로 분류했어요.')
