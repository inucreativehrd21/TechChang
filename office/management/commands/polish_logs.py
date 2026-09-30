"""공개 연구실에 올릴 활동 문장을 다듬는다.

연구실 페이지는 주기적으로 폴링하므로 조회 때마다 모델을 부르면 비용이 감당되지 않는다.
그래서 **여기서 미리 만들어 WorkLog.public_text 에 저장**하고, 페이지는 그것을 읽기만 한다.
칼럼 파이프라인이 끝난 뒤(office_publish·office_revise·hold_meeting) 한 번 돌리면 된다.

모델에 넘기는 것은 publiclog 가 이미 걸러 다듬은 문장뿐이다. 원문에는 운영자 지시문과
내부 채점표가 섞여 있어 그대로 주면 다시 새어 나온다.

사용법:
  python manage.py polish_logs                # 아직 안 다듬은 공개 대상 전부 (최대 40건)
  python manage.py polish_logs --limit 12
  python manage.py polish_logs --dry-run      # 무엇을 보낼지만 출력
  python manage.py polish_logs --redo         # 이미 다듬은 것도 다시
"""
from django.core.management.base import BaseCommand

from office.agents import AGENTS
from office.models import WorkLog
from office.publiclog import polish, public_line


class Command(BaseCommand):
    help = '공개 연구실 활동 문장을 다듬어 WorkLog.public_text 에 저장합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=40, help='한 번에 처리할 건수')
        parser.add_argument('--dry-run', action='store_true', help='보낼 내용만 출력')
        parser.add_argument('--redo', action='store_true', help='이미 다듬은 것도 다시 만든다')

    def handle(self, *args, **opts):
        out = self.stdout.write
        qs = WorkLog.objects.select_related('draft').order_by('-created_at')[:300]

        rows, targets = [], []
        for log in qs:
            if log.public_text and not opts['redo']:
                continue
            line = public_line(log)
            if not line or log.agent not in AGENTS:
                continue
            a = AGENTS[log.agent]
            rows.append((log.id, a['name'], a['title'], line))
            targets.append(log)
            if len(rows) >= opts['limit']:
                break

        if not rows:
            out('다듬을 로그가 없습니다.')
            return

        out(f'{len(rows)}건을 다듬습니다.')
        if opts['dry_run']:
            for _id, name, title, line in rows:
                out(f'  [{name}·{title}] {line}')
            return

        polished = polish(rows)
        if not polished:
            out(self.style.WARNING('모델이 문장을 돌려주지 않았습니다 — 틀 문장을 그대로 씁니다.'))
            return

        changed = 0
        for log in targets:
            new = polished.get(log.id)
            if not new:
                continue
            log.public_text = new[:300]
            log.save(update_fields=['public_text'])
            changed += 1
            if changed <= 12:
                out(f'  {AGENTS[log.agent]["name"]}: {new}')
        out(self.style.SUCCESS(f'\n{changed}건 저장 (요청 {len(rows)}건)'))
