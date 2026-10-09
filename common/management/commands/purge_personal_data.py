"""보유 기간이 지난 개인정보 파기 — 개인정보 처리방침 제3·4조를 실제로 지키는 정기 작업.

    python manage.py purge_personal_data                 # 1일 지난 이메일 인증 기록 삭제 (cron 매일)
    python manage.py purge_personal_data --withdrawn     # + 예전 방식으로 탈퇴한 계정의 남은 개인정보 파기
    python manage.py purge_personal_data --dry-run       # 대상 수만 보여 준다

--withdrawn 대상: 2026-10-09 이전 탈퇴 처리로 'deleted_<id>_<원래 아이디>' 형태가 된 비활성 계정.
이메일·아이디 원문이 그대로 남아 있어 common.services.account.withdraw 로 다시 파기한다.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

VERIFICATION_TTL = timedelta(days=1)


class Command(BaseCommand):
    help = '보유 기간이 지난 개인정보(이메일 인증 기록, 예전 탈퇴 계정)를 파기합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--withdrawn', action='store_true', help='예전 방식 탈퇴 계정의 남은 개인정보도 파기')
        parser.add_argument('--dry-run', action='store_true', help='삭제하지 않고 대상 수만 출력')

    def handle(self, *args, **opts):
        from common.models import EmailVerification
        from common.services.account import withdraw

        dry = opts['dry_run']
        old = EmailVerification.objects.filter(created_at__lt=timezone.now() - VERIFICATION_TTL)
        n = old.count()
        if not dry:
            old.delete()
        self.stdout.write(f'이메일 인증 기록 {n}건 {"삭제 대상" if dry else "삭제"}')

        if opts['withdrawn']:
            legacy = User.objects.filter(is_active=False, username__startswith='deleted_')
            n = legacy.count()
            if not dry:
                for user in legacy:
                    withdraw(user)
            self.stdout.write(f'예전 탈퇴 계정 {n}건 {"파기 대상" if dry else "개인정보 파기"}')
