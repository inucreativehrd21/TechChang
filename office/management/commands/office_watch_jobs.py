from django.core.management.base import BaseCommand
from office.job_supervision import recover


class Command(BaseCommand):
    help = '실행기와 독립적으로 만료된 작업을 확인해요.'

    def handle(self, *args, **opts):
        recover(out=self.stdout.write)
