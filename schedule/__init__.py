"""며칠 — 사이트에 붙여 쓰는 독립 일정·캘린더 모듈.

이 앱은 다른 앱(community, office, common)을 import 하지 않는다. 사이트 기능과의 연결은
settings.SCHEDULE 의 점 경로(FEED_PROVIDERS 등)로만 한다 — 설정을 비우면 단독으로 동작하고,
INSTALLED_APPS·urls 에서 빼면 사이트에 흔적 없이 떨어진다. 자세한 설정은 schedule/conf.py.
"""
