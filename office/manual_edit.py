"""운영자 직접 수정 발행 — 재작성 요청을 두 번 보내도 심사를 통과하지 못한 원고를 사람이 고쳐 올린다(2026-11-28 운영자 요청).

왜: 재작성·재심이 같은 자리를 맴돌았다(#72 직접 교열 4회 78점, #74 필수 0건인데 78점이라 일반·예외 승인이 모두 막힘).
기존 흐름(재작성 요청 → 검증·심사 → 승인)은 그대로 두고, 그 흐름이 두 번 실패한 원고에만 이 길을 연다.
직접 고친 판은 팩트체크·편집 심사를 다시 받지 않는다 — 운영자가 책임지고, 고치기 전·후 판과 사유를 감사 기록에 남긴다.
"""
from django.db import transaction
from django.utils import timezone

from .recorder import digest

AFTER_REQUESTS = 2
MAX_CONTENT = 200_000


def request_count(draft) -> int:
    """운영자 재작성 요청 횟수. 관리 화면 요청은 감사 기록, 메일 재심 요청은 작업 기록에만 남아 둘 중 큰 값을 쓴다."""
    from .models import AuditEvent, WorkLog
    audit = AuditEvent.objects.filter(draft_id=draft.pk, action='revision_requested').count()
    logged = WorkLog.objects.filter(draft_id=draft.pk, action='admin_note').count()
    return max(audit, logged)


def blocker(draft) -> str:
    """직접 수정 발행을 못 하는 이유. 빈 문자열이면 열린다."""
    from .models import ColumnDraft
    from .approval import policy
    if draft.status != ColumnDraft.STATUS_HOLD:
        return '검수 대기 원고만 직접 수정해 발행할 수 있어요.'
    try:
        policy(draft)
        return '검증·심사를 통과한 원고예요. 검수 승인을 사용해 주세요.'
    except ValueError:
        pass
    n = request_count(draft)
    if n < AFTER_REQUESTS:
        return f'재작성 요청을 {AFTER_REQUESTS}번 보낸 뒤에도 심사를 통과하지 못하면 열려요(지금 {n}번).'
    return ''


def marker_ok(draft) -> bool:
    """현재 제목·본문이 운영자가 직접 고쳐 저장한 바로 그 판인지."""
    mark = (draft.qa_report or {}).get('manual_edit')
    return (isinstance(mark, dict) and mark.get('subject_hash') == digest(draft.subject)
            and mark.get('content_hash') == digest(draft.content))


def check(draft) -> None:
    """approval.policy(mode='manual') — 심사·팩트체크 대신 '운영자가 고친 판'임과 이미지 보관만 확인한다."""
    if not draft.subject.strip() or not draft.content.strip():
        raise ValueError('제목과 본문을 입력해 주세요.')
    if not marker_ok(draft):
        raise ValueError('운영자가 직접 수정한 판이 아니에요. 검수 화면에서 다시 수정해 주세요.')
    from .artifacts import manifest
    manifest(draft, strict=True)


def publish(draft_id, user, *, subject, content, reason, expected_snapshot):
    """직접 고친 판을 저장하고 승인·공개까지 한 트랜잭션에서 마친다. 실패하면 아무것도 바뀌지 않는다."""
    from .models import ColumnDraft
    from .approval import approve_for_release
    from .audit import append, snapshot, fingerprint
    from .draft_state import guard
    from .security import is_operator
    subject, content = (subject or '').strip(), (content or '').replace('\r\n', '\n').strip() + '\n'
    reason = (reason or '').strip() or '재작성 두 번 뒤에도 심사 미통과 — 운영자가 지적사항을 직접 수정'
    if not is_operator(user):
        raise ValueError('운영자만 직접 수정해 발행할 수 있어요.')
    if not subject or not content.strip():
        raise ValueError('제목과 본문을 입력해 주세요.')
    if len(subject) > 200 or len(content) > MAX_CONTENT:
        raise ValueError('제목은 200자, 본문은 20만 자까지예요.')
    with transaction.atomic():
        draft = ColumnDraft.objects.select_for_update().get(pk=draft_id)
        busy = guard(draft, '직접 수정 발행')
        if busy:
            raise ValueError(busy)
        if not expected_snapshot or expected_snapshot != fingerprint(snapshot(draft)):
            raise ValueError('검수 화면을 연 뒤 원고가 바뀌었어요. 새로고침 후 다시 수정해 주세요.')
        why = blocker(draft)
        if why:
            raise ValueError(why)
        before = snapshot(draft)
        draft.subject, draft.content = subject, content
        draft.qa_report = {**{k: v for k, v in (draft.qa_report or {}).items() if k != 'human_approval'},
                           'manual_edit': {'actor': user.pk, 'at': timezone.now().isoformat(), 'reason': reason,
                                           'requests': request_count(draft),
                                           'previous_score': (draft.qa_report or {}).get('score'),
                                           'subject_hash': digest(subject), 'content_hash': digest(content)}}
        draft.save(update_fields=['subject', 'content', 'qa_report'])
        append('manual_edited', actor_id=user.pk, draft_id=draft.pk,
               payload={'reason': reason, 'before': before, 'subject': subject, 'content_hash': digest(content)})
        from .services import log
        log('lead', 'admin_edit', f'운영자 직접 수정: {subject[:80]} — {reason[:150]}', draft=draft)
        approve_for_release(draft.pk, user, expected_snapshot=fingerprint(snapshot(draft)), reason=reason, mode='manual')
        draft.refresh_from_db()
        approve_for_release(draft.pk, user, expected_snapshot=fingerprint(snapshot(draft)), now=True)
        draft.refresh_from_db()
    return draft
