"""정식 판 전·후기 리그 — 반기 MVP와 가을야구(2026-10-25 사용자 결정, docs/rookie-full-remake-proposal.md).

- 반기 MVP: 전기(1~14일)·후기(15~28일) 마지막 날 경기가 끝나면 프로 리그마다 회원 선수 중 반기 1위
  (시즌 MVP 와 같은 rank_key, 후보 문턱 AWARD_PA·AWARD_IP 를 반기 경기 수로). RookieAward kind='half' —
  수상 축하·기록실에는 보이지만 명예의 전당 순서·진로 평가 셈에서는 뺀다(rookie_legacy·rookie_career).
- 가을야구: 정규시즌 마지막 날 경기가 끝나면 선수마다 개인 세계의 전기 우승 대 후기 우승
  (rookie_universe.half_finalists)을 경기 단위로 미리 만들어 career['post'] 에 저장하고, 쉬는 이틀(29·30일)
  시간대마다 한 경기씩 공개한다. 1군 리그는 7전 4선승제(한국시리즈·일본시리즈·월드시리즈·대만시리즈),
  하위 리그는 5전 3선승제 우승 결정전.
  · 경기마다 승률은 정규시즌 순위 차이(rookie_series._p_game) — 라이트처럼 결과를 먼저 정하지 않고 1차전부터 차례로 굴린다.
  · 내 기록은 Series.Me(정해진 승패에 맞는 경기를 기각 표본으로). 정규시즌이 끝날 때 출전 자격(최근 활동)이 있어야 나선다.
  · 기록은 포스트시즌 기록(career['post'])으로만 — 정규시즌 집계·시상·명예의 전당에는 들어가지 않는다.
  · 난수는 (선수, 시즌) 파생 난수 — 메인 난수 순서를 건드리지 않고, 다시 만들어도 같은 시리즈다.
- 스위치: 반기 MVP 는 ROOKIE_FULL_HALVES 를 따르고, 가을야구는 ROOKIE_FULL_POSTSEASON(기본 꺼짐)을 더 켜야 한다.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from . import rookie_clock as Clock
from . import rookie_league as L
from . import rookie_world as W

logger = logging.getLogger(__name__)

HALF_KIND = 'half'
TOP_FORMAT, MINOR_FORMAT = (7, 4), (5, 3)          # (최대 경기, 필요한 승수)
# 경기 시각 — (정규시즌 마지막 날에서 며칠 뒤, 시간대). 29일 15:30~22:00, 30일 18:00~22:00, 마지막 경기는 22시.
POST_SLOTS = {7: ((1, 2), (1, 3), (1, 4), (1, 5), (2, 3), (2, 4), (2, 5)),
              5: ((1, 3), (1, 4), (1, 5), (2, 4), (2, 5))}
SHOW_AFTER = 3                                      # 다음 시즌 개막 뒤 며칠까지 지난 가을야구를 보여 주나


def post_enabled(season: int) -> bool:
    return Clock._flag('ROOKIE_FULL_POSTSEASON', 'false').lower() in ('true', '1') and Clock.split_season(season)


def half_range(s, half: int) -> tuple[date, date]:
    start = s.start + timedelta(days=(half - 1) * Clock.HALF_DAYS)
    return start, start + timedelta(days=Clock.HALF_DAYS - 1)


# ───────────────────────────── 반기 MVP
def close_half(s, day: date) -> list:
    """그날이 반기 마지막 날이면 리그마다 반기 MVP. 이미 준 리그는 건너뛴다. 준 상 목록."""
    from .models import RookieAward, RookieSeasonStat
    from . import rookie as R
    if not Clock.split_season(s.number):
        return []
    i = (day - s.start).days
    if i not in (Clock.HALF_DAYS - 1, L.SEASON_DAYS - 1):
        return []
    half = 1 if i < Clock.HALF_DAYS else 2
    a, b = half_range(s, half)
    label = f'{Clock.HALF_LABEL[half]} MVP'
    out = []
    with transaction.atomic():
        done = set(RookieAward.objects.filter(season=s, kind=HALF_KIND, label=label).values_list('league', flat=True))
        codes = set(RookieSeasonStat.objects.filter(season=s).values_list('league', flat=True))
        for code in sorted((c for c in codes if W.is_pro(c) and c not in done), key=lambda c: -W.level(c)):
            m = half_mvp(s, code, a, b)
            if m is None:
                continue
            r = m.stat
            out.append(RookieAward.objects.create(
                season=s, user=r.user, player=r.player, stat=r, league=code, kind=HALF_KIND, label=label,
                position=r.position, name=r.name, team=r.team, role=r.role, value=L.award_val(m), order=60 + half))
    for award in out:
        if award.player_id:
            R._log(award.player, 'award', f'시즌 {s.number} {W.short(award.league)} {award.label} 수상 — {award.value}')
    return out


def half_mvp(s, code: str, a: date, b: date):
    """반기 [a, b] 경기 기록으로 그 리그 회원 선수 중 1위 — 후보가 없으면 None."""
    from .models import RookieGame
    rows = [r for r in L.stat_rows(s, code, 'batter') + L.stat_rows(s, code, 'pitcher') if r.player_id]
    if not rows:
        return None
    totals = {}
    for pid, line in RookieGame.objects.filter(season=s, league=code, day__gte=a, day__lte=b,
                                               player_id__in=[r.player_id for r in rows]).values_list('player_id', 'line'):
        totals[pid] = L.add(totals.get(pid, {}), line or {})
    games = L.season_games(code) // 2
    cands = []
    for r in rows:
        t = totals.get(r.player_id)
        if t and L.qualified(r.role, t, games, L.AWARD_PA if r.role == 'batter' else L.AWARD_IP):
            cands.append(SimpleNamespace(stat=r, role=r.role, totals=t, war=L.war(r.role, r.position, t)))
    return max(cands, key=L.rank_key) if cands else None


# ───────────────────────────── 가을야구
def _team(league: str, code: str) -> dict:
    return {'code': code, 'name': W.club_label(league, code), 'short': W.club_short(league, code),
            'color': (W.PRO_TEAM.get(code) or {}).get('color', '')}


def _me(p):
    from . import rookie_career as C
    from . import rookie_series as Series
    return Series.Me(p.role, C.game_stats(p), p.position or 'DH', (p.lineup or '', p.slot or 0), W.level(p.league))


def series_seq(us: dict, them: dict, cap: int, need: int, r) -> list:
    """1차전부터 차례로 — 경기마다 정규시즌 순위 차이 승률(us 쪽이 이기면 1). 누가 need 승에 닿으면 끝."""
    from . import rookie_series as Series
    return Series._series_seq(Series._p_game(us['rank'], them['rank']), need, cap, (0, 0), r)


def build_post(p, s) -> dict | None:
    """그 선수 개인 세계의 가을야구 — 전·후기로 치른 세계가 아니거나 1군·하위 프로 리그가 아니면 None."""
    from . import rookie_series as Series
    from . import rookie_universe as U
    league = p.league
    if not W.is_pro(league):
        return None
    U.advance(p, s.number, league, L.SEASON_GAMES, None, split=True)   # 쉬어서 덜 치른 세계도 정규시즌 끝까지
    halves = U.half_tables(p)
    whole = U.table(p, s.number, league, L.SEASON_GAMES)
    pair = U.half_finalists(halves, whole)
    if not pair:
        return None
    first, second = pair
    cap, need = TOP_FORMAT if league in U.FINAL_NAME else MINOR_FORMAT
    name = halves['final']
    r = random.Random(f'full-post:{p.pk}:{s.number}:{league}')
    mine = p.club in (first['club'], second['club'])
    us, them = (first, second) if not mine or first['club'] == p.club else (second, first)
    us_higher = us['rank'] < them['rank']
    seq = series_seq(us, them, cap, need, r)
    me = _me(p) if mine and L.was_active(p, s.end) else None
    games = [Series.game(i, bool(x), Series._home(i, us_higher, cap), me, r) for i, x in enumerate(seq)]
    wins = Series._wins(seq, (0, 0))
    won = wins[0] >= need
    rnd = {'code': 'final', 'name': name, 'format': f'{cap}전 {need}선승제', 'need': need, 'cap': cap,
           'us_higher': us_higher, 'head': [0, 0], 'opponent': _team(league, them['club']), 'wins': wins,
           'result': 'won' if won else 'lost', 'games': games}
    champ = us if won else them
    times = [Clock.slot_at(s.end + timedelta(days=d), slot) for d, slot in POST_SLOTS[cap][:len(seq)]]
    return {'season': s.number, 'league': league, 'final': name, 'mine': mine,
            'team': _team(league, us['club']), 'champion': _team(league, champ['club']),
            'seeds': {'first': first['club'], 'second': second['club']},
            'doc': {'kind': 'post', 'key': league, 'title': f'{W.short(league)} {name}', 'rounds': [rnd],
                    'team': _team(league, us['club']), 'result': ('우승' if won else '준우승') if mine else ''},
            'at': [t.isoformat() for t in times],
            'labels': [f"{(s.end + timedelta(days=d)).day}일 {Clock.label(slot)}" for d, slot in POST_SLOTS[cap][:len(seq)]]}


def prepare_post(s) -> int:
    """정규시즌 마지막 경기 뒤 — 현역 프로 선수마다 가을야구를 만들어 둔다. 이미 만든 선수는 건너뛴다. 만든 수."""
    from .models import RookiePlayer
    if not post_enabled(s.number):
        return 0
    n = 0
    rows = RookiePlayer.objects.filter(retired_at__isnull=True, created_at__lt=L.day_end(s.end)) \
        .order_by('pk').values_list('pk', 'league')
    for pk, league in rows:
        if not W.is_pro(league):
            continue
        try:
            with transaction.atomic():
                p = RookiePlayer.objects.select_for_update().filter(pk=pk, retired_at__isnull=True).first()
                if p is None or ((p.career or {}).get('post') or {}).get('season') == s.number:
                    continue
                post = build_post(p, s)        # 개인 세계를 끝까지 채우므로(career) 만들지 못해도 저장한다
                p.career = dict(p.career or {}, post=post) if post else dict(p.career or {})
                p.save(update_fields=['career'])
                n += bool(post)
        except Exception:  # noqa: BLE001 — 한 선수의 오류가 다른 선수의 가을야구를 막지 않게
            logger.exception('야구선수 키우기 가을야구 준비 실패: player=%s season=%s', pk, s.number)
    return n


def post_view(p, now: datetime | None = None) -> dict | None:
    """경기장 칸의 가을야구 — 시각이 지난 경기까지만 보여 준다. 보여 줄 때가 아니면 None."""
    post = (p.career or {}).get('post')
    if not post or not post_enabled(post['season']):
        return None
    now = now or timezone.now()
    season = L.season_no(timezone.localdate(now))
    if season != post['season'] and not (season == post['season'] + 1 and
                                         (timezone.localdate(now) - L.season_bounds(season)[0]).days < SHOW_AFTER):
        return None
    times = [datetime.fromisoformat(t) for t in post['at']]
    shown = sum(1 for t in times if t <= now)
    rnd = dict(post['doc']['rounds'][0])
    games = rnd['games'][:shown]
    wins = [sum(1 for g in games if g['won']), sum(1 for g in games if not g['won'])]
    done = shown >= len(times)
    rnd.update(games=games, wins=wins, result=rnd['result'] if done else 'pending')
    doc = dict(post['doc'], rounds=[rnd], result=post['doc']['result'] if done else '')
    nxt = None if done else {'label': post['labels'][shown], 'at': times[shown], 'no': shown + 1}
    them = rnd['opponent']['short']
    us = post['team']['short']
    if not shown:
        line = f"{post['final']} 1차전 {post['labels'][0]} — {us} 대 {them}"
    elif done:
        line = f"{post['champion']['short']} {post['final']} 우승 ({max(wins)}승 {min(wins)}패)"
    else:
        line = f"{post['final']} {shown}차전까지 {us} {wins[0]} : {wins[1]} {them}"
    return {'season': post['season'], 'final': post['final'], 'mine': post['mine'], 'doc': doc, 'done': done,
            'next': nxt, 'line': line, 'shown': shown, 'champion': post['champion'] if done else None,
            'refresh_at': int(nxt['at'].timestamp() * 1000) + 60_000 if nxt else None}
