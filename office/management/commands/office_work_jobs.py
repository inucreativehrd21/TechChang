"""1분 cron에서 실행하는 단일 서버 작업 실행기."""
from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
from office.run_context import execution_lock
from office.worker import work


class Command(BaseCommand):
    help = '대기 작업을 웹 서비스 밖에서 하나씩 실행해요.'

    def handle(self, *args, **options):
        try:
            with execution_lock(Path(settings.BASE_DIR) / 'logs/office-worker.lock'):
                work(out=self.stdout.write)
        except RuntimeError as exc:
            if '다른 프로세스' not in str(exc):
                raise
