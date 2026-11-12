"""검증 계약을 확인하고 같은 원고의 중복 발행을 트랜잭션으로 막는다."""
from functools import wraps
from django.db import transaction


def guarded_publication(fn):
    @wraps(fn)
    def publish(draft, *args, manual=False, **kwargs):
        from .models import ColumnDraft
        from .review_protocol import blocked, publishable
        from .pipeline import verification_hash
        from .recorder import digest
        with transaction.atomic():
            locked = ColumnDraft.objects.select_for_update().get(pk=draft.pk)
            if locked.status == ColumnDraft.STATUS_PUBLISHED and locked.question_id:
                draft.refresh_from_db()
                return locked.question
            # 호출자가 방금 심사한 원고는 아직 저장 전일 수 있다. DB 잠금은 중복 공개를 막고,
            # 검증·발행 대상은 호출자가 넘긴 같은 버전으로 유지한다.
            qa = draft.qa_report or {}
            from .approval import valid, policy
            from .execution import assert_current
            assert_current()
            approved = (valid(locked) and valid(draft)
                        and (locked.qa_report or {}).get('human_approval') == qa.get('human_approval'))
            if not approved:
                raise ValueError('현재 제목·본문에 대한 운영자 승인이 필요해요.')
            policy(draft, qa.get('human_approval', {}).get('mode', 'normal'))
            result = fn(draft, *args, **kwargs)
            from .audit import append
            append('published', actor_id=draft.decided_by_id, draft_id=draft.pk,
                   payload={'approval': qa.get('human_approval', {}).get('audit_sequence'), 'question_id': result.pk})
            draft.refresh_from_db()
            return result
    return publish
