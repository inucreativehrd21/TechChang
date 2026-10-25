"""모듈 설정 — settings.SCHEDULE 딕셔너리로 기본값을 덮어쓴다.

    SCHEDULE = {
        # 달력 첫 요일 (0=월 … 6=일). 국내 달력 관례대로 일요일 시작이 기본.
        'FIRST_WEEKDAY': 6,
        # 사이트 기능을 달력에 얹는 함수들의 점 경로. 각 함수는 (start: date, end: date, user) 를 받아
        # schedule.feeds.FeedItem 들을 돌려준다. 하나가 실패해도 달력은 그대로 뜬다(로그만 남김).
        'FEED_PROVIDERS': ['office.calendar_feed.lab_schedule'],
        # 기상청 단기예보(apihub) — 비우면 날씨 표시가 통째로 꺼진다.
        'KMA_SERVICE_KEY': '',
        'KMA_REG_ID': '11B10101',      # 예보구역 (서울)
        'WEATHER_REGION': '서울',
        # ICS 구독 캘린더 이름
        'CALENDAR_NAME': '며칠',
    }
"""
from django.conf import settings

DEFAULTS = {
    'FIRST_WEEKDAY': 6,
    'FEED_PROVIDERS': [],
    'KMA_SERVICE_KEY': '',
    'KMA_REG_ID': '11B10101',
    'WEATHER_REGION': '서울',
    'CALENDAR_NAME': '며칠',
}


def get(key: str):
    return {**DEFAULTS, **getattr(settings, 'SCHEDULE', {})}[key]
