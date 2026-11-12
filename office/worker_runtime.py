"""유효기간과 실행 식별자로 보호하는 단일 관리자용 실행기."""
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from .models import JobRequest, ColumnDraft
from .job_supervision import recover, identity, managed, unit, stop
from .security import validate_args, is_operator
from .environment import worker_environment
from .audit import append


def work(out=print):
    from .jobmail import limited_until
    recover(out=out)
    if JobRequest.objects.filter(status__in=['started', 'quarantined']).exists() or limited_until():
        return
    job = JobRequest.objects.filter(status='pending', run_after__lte=timezone.now()).first()
    if not job:
        return
    if job.requested_by_id and not is_operator(job.requested_by):
        job.status, job.active_key, job.note = 'cancelled', None, '요청한 운영자의 권한이 회수됐어요.'
        job.save()
        return
    if job.draft and job.draft.status not in ('hold', 'revising', 'rejected'):
        job.status, job.active_key = 'skipped', None
        job.save()
        return
    try:
        validate_args(job.args)
    except ValueError as exc:
        job.status, job.note, job.active_key = 'failed', str(exc), None
        job.save()
        return
    now, execution = timezone.now(), uuid.uuid4()
    if not JobRequest.objects.filter(pk=job.pk, status='pending').update(status='started', started_at=now,
            execution_id=execution, lease_until=now+timedelta(seconds=120)):
        return
    job.refresh_from_db()
    job.attempts += 1
    job.save(update_fields=['attempts'])
    root = Path(settings.BASE_DIR)
    (root / 'logs').mkdir(exist_ok=True)
    proc = None
    try:
        path = root / 'logs/office_jobs.log'
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as log:
            argv = [sys.executable, str(root / 'manage.py'), 'office_execute_job',
                    '--job', str(job.pk), '--execution', str(execution)]
            if managed():
                argv = ['systemd-run', '--user', '--unit='+unit(job), '--wait', '--pipe', '--collect',
                        '--property=RuntimeMaxSec=2700', '--property=KillMode=control-group',
                        '--property=UMask=0077',
                        '--property=EnvironmentFile=-'+str(root / '.env'),
                        '--working-directory='+str(root),
                        '--setenv=DJANGO_SETTINGS_MODULE='+os.environ.get('DJANGO_SETTINGS_MODULE', 'config.settings.prod'), *argv]
            proc = subprocess.Popen(argv, cwd=root, env=worker_environment(), stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            job.process_id = proc.pid
            job.process_identity = identity(proc.pid)
            job.save(update_fields=['process_id', 'process_identity'])
            append('job_started', draft_id=job.draft_id, payload={'job': job.pk, 'execution': str(execution)})
            start = time.monotonic()
            while proc.poll() is None:
                now = timezone.now()
                if not JobRequest.objects.filter(pk=job.pk, execution_id=execution, status='started',
                        lease_until__gt=now).update(heartbeat_at=now, lease_until=now+timedelta(seconds=120)):
                    stop(job)
                    return
                if time.monotonic() - start >= 2700:
                    job.note = '45분 실행 시간을 초과했어요. 운영자 확인이 필요해요.'
                    if not stop(job):
                        job.status = 'quarantined'
                        break
                    proc.wait(timeout=15)
                    break
                time.sleep(1)
            job.exit_code = proc.returncode
            if job.status != 'quarantined':
                job.status = 'completed' if proc.returncode == 0 else 'failed'
            job.refresh_from_db(fields=['draft_id'])
            if job.draft_id:
                job.business_result = ColumnDraft.objects.values_list('status', flat=True).get(pk=job.draft_id)
    except OSError as exc:
        job.note = f'프로세스 시작 실패: {exc}'[:300] if proc is None else f'실행 후 오류: {exc}; 종료 확인이 필요해요.'[:300]
        job.status = ('pending' if job.attempts < 2 else 'failed') if proc is None else 'quarantined'
        job.run_after = timezone.now()+timedelta(minutes=1)
    except subprocess.TimeoutExpired:
        job.status, job.note = 'quarantined', '종료가 확인되지 않았어요. 운영자가 프로세스를 확인해 주세요.'
    job.finished_at = timezone.now() if job.status != 'pending' else None
    if job.status not in ('pending', 'quarantined'):
        job.active_key = None
    changes = {field: getattr(job, field) for field in
               ('status', 'finished_at', 'active_key', 'run_after', 'exit_code', 'note', 'business_result',
                'process_id', 'process_identity')}
    if not JobRequest.objects.filter(pk=job.pk, execution_id=execution, status='started').update(**changes):
        return
    append('job_finished', draft_id=job.draft_id, payload={'job': job.pk, 'execution': str(execution),
           'status': job.status, 'exit_code': job.exit_code, 'business_result': job.business_result})
    out(f'작업 #{job.pk}: {job.status}')
