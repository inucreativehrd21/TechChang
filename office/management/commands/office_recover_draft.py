"""기본은 복구 후보 확인만 한다. --apply 때도 공개·모델 호출 없이 빈 원고만 복원한다."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from office.models import ColumnDraft, JobRequest
from office.draft_recovery import reviewed_candidate


class Command(BaseCommand):
    help = '빈 원고의 마지막 검수본을 확인해요. --apply로 보류 상태에 복구해요(공개하지 않아요).'

    def add_arguments(self, parser):
        parser.add_argument('--draft', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        with transaction.atomic():
            draft = ColumnDraft.objects.select_for_update().filter(pk=opts['draft']).first()
            if draft is None:
                raise CommandError('원고를 찾을 수 없어요.')
            if draft.content.strip() or draft.status not in ('hold', 'failed') or draft.question_id:
                raise CommandError('본문이 비어 있는 보류·실패 원고만 복구해요.')
            if JobRequest.objects.filter(draft=draft, status__in=['pending', 'started', 'quarantined']).exists():
                raise CommandError('이 원고의 대기·실행 중 작업이 있어요. 종료를 확인한 뒤 복구해 주세요.')
            try:
                candidate = reviewed_candidate(draft)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            result = {'draft_id': draft.pk, 'applied': False, 'subject': candidate['subject'],
                      'score': candidate['qa_report'].get('score'), 'source': candidate['source']}
            if opts['apply']:
                from office.audit import append
                # 실패 재심 메타를 포함한 기존 필드와 출처를 감사 기록에 먼저 남긴다.
                append('draft_recovered', draft_id=draft.pk, payload={
                    'before': {k: getattr(draft, k) for k in ('subject', 'content', 'check_report', 'qa_report',
                               'chart_path', 'chart_note', 'revisions', 'status')}, 'source': candidate['source']})
                for key in ('subject', 'content', 'check_report', 'qa_report'):
                    setattr(draft, key, candidate[key])
                draft.status = ColumnDraft.STATUS_HOLD
                draft.chart_path, draft.chart_note = '', '제작 기록의 검수본 복구 — 공개 전 재심이 필요해요.'
                draft.save(update_fields=['subject', 'content', 'check_report', 'qa_report', 'status',
                                          'chart_path', 'chart_note'])
                result['applied'] = True
            self.stdout.write(json.dumps(result, ensure_ascii=False))
