"""연구실 일정을 '며칠'(schedule 앱) 달력에 얹는 피드.

settings.SCHEDULE['FEED_PROVIDERS'] 에 'office.calendar_feed.lab_schedule' 로 연결한다. 방향은 한쪽뿐이다 —
office 가 schedule 의 FeedItem 을 쓰고, schedule 은 office 를 모른다. 이 파일을 지우고 설정에서 빼면
달력은 회원 일정만으로 그대로 동작한다.

올리는 것:
  - 발행된 칼럼·연재 (글 링크)
  - 공개 대기 원고(심사 통과, publish_at 예약) — 운영진이 아니면 제목을 숨기고 분야만 보인다
  - 앞으로 3주의 정기 칼럼 공개 시각(office.schedule 의 요일·시각) 중 아직 원고가 잡히지 않은 것
  - 발행된 연구실 위클리, 열린 편집회의
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from office.models import ColumnDraft, Meeting, Newsletter
from office.schedule import COLUMN_WEEKDAY, PUBLISH_HOUR
from schedule.feeds import FeedItem

TOPIC_LABEL = {'hrd': 'HRD', 'data': '데이터분석', 'coding': '프로그래밍'}
PROJECTION_DAYS = 21


def _local(dt) -> tuple:
    at = timezone.localtime(dt)
    return at.date(), at.time().replace(second=0, microsecond=0)


def _kind(draft) -> tuple[str, str, str]:
    """(슬롯 키, 표시 이름, 아이콘)"""
    if draft.series_key:
        return 'series', '연재', 'fa-book-open'
    return draft.topic, f'{TOPIC_LABEL.get(draft.topic, draft.topic)} 칼럼', 'fa-feather'


def lab_schedule(start, end, user):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz)
    hi = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    staff = bool(getattr(user, 'is_staff', False))
    items: list[FeedItem] = []
    seen: set[str] = set()
    filled: set[tuple] = set()      # (날짜, 슬롯 키) — 이미 발행됐거나 예약된 공개 시각

    published = (ColumnDraft.objects
                 .filter(status=ColumnDraft.STATUS_PUBLISHED, question__isnull=False,
                         question__create_date__gte=lo, question__create_date__lt=hi)
                 .select_related('question'))
    for draft in published:
        question = draft.question
        key = f'lab:post:{question.pk}'
        if key in seen:                 # 리메이크 원고는 같은 글을 가리킨다
            continue
        seen.add(key)
        slot, label, icon = _kind(draft)
        day, at = _local(question.create_date)
        filled.add((day, slot))
        items.append(FeedItem(key=key, title=question.subject, start_date=day, time=at, icon=icon,
                              url=reverse('community:detail', args=[question.pk]), note=label))

    for draft in ColumnDraft.objects.filter(status=ColumnDraft.STATUS_READY, publish_at__gte=lo, publish_at__lt=hi):
        slot, label, icon = _kind(draft)
        day, at = _local(draft.publish_at)
        filled.add((day, slot))
        title = (draft.subject or draft.brief or label) if staff else f'{label} 공개'
        items.append(FeedItem(key=f'lab:ready:{draft.pk}', title=title, start_date=day, time=at,
                              icon=icon, note='공개 예정'))

    now = timezone.now()
    day = max(start, timezone.localdate())
    last = min(end, timezone.localdate() + timedelta(days=PROJECTION_DAYS))
    while day <= last:
        for topic, weekday in COLUMN_WEEKDAY.items():
            if day.weekday() != weekday or (day, topic) in filled:
                continue
            if timezone.make_aware(datetime.combine(day, time(PUBLISH_HOUR)), tz) <= now:
                continue
            items.append(FeedItem(key=f'lab:slot:{topic}:{day:%Y%m%d}',
                                  title=f'{TOPIC_LABEL[topic]} 칼럼 공개', start_date=day,
                                  time=time(PUBLISH_HOUR), icon='fa-feather', note='정기 공개',
                                  listed=False))
        day += timedelta(days=1)

    for issue in Newsletter.objects.filter(status=Newsletter.STATUS_PUBLISHED, published_at__gte=lo, published_at__lt=hi):
        day, at = _local(issue.published_at)
        items.append(FeedItem(key=f'lab:weekly:{issue.issue_no}', title=f'연구실 위클리 No.{issue.issue_no}',
                              start_date=day, time=at, icon='fa-newspaper',
                              url=reverse('newsletter_detail', args=[issue.slug]), note=issue.title))

    for meeting in Meeting.objects.filter(held_at__gte=lo, held_at__lt=hi):
        day, at = _local(meeting.held_at)
        items.append(FeedItem(key=f'lab:meeting:{meeting.pk}', title='연구실 편집회의', start_date=day,
                              time=at, icon='fa-people-group', url=reverse('office:home')))
    return items
