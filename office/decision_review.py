"""회의 전체의 선택·의견을 한 번에 검증하고 저장해요."""
from django.core import signing
from django.db import transaction
from django.utils import timezone
from .audit import fingerprint, append
from .models import Decision, Meeting, Task, WorkLog

SALT = 'office.meeting-decision-review.v1'


class ReviewError(ValueError):
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or {}


def version(d):
    return fingerprint({'id': d.pk, 'meeting': d.meeting_id, 'kind': d.kind, 'topic': d.topic,
        'track': d.column_track, 'question': d.question, 'options': d.options,
        'key': d.chosen_key, 'note': d.note, 'chosen_at': d.chosen_at, 'consumed_at': d.consumed_at})


def lock_reason(d):
    if d.consumed_at or d.drafts.exists():
        return '원고 제작에 사용한 안건이라 선택을 바꿀 수 없어요.'
    if d.tasks.exists():
        return '정비 작업으로 등록한 안건이라 선택을 바꿀 수 없어요.'
    return ''


def decorate(d, payload=None, error=''):
    d.review_token = signing.dumps({'id': d.pk, 'key': d.chosen_key, 'note': d.note, 'version': version(d)}, salt=SALT)
    d.review_locked = lock_reason(d)
    d.form_key, d.form_note = d.chosen_key, d.note
    if payload is not None:
        d.form_key = payload.get(f'choice_{d.pk}', d.chosen_key)
        d.form_note = payload.get(f'note_{d.pk}', d.note)
    d.attempted_note = d.form_note if d.review_locked and d.form_note != d.note else ''
    if d.review_locked:
        d.form_key, d.form_note = d.chosen_key, d.note
    d.review_error = error
    return d


@transaction.atomic
def save_review(meeting_id, payload, user):
    meeting = Meeting.objects.select_for_update().get(pk=meeting_id)
    decisions = list(Decision.objects.select_for_update().filter(meeting=meeting).order_by('pk'))
    ids = payload.getlist('decision_ids')
    if len(ids) != len(set(ids)) or set(ids) != {str(d.pk) for d in decisions}:
        raise ReviewError('회의 안건 구성이 달라졌어요. 표시된 선택을 확인한 뒤 다시 저장해 주세요.')
    changes, errors = [], {}
    for d in decisions:
        try:
            baseline = signing.loads(payload.get(f'version_{d.pk}', ''), salt=SALT, max_age=86400)
            if not isinstance(baseline, dict) or baseline.get('id') != d.pk:
                raise signing.BadSignature('wrong decision')
        except (signing.BadSignature, TypeError, ValueError):
            errors[d.pk] = '검토 화면이 만료됐어요. 선택과 의견을 확인한 뒤 다시 저장해 주세요.'
            continue
        key = payload.get(f'choice_{d.pk}', baseline['key'])
        note = payload.get(f'note_{d.pk}', baseline['note']).strip()
        if (key, note) == (baseline['key'], baseline['note']):
            continue  # 다른 탭이 바꾼, 이 화면에서 손대지 않은 항목은 덮어쓰지 않아요.
        if (key, note) == (d.chosen_key, d.note):
            continue  # 같은 POST가 반복돼도 작업·로그·후속 실행을 중복 생성하지 않아요.
        allowed = {str(o.get('key')) for o in d.options if isinstance(o, dict)}
        if (key and key not in allowed) or (not key and d.chosen_key):
            errors[d.pk] = '안건에 있는 주제 하나를 선택해 주세요.'
        elif len(note) > 300:
            errors[d.pk] = '의견은 300자 이내로 적어 주세요. 입력한 내용은 아래에 남겨뒀어요.'
        elif version(d) != baseline.get('version'):
            errors[d.pk] = '다른 화면에서 결정이 바뀌었어요. 현재 저장 내용과 입력한 내용을 비교해 주세요.'
        elif lock_reason(d):
            errors[d.pk] = lock_reason(d)
        else:
            changes.append((d, key, note))
    if errors:
        raise ReviewError('저장하지 않았어요. 표시된 안건을 확인해 주세요. 선택과 의견은 그대로 남아 있어요.', errors)
    now = timezone.now()
    task_count = 0
    for d, key, note in changes:
        before = {'key': d.chosen_key, 'note': d.note}
        d.chosen_key, d.note = key, note
        d.chosen_by, d.chosen_at = (user, now) if key else (None, None)
        d.public_note = ''  # 바뀐 선택에 옛 공개 소개를 재사용하지 않아요.
        d.save(update_fields=['chosen_key', 'note', 'chosen_by', 'chosen_at', 'public_note'])
        append('meeting_decision_saved', actor_id=user.pk, payload={
            'meeting_id': meeting.pk, 'decision_id': d.pk, 'before': before, 'after': {'key': key, 'note': note}})
        if key:
            WorkLog.objects.create(agent='lead', action='decision', meeting=meeting,
                text=f"관리자 결정: {d.question} → {(d.chosen or {}).get('title', '')}")
        if key and d.kind in (Decision.KIND_DEV, Decision.KIND_OPS) and not d.tasks.exists():
            ch = d.chosen or {}
            task = Task.objects.create(source=Task.SRC_MEETING, decision=d,
                title=ch.get('title', d.question)[:300],
                body=f"{ch.get('detail', '')}\n\n안건: {d.question}\n제안: {ch.get('proposed_by', '')}\n운영자 의견: {note}",
                kind=Task.KIND_OPS if d.kind == Decision.KIND_OPS else Task.KIND_DEV)
            WorkLog.objects.create(agent='coding', action='crew', text=f'정비 백로그 등록 #{task.pk}: {task.title}')
            task_count += 1
    pending = sum(not d.chosen_key for d in decisions)
    previous_status = meeting.status
    meeting.status = Meeting.STATUS_OPEN if pending else Meeting.STATUS_CLOSED
    if changes:
        meeting.public_summary = ''
    meeting.save(update_fields=['status', 'public_summary'])
    return {'changed': len(changes), 'pending': pending, 'tasks': task_count,
            'polish': not pending and (bool(changes) or previous_status != Meeting.STATUS_CLOSED)}
