"""정식 판 리그 시계 — 하루 경기를 시간대마다 하나씩 치른다(2026-10-25 사용자 결정 A안, docs/rookie-full-remake-proposal.md).

- 라운드 = 한 리그의 모든 구단이 한 경기씩 치르는 판(rookie_universe.schedule, 홀수 팀 리그면 한 팀은 쉰다).
  라운드를 시즌 28일에 고르게 나누고(i·R/28 — rookie_league.games_on 과 같은 식), 그날 몫은 그날 시간대의
  뒤쪽부터 채운다 → 하루 마지막 경기는 언제나 22:00(학생 18:00). 같은 리그는 같은 시각에 같은 라운드를 치르므로
  구단마다 순위표 진행이 어긋나지 않고, 회원 맞대결도 대진 그대로 만난다.
- 짝수 팀 프로 리그는 144라운드 = 하루 5~6경기로 지금과 같다. 퓨처스(상무 포함 11팀)는 160라운드라 그날 판 중
  한 판은 쉬고, 리틀(17팀)·중학(41팀)은 28경기가 35·42라운드에 걸쳐 어떤 날은 두 경기(15:30·18:00), 어떤 날은 쉰다.
  예전 방식은 '오늘 몇 번째 경기'를 날짜로만 정해 이 리그들에서 구단마다 다른 라운드를 치렀다.
- 모든 리그가 28일 마지막 시간대에 정규시즌을 마친다 → 쉬는 이틀(OFF_DAYS)은 가을야구 자리로 비어 있다.
- 스위치 ROOKIE_FULL_SLOTS(기본 꺼짐). 시즌 도중에 진행 방식이 바뀌지 않게 ROOKIE_SLOTS_FROM_SEASON(기본 2) 시즌부터만.
- 전·후기 리그(2026-10-25 사용자 결정, KBO 원년 방식): 1~14일 전기, 15~28일 후기. 스위치 ROOKIE_FULL_HALVES(기본 꺼짐),
  시작 시즌은 시간대 진행과 같다. 켜면 대진을 반기마다 따로 짜서(rookie_universe.schedule split) 모든 리그가
  14일 마지막 시간대에 전기를, 28일 마지막 시간대에 후기를 마치고 반기마다 모든 구단이 같은 경기 수를 치른다.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from django.conf import settings
from django.utils import timezone

from . import rookie_league as L
from . import rookie_universe as U
from . import rookie_world as W

SLOTS = (time(11, 0), time(13, 0), time(15, 30), time(18, 0), time(20, 0), time(22, 0))
PRO_SLOTS = (0, 1, 2, 3, 4, 5)
SCHOOL_SLOTS = (2, 3)                 # 학생은 방과 후 — 보통 18:00 한 경기, 두 라운드인 날은 15:30 도
NIGHT_FROM = 3                        # 18:00 부터 야간 경기(경기 환경 이식 때 낮·밤 구분)
HALF_DAYS = L.SEASON_DAYS // 2        # 전기리그 14일 · 후기리그 14일
HALF_LABEL = {1: '전기리그', 2: '후기리그'}


def _flag(name: str, default: str) -> str:
    return str(getattr(settings, name, os.environ.get(name, default)))


def enabled() -> bool:
    return _flag('ROOKIE_FULL_SLOTS', 'false').lower() in ('true', '1')


def from_season() -> int:
    try:
        return max(1, int(_flag('ROOKIE_SLOTS_FROM_SEASON', '2')))
    except ValueError:
        return 2


def active(season: int) -> bool:
    """그 시즌을 시간대별로 치르나 — 스위치를 켠 뒤에도 시작 시즌 전이면 예전처럼 하루에 몰아서."""
    return enabled() and season >= from_season()


def active_on(day: date) -> bool:
    return active(L.season_no(day))


def split_season(season: int) -> bool:
    """그 시즌을 전·후기 리그로 치르나 — 시즌 도중에 대진이 바뀌지 않게 시작 시즌부터만."""
    return _flag('ROOKIE_FULL_HALVES', 'false').lower() in ('true', '1') and season >= from_season()


def split_on(day: date) -> bool:
    return split_season(L.season_no(day))


def half_of(day: date) -> int | None:
    """정규시즌 그날이 전기(1)·후기(2) 중 어디인지 — 전·후기로 치르지 않거나 시즌 밖이면 None."""
    i = day_index(day)
    if i is None or not split_on(day):
        return None
    return 1 if i < HALF_DAYS else 2


def label(slot: int) -> str:
    return SLOTS[slot].strftime('%H:%M')


def slot_at(day: date, slot: int) -> datetime:
    return timezone.make_aware(datetime.combine(day, SLOTS[slot]))


def is_night(slot: int) -> bool:
    return slot >= NIGHT_FROM


# ───────────────────────────── 라운드 배치
@lru_cache(maxsize=64)
def rounds_total(league: str, split: bool = False) -> int:
    """그 리그 한 시즌의 라운드 수. 대진을 못 짜는 리그(구단 하나 이하)는 경기 수 그대로.
    전·후기 리그는 반기 라운드 수가 같아 i·R/28 배치에서 14일 마지막 시간대가 꼭 전기 마지막 라운드다."""
    _clubs, rounds = U.schedule(league, L.season_games(league), split)
    return len(rounds) or L.season_games(league)


def _pool(league: str) -> tuple:
    return PRO_SLOTS if W.is_pro(league) else SCHOOL_SLOTS


def day_index(day: date) -> int | None:
    if not L.in_season(day):
        return None
    return (day - L.season_bounds(L.season_no(day))[0]).days


@lru_cache(maxsize=4096)
def _day_plan(league: str, i: int, split: bool = False) -> tuple:
    """시즌 i번째 날의 (시간대, 라운드) 들 — 뒤쪽 시간대부터 채운다."""
    total = rounds_total(league, split)
    rounds = list(range(i * total // L.SEASON_DAYS, (i + 1) * total // L.SEASON_DAYS))
    pool = _pool(league)
    if len(rounds) > len(pool):
        raise ValueError(f'{league}: 하루 {len(rounds)}라운드는 시간대 {len(pool)}개에 들어가지 않아요.')
    return tuple(zip(pool[len(pool) - len(rounds):], rounds))


def day_plan(league: str, day: date) -> tuple:
    i = day_index(day)
    return () if i is None else _day_plan(league, i, split_on(day))


def round_at(league: str, day: date, slot: int) -> int | None:
    return next((r for s, r in day_plan(league, day) if s == slot), None)


@lru_cache(maxsize=1024)
def _club_rounds(league: str, club: str, split: bool = False) -> dict:
    """구단의 {라운드: (시즌 경기 번호, 대진)}. 대진표에 없는 구단이면 빈 dict."""
    return {f['day']: (i + 1, f) for i, f in enumerate(U.club_fixtures(league, L.season_games(league), club, split))}


def club_game(league: str, club: str, day: date, slot: int):
    """그 시각 내 구단 경기 (번호, 대진) — 쉬는 판이면 None. 대진표에 없는 구단은 라운드 번호를 경기 번호로 쓴다."""
    r = round_at(league, day, slot)
    if r is None:
        return None
    own = _club_rounds(league, club, split_on(day))
    if own:
        return own.get(r)
    no = r + 1
    return (no, None) if no <= L.season_games(league) else None


def club_games_on(league: str, club: str, day: date) -> list:
    """그날 내 구단 경기 [(시간대, 번호, 대진)] — 시각 순."""
    out = []
    for slot, _r in day_plan(league, day):
        g = club_game(league, club, day, slot)
        if g:
            out.append((slot, g[0], g[1]))
    return out


def next_game(league: str, club: str, now: datetime | None = None, horizon: int = 4):
    """지금 뒤 첫 경기 — {'day','slot','at','no','fixture'} 또는 None(시즌 밖·며칠 안에 경기 없음)."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    for k in range(horizon):
        day = today + timedelta(days=k)
        if not active_on(day):
            continue
        for slot, no, fixture in club_games_on(league, club, day):
            at = slot_at(day, slot)
            if at > now:
                return {'day': day, 'slot': slot, 'at': at, 'no': no, 'fixture': fixture, 'label': label(slot)}
    return None


def last_due(day: date, now: datetime) -> int | None:
    """그날 시각이 지난 마지막 시간대(없으면 None)."""
    due = [i for i in range(len(SLOTS)) if slot_at(day, i) <= now]
    return due[-1] if due else None


def start_no(pk: int, league: str, club: str, day: date) -> int | None:
    """그날 선발 투수가 나서는 구단 경기 번호 — 프로는 그날 경기 중 하나, 학생은 구단 경기 하나 걸러(번호 홀짝)."""
    nos = [n for _s, n, _f in club_games_on(league, club, day)]
    if not nos:
        return None
    if W.is_pro(league):
        return nos[pk % len(nos)]
    return next((n for n in nos if n % 2 == pk % 2), None)
