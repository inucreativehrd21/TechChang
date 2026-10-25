"""화면이 쓰는 데이터 모으기 — 회원 일정 + 사이트 피드 + 날씨."""
from __future__ import annotations

from datetime import date

from django.db.models import Q

from . import feeds
from .layout import Item
from .models import Event, WeatherSnapshot


def event_items(user, start: date, end: date) -> list[Item]:
    visible = Q(visibility=Event.COMMUNITY)
    if user.is_authenticated:
        visible |= Q(visibility=Event.PRIVATE, owner=user)
    qs = Event.objects.filter(visible, start_date__lte=end, end_date__gte=start)
    return [
        Item(key=f'event:{e.pk}', title=e.title, start_date=e.start_date, end_date=e.end_date,
             kind='community' if e.is_community else 'mine', start_time=e.start_time,
             end_time=e.end_time, url=e.get_absolute_url(), location=e.location,
             public=e.is_community)
        for e in qs
    ]


def feed_items(user, start: date, end: date) -> list[Item]:
    return [
        Item(key=f.key, title=f.title, start_date=f.start_date, end_date=f.end_date or f.start_date,
             kind='lab', start_time=f.time, icon=f.icon, url=f.url, note=f.note, public=f.public,
             listed=f.listed)
        for f in feeds.collect(start, end, user)
        if start <= f.start_date <= end or start <= (f.end_date or f.start_date) <= end
    ]


def calendar_items(user, start: date, end: date) -> list[Item]:
    return event_items(user, start, end) + feed_items(user, start, end)


def latest_weather() -> tuple[dict, WeatherSnapshot | None]:
    snap = WeatherSnapshot.objects.order_by('-fetched_at').first()
    return (snap.days if snap else {}), snap
