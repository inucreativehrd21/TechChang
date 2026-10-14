"""예약 공개 — 칼럼을 전날 미리 만들어 심사·보완을 끝내 두고, 정해진 시각에 공개한다.

예전에는 공개 시각(화·목·토 10시, 연재 월 10시)에 제작을 시작했다. 심사에서 막히면 그 자리에서 보류돼
운영자가 볼 때까지 무기한 미뤄졌다. 이제는:
  - 전날 13시 `--prepare`: 다음 공개 시각(slot)을 정해 원고에 적어 두고(publish_at) 끝까지 만든다.
    심사를 통과하면 '공개 대기'(ready), 미달이면 보류 + 운영자에게 메일(하루의 여유).
    22시에 한 번 더 — 13시 실행이 예외로 실패했을 때만 다시 만든다(보류·대기 중이면 건너뜀).
  - 10분마다 `office_release`: 예정 시각이 지난 '공개 대기' 원고를 발행한다.
  - 당일 10시 `--if-missing`: 그 시각 몫의 원고가 아예 없을 때만 예전처럼 바로 만든다(최후의 안전망).
운영자가 보류 원고를 고쳐 통과시키면, 예정 시각 전이면 공개 대기로, 지났으면 바로 발행된다(finish_accepted).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

PUBLISH_HOUR = 10
COLUMN_WEEKDAY = {'hrd': 1, 'data': 3, 'coding': 5}      # 화·목·토 (월=0)
SERIES_WEEKDAY = 0                                         # 월 — 시리즈는 ISO 주 홀짝(series_catalog.SCHEDULE)
# 이 상태의 원고가 이미 있으면 그 시각 몫은 '찼다' — 같은 시각에 두 편을 만들지 않는다
TAKEN = ('ready', 'published', 'hold', 'revising')


def _at(day) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(PUBLISH_HOUR)))


def column_slot(topic: str, now=None, *, upcoming: bool = True):
    """칼럼 공개 시각. upcoming: 지금 이후의 첫 공개 시각(전날 준비용).
    아니면 오늘이 공개 요일일 때 오늘 10시(당일 안전망용), 아니면 None."""
    now = timezone.localtime(now) if now else timezone.localtime()
    wd = COLUMN_WEEKDAY[topic]
    if not upcoming:
        return _at(now.date()) if now.weekday() == wd else None
    at = _at(now.date() + timedelta(days=(wd - now.weekday()) % 7))
    return at if at > now else at + timedelta(days=7)


def series_slot(now=None, *, upcoming: bool = True):
    """연재 공개 (시리즈 키, 시각). 키는 공개일의 ISO 주 홀짝으로 정한다 — 일요일의 주 번호는 월요일과 다르다."""
    from community.series_catalog import SCHEDULE
    now = timezone.localtime(now) if now else timezone.localtime()
    if upcoming:
        at = _at(now.date() + timedelta(days=(SERIES_WEEKDAY - now.weekday()) % 7))
        if at <= now:
            at += timedelta(days=7)
    elif now.weekday() == SERIES_WEEKDAY:
        at = _at(now.date())
    else:
        return None, None
    parity = at.date().isocalendar()[1] % 2
    key = next((k for k, s in SCHEDULE.items() if s['weekday'] == SERIES_WEEKDAY and s['week_parity'] == parity), None)
    return key, at


def taken(at, *, topic: str | None = None, series_key: str | None = None):
    """그 시각 몫으로 이미 진행 중이거나 끝난 원고(없으면 None)."""
    from office.models import ColumnDraft
    qs = ColumnDraft.objects.filter(publish_at=at, status__in=TAKEN)
    qs = qs.filter(series_key=series_key) if series_key else qs.filter(topic=topic, series_key='')
    return qs.order_by('-created_at').first()


def finish_accepted(draft, publish, *, by=None):
    """심사를 통과한 원고 — 공개 예정 시각이 남았으면 '공개 대기'로 두고(None 반환), 지났거나 없으면 바로 발행."""
    from office.models import ColumnDraft
    if draft.publish_at and draft.publish_at > timezone.now() and not draft.target_question_id:
        draft.status = ColumnDraft.STATUS_READY
        if by is not None:
            draft.decided_by, draft.decided_at = by, timezone.now()
        draft.save()
        return None
    return publish(draft, by=by)


def ready_line(draft) -> str:
    return (f'공개 대기: {draft.subject} — {timezone.localtime(draft.publish_at):%m.%d %H:%M} 공개 예정'
            f' ({(draft.qa_report or {}).get("score", "-")}점)')


def publish_now(draft, *, by=None):
    """공개 대기 원고를 지금 발행한다(예정 시각 도래 또는 운영자의 '지금 공개')."""
    from office import pipeline as P
    from office.services import log
    if draft.series_key:
        from office.series_pipeline import publish
        q = publish(draft, by=by)
    else:
        q = P.publish_draft(draft, by=by)
    log('lead', 'publish', f'발행: {draft.subject} (id={q.pk}, {(draft.qa_report or {}).get("score", "-")}점)'
                           + (' — 예정 시각 공개' if by is None else ' — 운영자가 바로 공개'), draft=draft)
    return q


def release_due(now=None, out=print) -> list:
    """예정 시각이 지난 '공개 대기' 원고를 발행한다. 반환: 발행한 Question 목록."""
    from office.models import ColumnDraft
    now = now or timezone.now()
    done = []
    for d in ColumnDraft.objects.filter(status=ColumnDraft.STATUS_READY, publish_at__lte=now).order_by('publish_at'):
        try:
            q = publish_now(d)
            done.append(q)
            out(f'예약 공개: #{q.pk} {d.subject}')
        except Exception:  # noqa: BLE001 — 한 편이 실패해도 다음 편은 낸다
            logger.exception('예약 공개 실패: draft=%s', d.pk)
            out(f'예약 공개 실패: draft {d.pk} {d.subject}')
    return done


def alert(subject: str, lines: list[str]) -> bool:
    """운영자에게 메일(.env DJANGO_ADMIN_EMAIL, 없으면 ADMINS). 실패해도 제작은 멈추지 않는다."""
    from django.conf import settings
    from django.core.mail import EmailMessage
    from common.views import _admin_otp_recipient
    to = _admin_otp_recipient()
    if not to:
        return False
    try:
        EmailMessage(subject=f'[TechChang] {subject}', body='\n'.join(lines + ['', '검수: https://techchang.com/lab/admin/']),
                     from_email=settings.DEFAULT_FROM_EMAIL, to=[to]).send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001
        logger.exception('운영자 알림 메일 실패: %s', subject)
        return False


def alert_not_ready(draft, label: str, reason: str) -> bool:
    """전날 준비가 심사를 통과하지 못했다 — 공개 전까지 운영자가 손볼 수 있게 알린다."""
    from office import review_protocol as R
    qa = draft.qa_report or {}
    when = f'{timezone.localtime(draft.publish_at):%m.%d(%a) %H:%M}' if draft.publish_at else '(예정 없음)'
    lines = [f'{when} 공개 예정인 {label} 원고가 준비 단계에서 {reason}.',
             f'제목: {draft.subject or draft.brief or "(제목 없음)"}',
             f'편집 심사: {qa.get("score", "-")}점 · 판정 {qa.get("verdict", "-")}'
             + (f' · 치명 결함 {", ".join(qa.get("fatal") or [])}' if qa.get('fatal') else ''), '']
    must = R.must_fix_items(qa)
    if must:
        lines.append('남은 필수 수정:')
        lines += [f'  - {R.as_line(m)}' for m in must]
    elif qa.get('notes'):
        lines.append(f'편집장: {qa["notes"]}')
    lines += ['', '공개 시각 전에 /lab/admin/ 에서 수정 지시나 교열을 하면, 통과하는 즉시 공개 대기로 들어가 그 시각에 공개됩니다.']
    return alert(f'{when} 공개 예정 {label} — {reason}', lines)
