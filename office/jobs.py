"""웹 요청은 DB에 예약하고, cron 실행기만 manage.py 자식 프로세스를 시작한다."""
from __future__ import annotations

import os
import subprocess
import sys

from django.conf import settings
from django.utils import timezone


def enqueue(args: list, *, by: str = 'system', draft=None, via: str = 'admin', dedupe=False, actor=None):
    """웹 서비스 재시작과 분리되도록 office_release(cron)가 집을 작업을 저장한다."""
    from .models import JobRequest
    from .security import validate_args
    validate_args(args)
    from .models import ColumnDraft
    for flag in ('--draft', '--revise-draft'):
        if flag in args and args.index(flag) + 1 < len(args):
            draft = ColumnDraft.objects.filter(pk=args[args.index(flag) + 1]).first()
    if dedupe:
        existing = next((job for job in JobRequest.objects.filter(status=JobRequest.ST_PENDING,
                                                                   requested_via=via)
                         if job.args == args), None)
        if existing:
            return existing
    from .recorder import digest
    from django.db import IntegrityError, transaction
    import json
    key = digest(json.dumps([args[0], draft.pk] if draft else list(args), ensure_ascii=False))
    try:
        with transaction.atomic():
            return JobRequest.objects.create(kind=JobRequest.KIND_RERUN, args=list(args), active_key=key,
                                     label=' '.join(args)[:200], draft=draft,
                                     run_after=timezone.now(), requested_via=via, requested_by=actor, note=f'요청: {by}'[:300])
    except IntegrityError:
        return JobRequest.objects.get(active_key=key)


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
