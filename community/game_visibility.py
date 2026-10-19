"""게임 기록 숨김 — 운영자(admin) 계정의 게임 기록은 홈페이지 어디에도 보이지 않게 한다(2026-10-16 운영자 요청).

리더보드(숫자야구·2048·지뢰찾기), 홈·게임센터의 '지금까지 N판' 집계에서 뺀다.
운영자가 테스트로 친 판이 순위와 통계를 흐리지 않게 하려는 것 — 기록 자체는 지우지 않는다.
틱택토·끝말잇기는 URL 이 꺼져 있다 — 다시 켜면 방 목록에 visible_for 를 씌울 것
(운영자 본인 화면에서는 자기 방이 보여야 하니까).

숨길 계정은 settings.GAME_HIDDEN_USERNAMES 로 바꿀 수 있다(기본: admin).

야구선수 키우기(정식·라이트)는 숨기지 않는다(2026-10-19 운영자 요청: '나도 좀 즐기게') — 운영자 선수도 순위·명예의 전당·
오늘의 랭킹·시상·베스트 9·선수/카드 페이지·홈 집계에 그대로 오른다. 야구 코드는 rookie_visible·rookie_hidden 만 쓰고,
다시 숨기려면 ROOKIE_HIDES_ADMIN = True 하나만 바꾸면 된다.
"""
from __future__ import annotations

from django.conf import settings

DEFAULT_HIDDEN = ('admin',)


def hidden_usernames() -> tuple:
    return tuple(getattr(settings, 'GAME_HIDDEN_USERNAMES', None) or DEFAULT_HIDDEN)


def is_hidden(user) -> bool:
    return bool(getattr(user, 'is_authenticated', False) and user.username in hidden_usernames())


def visible(qs, *fields: str):
    """fields(기본 'player') 중 하나라도 숨김 계정이면 뺀다. M2M(participants)도 된다."""
    names = hidden_usernames()
    for f in fields or ('player',):
        qs = qs.exclude(**{f'{f}__username__in': names})
    return qs


ROOKIE_HIDES_ADMIN = False


def rookie_visible(qs, *fields: str):
    """야구선수 키우기용 visible — 지금은 운영자도 보인다(ROOKIE_HIDES_ADMIN)."""
    return visible(qs, *fields) if ROOKIE_HIDES_ADMIN else qs


def rookie_hidden(user) -> bool:
    """야구선수 키우기용 is_hidden — 운영자 선수 페이지·카드도 남이 볼 수 있다."""
    return ROOKIE_HIDES_ADMIN and is_hidden(user)


def visible_for(request, qs, *fields: str):
    """방 목록용 — 숨김 계정 본인이 보는 화면에서는 거르지 않는다."""
    return qs if is_hidden(getattr(request, 'user', None)) else visible(qs, *fields)
