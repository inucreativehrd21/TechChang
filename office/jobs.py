"""연구실 백그라운드 작업 띄우기 — manage.py <명령> 을 따로 프로세스로 실행하고 출력을 logs/office_jobs.log 에 쌓는다.

관리 화면의 '작업 실행'(office.views.run_job)과 칼럼 저장 신호(office.signals)가 함께 쓴다. 모델 호출은 수 분이
걸려 요청·저장 안에서 돌릴 수 없다.
"""
from __future__ import annotations

import os
import subprocess
import sys

from django.conf import settings
from django.utils import timezone


def spawn(args: list, *, by: str = 'system', env: dict | None = None):
    if sys.argv[1:2] == ['test']:
        return      # 테스트 중에는 실제 프로세스를 띄우지 않는다(저장 신호가 커밋 콜백으로 부를 수 있다)
    manage = os.path.join(settings.BASE_DIR, 'manage.py')
    os.makedirs(os.path.join(settings.BASE_DIR, 'logs'), exist_ok=True)
    logf = open(os.path.join(settings.BASE_DIR, 'logs', 'office_jobs.log'), 'a', encoding='utf-8')
    logf.write(f"\n=== {timezone.localtime():%Y-%m-%d %H:%M:%S} {' '.join(args)} (by {by})\n")
    logf.flush()
    full_env = {**os.environ, 'DJANGO_SETTINGS_MODULE': os.environ.get('DJANGO_SETTINGS_MODULE', 'config.settings'),
                **(env or {})}
    subprocess.Popen([sys.executable, manage, *args], cwd=settings.BASE_DIR,
                     stdout=logf, stderr=subprocess.STDOUT, env=full_env, start_new_session=True)
