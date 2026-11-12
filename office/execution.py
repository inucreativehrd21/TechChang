"""작업의 유효한 실행만 원고를 변경할 수 있다."""
import os
from contextlib import contextmanager
from django.db import transaction
from django.utils import timezone


class LeaseLost(RuntimeError):
    pass


def assert_current():
    job_id, token = os.environ.get('LAB_JOB_ID'), os.environ.get('LAB_EXECUTION_ID')
    if not job_id and not token:
        return
    from .models import JobRequest
    try:
        with transaction.atomic():
            valid = JobRequest.objects.select_for_update().filter(pk=job_id, execution_id=token,
                           status='started', lease_until__gt=timezone.now()).exists()
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise LeaseLost('작업 실행 권한이 만료됐어요. 이전 실행의 저장을 차단했어요.')


@transaction.atomic
def save_draft(draft, save, *args, **kwargs):
    assert_current()
    return save(*args, **kwargs)


@contextmanager
def commit_guard():
    """실행 행 잠금을 유지한 채 DB 변경 또는 파일 게시를 완료한다."""
    if not os.environ.get('LAB_JOB_ID') and not os.environ.get('LAB_EXECUTION_ID'):
        yield
        return
    with transaction.atomic():
        assert_current()
        yield
