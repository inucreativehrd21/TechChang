from django.db import transaction
from django.utils import timezone
from .models import JobRequest
from .audit import append


@transaction.atomic
def cancel(job_id, actor_id=None):
    job = JobRequest.objects.select_for_update().get(pk=job_id)
    if job.status not in ('pending', 'started', 'quarantined'):
        return
    was_running = job.status != 'pending'
    job.lease_until = timezone.now()
    job.status, job.active_key, job.finished_at = 'cancelled', None, timezone.now()
    job.save()
    # 먼저 소유권을 취소한다. 종료 확인이 안 되면 신규 실행을 막는다.
    if was_running:
        from .job_supervision import stop
        try:
            stopped = stop(job)
        except Exception:
            stopped = False
        if not stopped:
            job.status, job.active_key = 'quarantined', 'cancel-'+str(job.pk)
            job.save()
    append('job_cancelled', actor_id=actor_id, draft_id=job.draft_id,
           payload={'job': job.pk, 'execution': str(job.execution_id), 'status': job.status})


@transaction.atomic
def restart(job_id, actor_id=None, resume=False):
    from .jobs import enqueue
    job = JobRequest.objects.select_for_update().get(pk=job_id)
    if job.status not in ('failed', 'interrupted', 'cancelled'):
        raise ValueError('종료가 확인된 중단·실패 작업만 다시 실행할 수 있어요.')
    args = list(job.args)
    if '--resume-run' in args:
        index = args.index('--resume-run')
        del args[index:index+2]
    if resume:
        if not job.checkpoint_run_id or args[0] != 'office_publish':
            raise ValueError('이 작업에는 재개할 일반 칼럼 체크포인트가 없어요.')
        import json
        from pathlib import Path
        from django.conf import settings
        try:
            data = json.loads(Path(settings.BASE_DIR, 'logs/lab-runs', str(job.checkpoint_run_id)+'.json').read_text(encoding='utf-8'))
            profile = data['metadata']['profile']
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError('체크포인트 정보를 읽을 수 없어요. 새 실행을 선택해 주세요.') from exc
        if '--profile' in args:
            args[args.index('--profile')+1] = profile
        else:
            args += ['--profile', profile]
        track = data['metadata'].get('column_track', '') or 'legacy'
        if '--track' in args:
            args[args.index('--track')+1] = track
        else:
            args += ['--track', track]
        args += ['--resume-run', str(job.checkpoint_run_id)]
    from django.contrib.auth.models import User
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    new = enqueue(args, draft=job.draft, by=str(actor_id or 'operator'), via='restart', actor=actor)
    append('job_restarted', actor_id=actor_id, draft_id=job.draft_id, payload={'old': job.pk, 'new': new.pk})
    return new
