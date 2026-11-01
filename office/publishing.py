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
            approved = manual and bool(getattr(kwargs.get('by'), 'is_staff', False))
            if blocked(qa) and not approved:
                raise ValueError('필수 결함 또는 미해결 심사가 남아 발행할 수 없어요.')
            if qa.get('review_contract_version') == 2 and not approved:
                if (not publishable(qa) or qa.get('verified_content_hash') != verification_hash(draft.content)
                        or qa.get('reviewed_full_hash') != digest(draft.content)
                        or qa.get('verified_subject') != draft.subject):
                    raise ValueError('현재 원고의 독립 검증과 편집 심사가 필요해요.')
            result = fn(draft, *args, **kwargs)
            draft.refresh_from_db()
            return result
    return publish
