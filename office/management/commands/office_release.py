"""예정 시각이 지난 '공개 대기' 칼럼·연재 회차를 발행하고(office.schedule.release_due),
메일 버튼으로 예약한 재실행·재심 요청을 띄운다(office.jobmail.run_due).

cron: */10 * * * *  cd $APP && $PY manage.py office_release >> $APP/logs/techchang_columns.log 2>&1
모델을 부르지 않는다 — 미리 끝내 둔 원고를 공개만 한다.
"""
from django.core.management.base import BaseCommand

from office import schedule as S


class Command(BaseCommand):
    help = '공개 예정 시각이 지난 공개 대기 원고를 발행합니다.'

    def handle(self, *args, **opts):
        from office import jobmail
        jobmail.run_due(out=self.stdout.write)          # 메일 버튼으로 예약한 재실행·재심 요청
        done = S.release_due(out=self.stdout.write)
        if done:
            try:     # 연구실 공개 피드 문장(발행 줄) — 실패해도 공개는 끝났다
                from django.core.management import call_command
                call_command('polish_logs', limit=6, verbosity=0)
            except Exception:  # noqa: BLE001
                pass
