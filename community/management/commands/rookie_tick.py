"""야구선수 키우기 정식 판 시간대 경기 — 시각이 지난 경기(11:00·13:00·15:30·18:00·20:00·22:00)를 치른다.

cron(서버 ubuntu): */5 11-23 * * *  cd $APP && $PY manage.py rookie_tick >> $APP/logs/techchang_rookie.log 2>&1
스위치 ROOKIE_FULL_SLOTS 가 꺼져 있거나 시작 시즌(ROOKIE_SLOTS_FROM_SEASON) 전이면 아무것도 하지 않는다 —
그때는 지금처럼 00:10 rookie_daily 가 전날 경기를 몰아서 치른다. 이미 치른 시간대는 다시 치르지 않는다.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from community import rookie_clock as Clock
from community import rookie_league as L


class Command(BaseCommand):
    help = '야구선수 키우기: 시각이 지난 시간대 경기 진행(정식 판)'

    def handle(self, *args, **opts):
        now = timezone.now()
        today = timezone.localdate(now)
        if not Clock.active_on(today):
            return
        n = L.advance(now=now)                       # 빠진 시간대·전날 마무리까지 따라잡는다
        if n:
            self.stdout.write(f'[{timezone.localtime(now):%Y-%m-%d %H:%M}] 야구선수 키우기 — 시간대 경기 진행')
