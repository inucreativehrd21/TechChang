"""검수 화면이 원고를 '작업 중'으로 볼지 — 재작성이 작업 대기열에 들어간 것까지 포함한다.

재작성 요청은 작업 대기열(JobRequest)에 저장되고 cron 실행기가 나중에 집어 간다. 그동안 원고 상태(status)는 그대로
'검수 대기'라서 상태만 보면 수정 지시 박스·승인·반려가 계속 살아 있고, 그 사이의 재요청·승인·반려가 곧 돌 작업과 엇갈린다.
(재작성이 대기 중일 때 반려하면 작업이 반려 원고를 되살리고, 승인·공개하면 곧 덮어쓸 옛 원고가 공개된다 — worker_runtime 은
hold·revising·rejected 원고를 모두 처리한다.) 화면과 서버(뷰)가 같은 판정을 쓰도록 한 곳에 둔다.
"""
from .models import ColumnDraft, JobRequest

QUEUED, RUNNING, ATTENTION = 'queued', 'running', 'attention'
BUSY_JOB_STATUSES = (JobRequest.ST_PENDING, JobRequest.ST_STARTED, 'quarantined')

MESSAGES = {
    QUEUED: '재작성 요청이 대기 중이에요. 연구팀이 끝낸 뒤에 {action}할 수 있어요.',
    RUNNING: '연구팀이 재작성 중이에요. 끝난 뒤에 {action}할 수 있어요.',
    ATTENTION: '이 원고의 작업이 종료 확인을 기다리고 있어요. 작업 상태에서 확인한 뒤에 {action}할 수 있어요.',
}


def active_jobs(draft_ids) -> dict:
    """{원고 id: 가장 최근의 진행 중 작업} — 대기·실행·종료 확인 필요."""
    jobs = {}
    rows = JobRequest.objects.filter(draft_id__in=list(draft_ids), status__in=BUSY_JOB_STATUSES).order_by('created_at', 'pk')
    for job in rows:
        jobs[job.draft_id] = job
    return jobs


def busy_job(draft):
    return (JobRequest.objects.filter(draft=draft, status__in=BUSY_JOB_STATUSES)
            .order_by('-created_at', '-pk').first())


def state_of(draft, job=None):
    """손댈 수 있으면 None, 아니면 queued(대기열) / running(재작성 중) / attention(종료 확인 필요)."""
    if job is not None:
        if job.status == 'quarantined':
            return ATTENTION
        if job.status == JobRequest.ST_STARTED or draft.status == ColumnDraft.STATUS_REVISING:
            return RUNNING
        return QUEUED
    return RUNNING if draft.status == ColumnDraft.STATUS_REVISING else None


def guard(draft, action: str):
    """서버 쪽 막이 — 작업 중이면 사용자에게 보일 안내 문장, 아니면 None. action 은 '승인·공개'·'반려'·'재요청'처럼 동작 이름."""
    state = state_of(draft, busy_job(draft))
    return MESSAGES[state].format(action=action) if state else None
