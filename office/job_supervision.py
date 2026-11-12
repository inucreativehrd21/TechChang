"""작업 신원 확인과 독립 감시. PID가 다른 프로세스에 재사용되면 종료하지 않는다."""
import os
import subprocess
import time
from pathlib import Path
from django.conf import settings
from django.utils import timezone


def identity(pid):
    if not pid:
        return ''
    try:
        if os.name == 'posix':
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] == 'Z':
                return 'exited-zombie'
            return fields[19]
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ''
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return ''
            return str(times[0].dwHighDateTime << 32 | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    except (OSError, IndexError):
        return ''


def managed():
    return getattr(settings, 'LAB_JOB_SUPERVISOR', 'process') == 'systemd'


def unit(job):
    return f'lab-job-{job.execution_id}.service'


def active(job):
    if managed():
        result = subprocess.run(['systemctl', '--user', 'is-active', unit(job)],
                                capture_output=True, text=True, timeout=10)
        if result.stdout.strip() not in ('active', 'activating', 'deactivating', 'inactive', 'failed', 'unknown'):
            raise OSError('systemd 작업 상태를 확인할 수 없어요.')
        return result.stdout.strip() in ('active', 'activating', 'deactivating')
    from .worker import alive
    current = identity(job.process_id)
    if current == 'exited-zombie':
        return False
    if not current or not job.process_identity:
        return alive(job.process_id)
    return bool(job.process_identity and current == job.process_identity and alive(job.process_id))


def stop(job):
    if not job.execution_id:
        from .worker import alive
        return not alive(job.process_id)
    if managed():
        subprocess.run(['systemctl', '--user', 'stop', unit(job)], capture_output=True, timeout=15)
        return not active(job)
    current = identity(job.process_id)
    if current == 'exited-zombie':
        return True
    if not current:
        from .worker import alive
        return not alive(job.process_id)
    if not job.process_identity:
        return False
    if current != job.process_identity:
        return True  # 기록한 프로세스는 이미 끝났다. 재사용된 PID는 건드리지 않는다.
    if os.name == 'posix':
        import signal
        os.killpg(job.process_id, signal.SIGKILL)
    else:
        subprocess.run(['taskkill', '/PID', str(job.process_id), '/T', '/F'], capture_output=True, timeout=15)
    for _ in range(40):
        if not active(job):
            return True
        time.sleep(.05)
    return False


def recover(out=print):
    from .models import JobRequest, ColumnDraft
    from .audit import append
    for job in JobRequest.objects.filter(status='started'):
        now = timezone.now()
        try:
            running = active(job)
            if not job.execution_id and job.process_id:
                from .worker import alive
                running = alive(job.process_id)
            expired = not job.lease_until or job.lease_until <= now
            if not expired and job.started_at and (now-job.started_at).total_seconds() < 10:
                continue
            if running and not expired:
                continue
            claim = JobRequest.objects.filter(pk=job.pk, execution_id=job.execution_id, status='started')
            if running and expired:
                from django.db.models import Q
                claim = claim.filter(Q(lease_until__lte=now) | Q(lease_until__isnull=True))
            if not claim.update(lease_until=now):
                continue
            stopped = stop(job) if running else True
        except (OSError, subprocess.SubprocessError):
            stopped = False
        changed = JobRequest.objects.filter(pk=job.pk, execution_id=job.execution_id, status='started').update(
            status='interrupted' if stopped else 'quarantined', finished_at=now,
            active_key=None if stopped else job.active_key, note='실행이 중단됐어요. 기록을 확인해 재개해 주세요.')
        if changed:
            ColumnDraft.objects.filter(pk=job.draft_id, status='revising').update(status='hold')
            append('job_interrupted', draft_id=job.draft_id,
                   payload={'job': job.pk, 'execution': str(job.execution_id), 'stopped': stopped})
            out(f'작업 #{job.pk}: 중단 확인' if stopped else f'작업 #{job.pk}: 종료 확인 필요')
