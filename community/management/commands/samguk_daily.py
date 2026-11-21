"""테크창 삼국지 아침 마감 — 지난 게임일 판을 닫고(순위·천하인 칭호·세력 점수) 오늘 판을 만든다.

cron(서버 ubuntu): 5 6 * * *  cd $APP && $PY manage.py samguk_daily >> $APP/logs/techchang_samguk.log 2>&1
06:00 경계 바로 뒤에 돈다. 늦거나 빠져도 화면을 열 때 samguk.catch_up() 이 따라잡는다.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from community import samguk as S


class Command(BaseCommand):
    help = '테크창 삼국지: 지난 판 마감과 오늘 판 생성'

    def handle(self, *args, **opts):
        out = S.daily()
        self.stdout.write(f"{timezone.localtime():%Y-%m-%d %H:%M} 삼국지 마감 {out['closed'] or '없음'} → 오늘 {out['today']}")
