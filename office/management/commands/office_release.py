"""예정 시각이 지난 '공개 대기' 칼럼·연재 회차를 발행하고(office.schedule.release_due),
작업 실행은 별도 office_work_jobs 명령이 담당한다.

cron: */10 * * * *  cd $APP && $PY manage.py office_release >> $APP/logs/techchang_columns.log 2>&1
모델을 부르지 않는다 — 미리 끝내 둔 원고를 공개만 한다.
"""
from django.core.management.base import BaseCommand

from office import schedule as S


class Command(BaseCommand):
    help = '공개 예정 시각이 지난 공개 대기 원고를 발행합니다.'

    def handle(self, *args, **opts):
        S.release_due(out=self.stdout.write)
