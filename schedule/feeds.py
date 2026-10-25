"""사이트 기능을 달력에 얹는 통로.

호스트 사이트는 (start: date, end: date, user) -> Iterable[FeedItem] 함수를 만들고 그 점 경로를
settings.SCHEDULE['FEED_PROVIDERS'] 에 적는다. 이 모듈은 그 함수를 불러 쓰기만 하고, 사이트의 모델을
직접 import 하지 않는다. 함수 하나가 예외를 내도 달력은 그대로 뜬다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time

from django.utils.module_loading import import_string

from . import conf

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedItem:
    key: str                  # 전역에서 겹치지 않는 식별자 (예: 'lab:column:123') — ICS UID 로도 쓴다
    title: str
    start_date: date
    end_date: date | None = None
    time: time | None = None
    icon: str = ''            # Font Awesome 클래스 (예: 'fa-feather')
    url: str = ''
    note: str = ''            # 제목 옆 보조 설명 (예: '공개 예정')
    public: bool = True       # False 면 ICS 공개 구독에서 뺀다
    listed: bool = True       # False 면 달력 칸에만 그리고 '다가오는 일정' 요약에는 올리지 않는다(매주 반복 안내 등)


def collect(start: date, end: date, user) -> list[FeedItem]:
    items: list[FeedItem] = []
    for path in conf.get('FEED_PROVIDERS'):
        try:
            provider = import_string(path)
            items.extend(provider(start, end, user))
        except Exception:  # noqa: BLE001 — 사이트 기능 하나 때문에 달력이 죽으면 안 된다
            logger.exception('schedule feed provider failed: %s', path)
    return items
