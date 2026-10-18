"""야구선수 키우기 밤 정산 — 전날 경기 시뮬레이션(시즌 마지막 날이면 시상) → 능력치 감쇠·강등 정산.

cron(서버 ubuntu): 10 0 * * *  cd $APP && $PY manage.py rookie_daily >> $APP/logs/techchang_rookie.log 2>&1
경기를 먼저 치르는 이유: 그날 밤 감쇠가 들어가기 전, 그날 훈련한 능력치로 뛰게 하려고.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from community import rookie as R
from community import rookie_league as L


class Command(BaseCommand):
    help = '야구선수 키우기: 전날 경기 진행·시즌 시상·능력치 감쇠 정산'

    def handle(self, *args, **opts):
        days = L.advance()
        n = R.settle_all(stale_only=False)     # 자정에 출석해 정산은 됐지만 경기 전이라 미룬 학년 전환까지
        from datetime import timedelta
        from community.models import LiteCareer
        old = LiteCareer.objects.filter(user__isnull=True, updated_at__lt=timezone.now() - timedelta(days=14)).delete()[0]
        if old:
            self.stdout.write(f'라이트 손님 판 정리 {old}건(14일 넘게 손대지 않음)')
        self.stdout.write(f'[{timezone.localtime():%Y-%m-%d %H:%M}] 야구선수 키우기 — 경기일 {days}일 진행 · 정산 {n}명')
