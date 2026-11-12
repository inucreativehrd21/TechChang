"""승인 당시 자료와 사건을 변경 불가능한 응용 계층 해시 체인으로 남긴다."""
import hashlib
import json
from django.db import transaction
from django.utils import timezone


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), default=str).encode()).hexdigest()


def snapshot(draft):
    from .models import StageRun
    from .artifacts import manifest as asset_manifest
    qa = {k: v for k, v in (draft.qa_report or {}).items() if k != 'human_approval'}
    runs = StageRun.objects.filter(draft_id=draft.pk).exclude(stage='applied')
    last = runs.order_by('-pk').first()
    manifest = [{'id': row.pk, 'digest': fingerprint(row.output), 'text': row.text_digest, 'output': row.output}
                for row in runs.filter(run_id=last.run_id).order_by('pk')] if last else []
    result = {'subject': draft.subject, 'content': draft.content, 'check': draft.check_report,
            'review': qa, 'chart_path': draft.chart_path, 'chart_note': draft.chart_note,
            'stages': manifest, 'assets': asset_manifest(draft)}
    # 기존 승인 지문은 유지하고, 새 유형 원고부터 유형 변경도 승인을 무효화해요.
    if draft.column_track:
        result['column_track'] = draft.column_track
    return result


def event_digest(event):
    return fingerprint({k: getattr(event, k) for k in
                        ('sequence', 'created_at', 'action', 'actor_id', 'draft_id', 'payload', 'previous_digest')})


@transaction.atomic
def append(action, *, actor_id=None, draft_id=None, payload=None):
    from .models import AuditHead, AuditEvent
    AuditHead.objects.get_or_create(pk=1)
    head = AuditHead.objects.select_for_update().get(pk=1)
    event = AuditEvent(sequence=head.sequence + 1, created_at=timezone.now(), action=action,
                       actor_id=actor_id, draft_id=draft_id, payload=payload or {}, previous_digest=head.digest)
    event.digest = event_digest(event)
    event.save(force_insert=True)
    head.sequence, head.digest = event.sequence, event.digest
    head.save()
    return event


def verify():
    from .models import AuditEvent, AuditHead
    previous, sequence = '', 0
    for event in AuditEvent.objects.order_by('sequence').iterator():
        sequence += 1
        if event.sequence != sequence or event.previous_digest != previous or event.digest != event_digest(event):
            return False
        previous = event.digest
    head = AuditHead.objects.filter(pk=1).first()
    return (not head and sequence == 0) or bool(head and head.sequence == sequence and head.digest == previous)
