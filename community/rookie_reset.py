"""시즌 개막 전 새 출발 선택(2026-11-16 사용자 요청) — 휴식기마다 '이 선수로 계속 / 새 선수로 처음부터'를 한 번 묻는다.

- 기간: 지난 시즌 폐막 다음 날 0시부터 새 시즌 첫 시간대(개막일 11:00) 전까지. 시즌 1 개막 전에는 묻지 않는다.
- 대상: 기간이 시작되기 전에 입단한 현역 선수. 시즌마다 한 번만 고르고(career['season_choice']), 고르지 않으면 그대로 계속한다.
- 새 출발 = 은퇴 처리(rookie_career.retire_player) — 선수 페이지·기록·수상·은퇴 카드는 남고, 회원은 리틀야구부터 새 선수를 만든다.
  이렇게 은퇴한 선수는 career['season_reset'] 에 시즌 번호를 남겨, 새 선수가 잠재력·숨은 특성을 이어받지 않고 새로 뽑는다
  (rookie.inherits_from). 기회가 시즌마다 한 번뿐이라 '좋은 자질만 골라 뽑기'로 되풀이할 수 없다.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from . import rookie_clock as Clock
from . import rookie_league as L

KEEP, RESET = 'keep', 'reset'
REASON = '시즌 {n} 개막 전 새 출발'


class ResetError(Exception):
    pass


def window(now=None) -> dict | None:
    """지금이 선택 기간이면 {'season','opens','deadline'} — 아니면 None."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    if L.in_season(today):
        n = L.season_no(today)
        start = L.season_bounds(n)[0]
        if today != start:
            return None
    else:
        n = L.season_no(today) + 1
        start = L.season_bounds(n)[0]
    if n < 2:
        return None
    deadline = Clock.slot_at(start, 0)                    # 개막일 첫 시간대(11:00) — 시간대 진행이 아니어도 같은 마감
    opens = timezone.make_aware(datetime.combine(L.season_bounds(n - 1)[1] + timedelta(days=1), time.min))
    if not (opens <= now < deadline):
        return None
    return {'season': n, 'opens': opens, 'deadline': deadline}


def chosen(p, season: int) -> str:
    return ((p.career or {}).get('season_choice') or {}).get(str(season), '')


def offer(p, now=None) -> dict | None:
    """그 선수에게 선택 칸을 보여 줄지 — 보여 주면 화면 값."""
    if p is None or p.retired_at:
        return None
    w = window(now)
    if not w or chosen(p, w['season']) or (p.created_at and p.created_at >= w['opens']):
        return None
    return dict(w, name=p.name)


def keep(user, now=None) -> dict:
    from . import rookie as R
    w = window(now)
    if not w:
        raise ResetError('지금은 새 시즌 개막 전 선택 기간이 아니에요.')
    with transaction.atomic():
        p = R.locked(user)
        if p is None:
            raise ResetError('현역 선수가 없어요.')
        _mark(p, w['season'], KEEP)
        p.save(update_fields=['career'])
    return {'season': w['season'], 'name': p.name}


def reset(user, now=None) -> dict:
    """새 출발 — 지금 선수를 은퇴시키고 새 선수가 자질을 새로 뽑도록 표시한다."""
    from . import rookie as R
    from . import rookie_career as C
    w = window(now)
    if not w:
        raise ResetError('지금은 새 시즌 개막 전 선택 기간이 아니에요.')
    with transaction.atomic():
        p = R.locked(user)
        if p is None:
            raise ResetError('현역 선수가 없어요.')
        if chosen(p, w['season']):
            raise ResetError('이번 시즌 선택은 이미 했어요.')
        _mark(p, w['season'], RESET)
        p.career['season_reset'] = w['season']
        C.retire_player(p, REASON.format(n=w['season']))      # career 를 이어받아 함께 저장한다
    return {'season': w['season'], 'name': p.name, 'pk': p.pk}


def _mark(p, season: int, choice: str) -> None:
    career = dict(p.career or {})
    picks = dict(career.get('season_choice') or {})
    picks[str(season)] = choice
    career['season_choice'] = picks
    p.career = career
