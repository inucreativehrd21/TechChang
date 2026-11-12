"""사람의 승인을 정확한 제목·본문 버전에 묶는다."""
from django.utils import timezone
from django.db import transaction
from .recorder import digest
from .audit import snapshot, fingerprint, append


def policy(draft, mode='normal'):
    from .pipeline import verification_hash
    from .review_protocol import publishable, must_fix_items
    check, qa = draft.check_report or {}, draft.qa_report or {}
    if not isinstance(check, dict) or not isinstance(qa, dict):
        raise ValueError('검증·심사 보고서 형식이 올바르지 않아요.')
    from .editorial import review_failures
    if qa.get('column_track', '') != draft.column_track or review_failures(qa, draft.content, draft.column_track):
        raise ValueError('현재 칼럼 유형에 맞는 편집 심사를 먼저 통과해야 해요.')
    revision = qa.get('admin_revision')
    if revision is not None and (not isinstance(revision, dict) or revision.get('status') != 'adopted'):
        raise ValueError('관리자 수정 요청이 완료되지 않았어요. 요청별 결과를 확인해 주세요.')
    from .evidence_bundle import validate
    validate(draft)
    from .artifacts import manifest
    manifest(draft, strict=True)
    if (check.get('verdict') != 'pass' or check.get('verification_hash') != verification_hash(draft.content)
            or check.get('subject') != draft.subject
            or any(c.get('status') in ('wrong', 'unverifiable', 'outdated') for c in check.get('claims', []) if isinstance(c, dict))
            or check.get('critical') or check.get('duplicate')):
        raise ValueError('현재 원고의 사실 검증을 먼저 통과해야 해요.')
    if (qa.get('reviewed_full_hash') != digest(draft.content) or qa.get('verified_subject') != draft.subject
            or qa.get('verified_content_hash') != verification_hash(draft.content)):
        raise ValueError('현재 원고 버전의 편집 심사가 필요해요.')
    if mode == 'normal':
        if not publishable(qa):
            raise ValueError('필수 수정이 남아 있어요. 수정하거나 형식 예외 승인을 선택해 주세요.')
    elif mode == 'exception':
        allowed = {'style_broken', 'too_short'}
        if not qa.get('fatal') and not must_fix_items(qa):
            raise ValueError('예외 승인할 형식 결함이 없어요. 일반 승인을 사용해 주세요.')
        if set(qa.get('fatal') or []) - allowed or any(
                item.get('kind') not in ('style', 'format') for item in must_fix_items(qa)):
            raise ValueError('문체·형식 외의 결함은 예외 승인할 수 없어요.')
        if qa.get('unresolved_issue_ids') or any(v is False for v in qa.get('resolved', [])):
            raise ValueError('해결하지 않은 심사 지적은 예외 승인할 수 없어요.')
    else:
        raise ValueError('올바른 승인 방식을 선택해 주세요.')


def valid(draft):
    if draft.status not in ('hold', 'ready', 'published'):
        return False
    if not isinstance(draft.qa_report, dict):
        return False
    try:
        from .evidence_bundle import validate
        validate(draft)
    except ValueError:
        return False
    approval = draft.qa_report.get('human_approval') or {}
    if not isinstance(approval, dict) or type(approval.get('audit_sequence')) is not int:
        return False
    from .security import is_operator
    from .models import AuditEvent
    event = AuditEvent.objects.filter(sequence=approval.get('audit_sequence'), draft_id=draft.pk,
                                      actor_id=draft.decided_by_id, action__in=['approved', 'exception_approved']).first()
    from .audit import event_digest
    from .artifacts import verify_archive
    return (event is not None and event.digest == event_digest(event)
            and verify_archive(event.payload.get('snapshot', {}).get('assets', []))
            and event.payload.get('mode') == approval.get('mode')
            and event.payload.get('reason') == approval.get('reason')
            and fingerprint(event.payload.get('snapshot')) == approval.get('snapshot_hash')
            and approval.get('subject_hash') == digest(draft.subject)
            and approval.get('content_hash') == digest(draft.content)
            and bool(draft.decided_by_id) and approval.get('actor') == draft.decided_by_id
            and is_operator(draft.decided_by)
            and approval.get('snapshot_hash') == fingerprint(snapshot(draft)))


@transaction.atomic
def approve(draft, user, reason='', mode='normal', expected_snapshot=None):
    from .review_protocol import publishable
    from .models import ColumnDraft
    current = ColumnDraft.objects.select_for_update().get(pk=draft.pk)
    if (current.subject != draft.subject or current.content != draft.content
            or current.column_track != draft.column_track
            or current.qa_report != draft.qa_report or current.check_report != draft.check_report
            or current.chart_path != draft.chart_path or current.chart_note != draft.chart_note
            or (expected_snapshot is not None and fingerprint(snapshot(current)) != expected_snapshot)):
        raise ValueError('검수 중 원고가 바뀌었어요. 새로고침한 뒤 다시 확인해 주세요.')
    from .security import is_operator
    if not is_operator(user):
        raise ValueError('운영자만 승인할 수 있어요.')
    policy(draft, mode)
    exception = mode == 'exception'
    if exception and not reason.strip():
        raise ValueError('심사 미통과 원고의 예외 공개 사유를 입력해 주세요.')
    artifact = snapshot(draft)
    from .artifacts import archive
    archive(artifact['assets'])
    event = append('exception_approved' if exception else 'approved', actor_id=user.pk, draft_id=draft.pk,
                   payload={'reason': reason.strip(), 'mode': mode, 'snapshot': artifact})
    draft.qa_report = {**(draft.qa_report or {}), 'human_approval': {
        'actor': user.pk, 'at': timezone.now().isoformat(), 'reason': reason.strip(),
        'exception': exception, 'mode': mode, 'audit_sequence': event.sequence,
        'snapshot_hash': fingerprint(artifact), 'subject_hash': digest(draft.subject),
        'content_hash': digest(draft.content)}}
    draft.decided_by, draft.decided_at = user, timezone.now()
    draft.save(update_fields=['qa_report', 'decided_by', 'decided_at'])
    from .models import WorkLog
    WorkLog.objects.create(agent='lead', action='approve', draft=draft,
                           text=(f'운영자 승인: {user.pk} · 예외={exception} · 제목={digest(draft.subject)} '
                                 f'본문={digest(draft.content)} · {reason}')[:300])


@transaction.atomic
def revoke(draft, user, reason):
    from .security import is_operator
    if not is_operator(user):
        raise ValueError('운영자만 승인을 취소할 수 있어요.')
    from .models import ColumnDraft
    current = ColumnDraft.objects.select_for_update().get(pk=draft.pk)
    old = (current.qa_report or {}).get('human_approval')
    if old:
        current.qa_report = {k: v for k, v in current.qa_report.items() if k != 'human_approval'}
        current.save(update_fields=['qa_report'])
        draft.qa_report = current.qa_report
        append('approval_revoked', actor_id=user.pk, draft_id=draft.pk,
               payload={'approval': old.get('audit_sequence'), 'reason': reason})
