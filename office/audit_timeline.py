"""감사 기록(AuditEvent)을 운영자가 읽는 타임라인으로 바꾼다.

원본 JSON 은 해시 체인 그대로라 읽기 어렵고, approved·revision_requested 의 payload 에는 원고 전문이 통째로 들어 있다.
그래서 화면에는 '누가·언제·무엇을·결과가 어땠는지'만 사람 말로 요약해 싣고 원문은 싣지 않는다(원본은 audit.json 에 그대로).
"""
from collections import OrderedDict

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from . import audit
from .models import AuditEvent, ColumnDraft, JobRequest

# 색은 의미를 따른다 — ask 운영자 지시 / ok 승인·공개 / warn 취소·중단·예외 / bad 실패·반려 / sys 연구팀 자동 작업
JOB_STATUS = dict(JobRequest.ST_CHOICES)
DRAFT_STATUS = dict(ColumnDraft.STATUS_CHOICES)
SYSTEM = '자동 실행'


def _score(payload):
    """그 시점의 편집 심사 점수(100점). 구버전 10점 척도는 환산한다."""
    for first in ('before', 'snapshot'):
        review = ((payload.get(first) or {}).get('review') or {}) if isinstance(payload.get(first), dict) else {}
        if review.get('score') is not None:
            try:
                value = int(review['score'])
            except (TypeError, ValueError):
                return None
            return value * 10 if value <= 10 else value
    return None


def _job(payload, key='job'):
    return f"#{payload[key]}" if payload.get(key) else '-'


def describe(event, actor):
    """이벤트 하나 → 화면용 dict. 모르는 종류도 원래 이름으로 보여 준다."""
    p = event.payload if isinstance(event.payload, dict) else {}
    action = event.action
    out = dict(tone='sys', label='기록', title=action, quote='', facts=[], link=None)
    score = _score(p)
    if action == 'revision_requested':
        out.update(tone='ask', label='수정 지시', title='재작성을 요청했어요', quote=p.get('note', ''))
        if score is not None:
            out['facts'].append(('요청 당시 심사', f'{score}점'))
        picked = [r for r in p.get('feedback') or [] if isinstance(r, dict)]
        if picked:
            kinds = OrderedDict()
            for r in picked:
                kinds[r.get('label') or r.get('kind', '')] = kinds.get(r.get('label') or r.get('kind', ''), 0) + 1
            out['facts'].append(('반영할 지적', ' · '.join(f'{k} {n}' for k, n in kinds.items())))
        if p.get('reopened'):
            out['facts'].append(('다시 연 해결 지적', ', '.join(p['reopened'])))
    elif action == 'job_started':
        out.update(label='연구팀 작업', title='재작성을 시작했어요')
        out['facts'].append(('작업', _job(p)))
    elif action == 'job_finished':
        status = p.get('status', '')
        failed = status in ('failed', 'interrupted', 'quarantined')
        out.update(tone='bad' if failed else 'sys', label='연구팀 작업',
                   title='작업이 실패했어요' if status == 'failed' else '작업이 끝났어요' if status == 'completed'
                   else f"작업이 {JOB_STATUS.get(status, status or '종료')} 상태로 끝났어요")
        out['facts'].append(('작업', _job(p)))
        if p.get('exit_code') not in (None, 0):
            out['facts'].append(('종료 코드', str(p['exit_code'])))
        if p.get('business_result'):
            out['facts'].append(('원고 상태', DRAFT_STATUS.get(p['business_result'], p['business_result'])))
    elif action == 'job_interrupted':
        stopped = p.get('stopped', True)
        out.update(tone='warn', label='연구팀 작업', title='작업이 중단됐어요' if stopped else '작업 종료 확인이 필요해요')
        out['facts'].append(('작업', _job(p)))
    elif action == 'job_cancelled':
        out.update(tone='warn', label='작업 관리', title='작업을 취소했어요' if p.get('status') != 'quarantined'
                   else '작업을 취소했지만 종료 확인이 필요해요')
        out['facts'].append(('작업', _job(p)))
    elif action == 'job_restarted':
        out.update(tone='warn', label='작업 관리', title='작업을 다시 시작했어요')
        out['facts'].append(('작업', f"#{p.get('old', '?')} → #{p.get('new', '?')}"))
    elif action in ('approved', 'exception_approved'):
        exception = action == 'exception_approved'
        out.update(tone='warn' if exception else 'ok', label='예외 승인' if exception else '승인',
                   title='예외로 승인했어요' if exception else '검수를 승인했어요', quote=p.get('reason', ''))
        if score is not None:
            out['facts'].append(('승인 당시 심사', f'{score}점'))
    elif action == 'release_queued':
        out.update(tone='ok', label='공개 대기', title='승인한 원고를 공개 대기로 옮겼어요')
        out['facts'].append(('공개 방식', '예약 공개' if p.get('publish_at') else '지금 공개 버튼으로 수동 공개'))
        if p.get('previous_publish_at') and not p.get('publish_at'):
            out['facts'].append(('지난 예약', '즉시 공개되지 않도록 해제했어요'))
    elif action == 'approval_revoked':
        out.update(tone='warn', label='승인', title='승인을 취소했어요')
        if p.get('reason'):
            out['facts'].append(('사유', p['reason']))
        if p.get('approval'):
            out['facts'].append(('취소한 승인', f"기록 #{p['approval']}"))
    elif action == 'rejected':
        out.update(tone='bad', label='반려', title='원고를 반려했어요')
    elif action == 'published':
        out.update(tone='ok', label='공개', title='칼럼으로 공개했어요')
        if p.get('question_id'):
            out['link'] = ('공개된 칼럼 보기', reverse('community:detail', args=[p['question_id']]))
        if p.get('approval'):
            out['facts'].append(('근거 승인', f"기록 #{p['approval']}"))
    elif action == 'draft_recovered':
        out.update(tone='warn', label='복구', title='제작 기록에서 원고를 복구했어요')
        if p.get('source'):
            out['facts'].append(('복구 출처', str(p['source'])))
    elif action == 'chart_revision_created':
        out.update(label='차트', title='차트 수정본을 만들었어요')
    out['actor'] = actor
    return out


def build(draft_id):
    """한 원고의 감사 기록 화면 묶음. 사슬 전체 검증(audit.verify)은 전역 해시 체인이라 한 번만 돌린다."""
    events = list(AuditEvent.objects.filter(draft_id=draft_id).order_by('-sequence'))
    users = {u.pk: u.get_username() for u in User.objects.filter(pk__in={e.actor_id for e in events if e.actor_id})}
    days = OrderedDict()
    counts = {'asked': 0, 'approved': 0, 'exception': 0, 'published': None, 'last': None}
    for event in events:                                    # 최신 → 과거 순
        at = timezone.localtime(event.created_at)
        row = describe(event, users.get(event.actor_id, f'사용자 #{event.actor_id}') if event.actor_id else SYSTEM)
        row.update(sequence=event.sequence, at=at, hash=event.digest[:10], intact=audit.event_digest(event) == event.digest)
        days.setdefault(at.date(), []).append(row)
        if counts['last'] is None:
            counts['last'] = at
        if event.action == 'revision_requested':
            counts['asked'] += 1
        elif event.action == 'approved':
            counts['approved'] += 1
        elif event.action == 'exception_approved':
            counts['exception'] += 1
        elif event.action == 'published' and counts['published'] is None:
            counts['published'] = at
    return {'days': [{'day': d, 'rows': rows} for d, rows in days.items()], 'total': len(events), 'counts': counts,
            'chain_ok': audit.verify(), 'chain_total': AuditEvent.objects.count(),
            'broken': [r['sequence'] for rows in days.values() for r in rows if not r['intact']]}
