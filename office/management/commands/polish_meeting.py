"""편집회의 요약·주제 소개를 공개 연구실용으로 다듬는다.

내부 요약(Meeting.summary)에는 방문자 수·검색 CTR·평균순위 같은 운영 지표와
반려 사유가 섞여 있어 그대로 내보낼 수 없다. 여기서 독자용 문장을 만들어
Meeting.public_summary / Decision.public_note 에 저장하고, 공개 페이지는 그것만 읽는다.
주 1회 회의 때 한 번(호출 1회)만 돌린다 — hold_meeting 끝에서 자동 실행된다.

사용법:
  python manage.py polish_meeting                # 가장 최근 회의
  python manage.py polish_meeting --meeting 2
  python manage.py polish_meeting --dry-run
"""
from django.core.management.base import BaseCommand, CommandError

from office.models import Meeting
from office.publiclog import polish_meeting


class Command(BaseCommand):
    help = '편집회의 요약·주제 소개를 공개용으로 다듬습니다.'

    def add_arguments(self, parser):
        parser.add_argument('--meeting', type=int, help='회의 ID (기본: 최신)')
        parser.add_argument('--dry-run', action='store_true', help='저장하지 않고 결과만 출력')

    def handle(self, *args, **opts):
        m = (Meeting.objects.filter(pk=opts['meeting']).first() if opts['meeting']
             else Meeting.objects.first())
        if m is None:
            raise CommandError('회의를 찾지 못했습니다')

        out = self.stdout.write
        res = polish_meeting(m)
        if not res['summary'] and not res['notes']:
            out(self.style.WARNING('다듬을 내용이 없습니다 (정해진 칼럼 주제가 없음)'))
            return

        out(f'[{m.week_start} 주차]\n{res["summary"]}\n')
        by_id = {d.id: d for d in m.decisions.all()}
        for did, note in res['notes'].items():
            d = by_id.get(did)
            out(f'  · {(d.chosen or {}).get("title", "")[:50]}\n      {note}')

        if opts['dry_run']:
            out(self.style.WARNING('\n[dry-run] 저장하지 않았습니다.'))
            return

        m.public_summary = res['summary']
        m.save(update_fields=['public_summary'])
        for did, note in res['notes'].items():
            d = by_id.get(did)
            if d:
                d.public_note = note
                d.save(update_fields=['public_note'])
        missing = res.get('expected', 0) - len(res['notes'])
        out(self.style.SUCCESS(f'\n저장 완료 — 요약 1건 · 주제 소개 {len(res["notes"])}건'))
        if missing > 0:
            out(self.style.WARNING(f'{missing}개 주제는 소개 문장이 없어 제목만 나갑니다 — '
                                   '다시 실행하면 채워질 수 있습니다.'))
