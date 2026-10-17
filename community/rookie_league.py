"""야구선수 키우기 — 리그(시즌·경기·기록·시상). 성장 규칙은 rookie.py.

시즌: 2026-10-19(월) 개막, 4주(28일)에 144경기 — 하루 5~6경기, KBO 한 시즌 분량.
매일 밤 rookie_daily 가 전날 경기를 시뮬레이션하고(advance), 시즌 마지막 날 다음 정산에서 시상한다(close_season).
- 출전: 경기일 포함 최근 3일 안에 활동(TP 획득)이 있어야 엔트리에 든다. 쉬면 결장 → 규정타석·이닝을 못 채운다.
- 리그는 소속 그대로(rookie_world.LEAGUES): 리틀·중학·고교·대학 / KBO 육성군·퓨처스·1군 / MLB 싱글A~메이저 /
  NPB 2군·1군 / CPBL. 기록은 리그별로 따로 쌓는다. 상대는 같은 리그 구단(학교)에서 고른다.
- 프로: 타자는 그날 모든 경기(5~6경기)에, 투수는 선발 로테이션으로 하루 한 경기에 나간다(시즌 ≈ 28선발 170이닝).
  학생(아마추어): 하루 한 경기, 선발 투수는 이틀에 한 번.
- 시상: 각 나라 최상위 리그는 MVP·신인왕·포지션별 수상(골든글러브·실버슬러거·베스트 나인·베스트 텐)·타이틀
  (MLB 사이영상, NPB 사와무라상), 하위 리그는 리그 MVP, 아마추어는 최우수선수·타격상·홈런상·우수투수상.

경기 모형(타석 승부·상대 선수·내 타순과 보직·경기 시뮬레이션)은 community/rookie_sim.py.
같은 수준끼리면 리그 평균 ≈ .265/.325/.435, 평균자책점 ≈ 4 — test_rookie_league 가 몬테카를로로 지킨다.
투수 보직: 선발(하루 한 경기) · 구원(그날 경기 중 보직별 확률로 하루 두 번까지) — 세이브·홀드·블론세이브.

WAR(추정, 실제 KBO 공식이 아니라 같은 뼈대의 근사):
- 타자 = (wRAA + 대체 수준 20점/600타석 + 포지션 보정 + 수비 + 주루) / 10, wOBA 가중치는 흔히 쓰는 근사값.
- 투수 = (대체 수준 FIP − FIP) × 이닝/9 / 10.
"""
from __future__ import annotations

import logging
import math
import random
from collections import Counter
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from . import rookie_world as W

logger = logging.getLogger(__name__)

EPOCH = date(2026, 10, 19)
SEASON_DAYS, SEASON_GAMES = 28, 144
OFF_DAYS = 2                    # 시즌 사이 쉬는 날 — 시상식·(앞으로) 포스트시즌 자리. 날짜가 흔들리지 않게 개막 전에 정했다
CYCLE = SEASON_DAYS + OFF_DAYS
MIN_STAY = 2                    # 타순·보직은 한 자리에서 최소 이틀(경기일 기준)을 보내야 다음 계단으로
ACTIVE_DAYS = 3                                    # 경기일 포함 최근 3일 안에 활동해야 출전
QUAL_PA, QUAL_IP = 3.1, 1.0                        # 규정타석·규정이닝(팀 경기 수 × 배수, KBO 와 같다)
AWARD_PA, AWARD_IP = 2.0, 0.6                      # MVP·골든글러브 후보 최소(팀 경기 수 × 배수)
AM_AWARD_PA, AM_AWARD_OUTS = 20, 30                # 아마추어 최우수선수 후보 최소(학년이 바뀌면 리그를 옮기므로 낮게)

PITCHER_POS = 'SP'
POSITIONS = [('C', '포수'), ('1B', '1루수'), ('2B', '2루수'), ('3B', '3루수'), ('SS', '유격수'),
             ('OF', '외야수'), ('DH', '지명타자')]
POS_LABEL = dict(POSITIONS, SP='투수')
POS_ADJ = {'C': 12.0, 'SS': 7.0, '2B': 3.0, '3B': 2.0, 'OF': -2.0, '1B': -10.0, 'DH': -15.0}   # 144경기 기준 점수
ERR_BASE = {'C': .03, '1B': .03, '2B': .05, '3B': .07, 'SS': .08, 'OF': .03}

META_KEYS = ('vs', 'vs_lvl', 'bslot', 'lead', 'inn', 'club', 'xp')        # 경기 줄 설명 값 — 시즌 누적에서 뺀다

BAT_KEYS = ('g', 'pa', 'ab', 'h', 'd', 't', 'hr', 'rbi', 'r', 'bb', 'hbp', 'so', 'sb', 'cs', 'e', 'def',
            'ph', 'pr', 'dr')                                                  # 대타·대주자·대수비 출장
PIT_KEYS = ('g', 'gs', 'gr', 'w', 'l', 'sv', 'hld', 'bs', 'qs', 'cg', 'sho', 'outs', 'h', 'r', 'er', 'bb', 'hbp',
            'so', 'hr', 'bf', 'np')
LG_WOBA, WOBA_SCALE, FIP_C, REPL_FIP = 0.327, 1.20, 2.94, 5.10   # 몬테카를로로 맞춘 리그 평균


# ───────────────────────────── 시즌 달력
def season_no(day: date) -> int:
    """day 가 속한 시즌 번호(그 시즌 뒤 쉬는 날 포함). 개막 전이면 0."""
    return (day - EPOCH).days // CYCLE + 1 if day >= EPOCH else 0


def season_bounds(n: int) -> tuple[date, date]:
    """(개막일, 정규시즌 마지막 날). 그 뒤 OFF_DAYS 는 쉬는 날."""
    start = EPOCH + timedelta(days=(n - 1) * CYCLE)
    return start, start + timedelta(days=SEASON_DAYS - 1)


def in_season(day: date) -> bool:
    n = season_no(day)
    return bool(n) and (day - season_bounds(n)[0]).days < SEASON_DAYS


def games_through(day: date) -> int:
    """그 시즌에서 day 까지(포함) 치른 팀 경기 수."""
    n = season_no(day)
    if not n:
        return 0
    i = min((day - season_bounds(n)[0]).days, SEASON_DAYS - 1)     # 쉬는 날이면 전 경기
    return (i + 1) * SEASON_GAMES // SEASON_DAYS


def games_on(day: date) -> range:
    """day 에 치르는 시즌 경기 번호들(1부터)."""
    if not in_season(day):
        return range(0)
    i = (day - season_bounds(season_no(day))[0]).days
    return range(i * SEASON_GAMES // SEASON_DAYS + 1, (i + 1) * SEASON_GAMES // SEASON_DAYS + 1)


def league_games_on(day: date, code: str) -> range:
    """그 리그가 day 에 치르는 경기 번호 — 프로는 하루 5~6경기, 학생은 하루 한 경기(번호 = 시즌 몇째 날)."""
    if W.is_pro(code):
        return games_on(day)
    if not in_season(day):
        return range(0)
    i = (day - season_bounds(season_no(day))[0]).days
    return range(i + 1, i + 2)


def get_season(n: int):
    from .models import RookieSeason
    start, end = season_bounds(n)
    return RookieSeason.objects.get_or_create(number=n, defaults={'start': start, 'end': end})[0]


def season_state(today: date | None = None) -> dict:
    """화면 머리말용 — 개막 전이면 D-day, 시즌 중이면 몇 경기째."""
    today = today or timezone.localdate()
    if today < EPOCH:
        return {'phase': 'pre', 'number': 1, 'dday': (EPOCH - today).days, 'opening': EPOCH}
    n = season_no(today)
    start, end = season_bounds(n)
    if today > end:                                            # 시즌 사이 쉬는 날
        opening = season_bounds(n + 1)[0]
        return {'phase': 'off', 'number': n, 'next': n + 1, 'opening': opening, 'dday': (opening - today).days,
                'played': SEASON_GAMES, 'total': SEASON_GAMES, 'pct': 100.0, 'end': end}
    played = games_through(today - timedelta(days=1)) if today > start else 0
    return {'phase': 'season', 'number': n, 'start': start, 'end': end, 'played': played,
            'total': SEASON_GAMES, 'pct': round(played / SEASON_GAMES * 100, 1), 'left_days': (end - today).days + 1}


# ───────────────────────────── 경기 모형(rookie_sim)
from .rookie_sim import (BAT_ROLES, BAT_SPLITS, GRADE_LABEL, GROUP_NOTE, LINEUP_FORMS, PIT_ROLES,  # noqa: E402,F401
                         PIT_SPLITS, RELIEF, RELIEF_PER_DAY, STARTER_GRADES, STARTER_PA, batter_game, batter_role,
                         opp_summary, pa_probs, pitcher_role, relief_game, starter_game)

pitcher_game = starter_game                      # 예전 이름(선발 등판)


def opp_levels(league: str) -> dict:
    """리그별 상대 수준 — 상대 선발 등급별 구위와 상대 타선 구간별 대표 능력(화면 안내용)."""
    return opp_summary(W.level(league))


# ───────────────────────────── 표기
def ip_text(outs: int) -> str:
    whole, part = divmod(int(outs), 3)
    return f"{whole}{'⅓⅔'[part - 1] if part else ''}"


def rate(x: float, digits: int = 3) -> str:
    """타율식 표기 — .312, 1.000."""
    s = f'{x:.{digits}f}'
    return s[1:] if s.startswith('0.') else s


def bat_summary(t) -> str:
    h = t.get('h', 0)
    bits = [f"{t.get('ab', 0)}타수 {f'{h}안타' if h else '무안타'}"]
    if t.get('hr'):
        bits.append(f"{t['hr']}홈런")
    if t.get('rbi'):
        bits.append(f"{t['rbi']}타점")
    if t.get('bb'):
        bits.append(f"{t['bb']}볼넷")
    if t.get('sb'):
        bits.append(f"{t['sb']}도루")
    return ' '.join(bits)


def pit_summary(t) -> str:
    dec = '승' if t.get('w') else '패' if t.get('l') else ''
    return (f"{ip_text(t.get('outs', 0))}이닝 {t.get('h', 0)}피안타 {t.get('r', 0)}실점 {t.get('so', 0)}탈삼진"
            + (f' ({dec})' if dec else ''))


# ───────────────────────────── 누적·지표
def add(totals: dict, line: dict) -> dict:
    out = dict(totals)
    for k, v in line.items():
        if k in META_KEYS or not isinstance(v, (int, float)):
            continue
        out[k] = round(out.get(k, 0) + v, 4) if isinstance(v, float) else out.get(k, 0) + v
    return out


def splits(role: str, t: dict, league: str | None = None) -> list:
    """상대별 성적 — 타자는 상대 선발 등급·불펜 종류, 투수는 상대 타선 구간(상위·중심·하위). 투수의 타율은 피안타율."""
    from .rookie_sim import OPP_PITCHERS
    summary = opp_levels(league) if league is not None else {}
    rows = []
    for code, label in (PIT_SPLITS if role == 'pitcher' else BAT_SPLITS):
        g = {k: t.get(f'{code}_{k}', 0) for k in ('pa', 'ab', 'h', 'hr', 'bb', 'so')}
        if league is None:
            level = None
        elif code in summary:
            level = summary[code]
        else:                                         # 불펜(필승조·추격조)의 구위
            o = OPP_PITCHERS[code]
            level = round(W.level(league) + (o['velocity'] + o['breaking'] + o['control']) / 3)
        rows.append(dict(g, code=code, label=label, level=level,
                         note=GROUP_NOTE.get(code, ''),
                         avg_text=rate(g['h'] / g['ab']) if g['ab'] else '-',
                         obp_text=rate((g['h'] + g['bb']) / g['pa']) if g['pa'] else '-'))
    return rows


def batting(t: dict) -> dict:
    g = lambda k: t.get(k, 0)  # noqa: E731
    ab, pa = g('ab'), g('pa')
    singles = g('h') - g('d') - g('t') - g('hr')
    tb = singles + 2 * g('d') + 3 * g('t') + 4 * g('hr')
    avg = g('h') / ab if ab else 0.0
    obp = (g('h') + g('bb') + g('hbp')) / pa if pa else 0.0
    slg = tb / ab if ab else 0.0
    woba = ((0.69 * g('bb') + 0.72 * g('hbp') + 0.89 * singles + 1.27 * g('d') + 1.62 * g('t') + 2.10 * g('hr')) / pa
            if pa else 0.0)
    return {'avg': avg, 'obp': obp, 'slg': slg, 'ops': obp + slg, 'woba': woba, 'tb': tb, 'singles': singles,
            'iso': slg - avg, 'k_pct': g('so') / pa if pa else 0.0, 'bb_pct': g('bb') / pa if pa else 0.0}


def pitching(t: dict) -> dict:
    g = lambda k: t.get(k, 0)  # noqa: E731
    ip = g('outs') / 3
    era = g('er') * 9 / ip if ip else 0.0
    whip = (g('h') + g('bb')) / ip if ip else 0.0
    fip = (13 * g('hr') + 3 * (g('bb') + g('hbp')) - 2 * g('so')) / ip + FIP_C if ip else 0.0
    dec = g('w') + g('l')
    return {'ip': ip, 'ip_text': ip_text(g('outs')), 'era': era, 'whip': whip, 'fip': fip,
            'k9': g('so') * 9 / ip if ip else 0.0, 'bb9': g('bb') * 9 / ip if ip else 0.0,
            'wpct': g('w') / dec if dec else 0.0, 'decisions': dec}


def war(role: str, position: str, t: dict) -> float:
    if role == 'pitcher':
        p = pitching(t)
        return round((REPL_FIP - p['fip']) * p['ip'] / 9 / 10, 1) if p['ip'] else 0.0
    pa = t.get('pa', 0)
    if not pa:
        return 0.0
    b = batting(t)
    wraa = (b['woba'] - LG_WOBA) / WOBA_SCALE * pa
    games = t.get('g', 0)
    full = SEASON_GAMES * 4.2                                   # 주전 한 시즌 타석
    runs = (wraa + 20 * pa / 600 + POS_ADJ.get(position, 0) * min(games / SEASON_GAMES, pa / full) + t.get('def', 0)
            + 0.2 * t.get('sb', 0) - 0.4 * t.get('cs', 0))
    return round(runs / 10, 1)


def qualified(role: str, t: dict, team_games: int, mult: float | None = None) -> bool:
    if role == 'pitcher':
        return t.get('outs', 0) / 3 >= (QUAL_IP if mult is None else mult) * team_games
    return t.get('pa', 0) >= (QUAL_PA if mult is None else mult) * team_games


def line_view(role: str, t: dict) -> dict:
    """화면용 시즌 줄 — 숫자·표기 모두."""
    if role == 'pitcher':
        p = pitching(t)
        no = not t.get('outs')
        return dict(t, **p, era_text='-' if no else f"{p['era']:.2f}", whip_text='-' if no else f"{p['whip']:.2f}",
                    fip_text='-' if no else f"{p['fip']:.2f}", wpct_text=rate(p['wpct']) if p['decisions'] else '-')
    b = batting(t)
    no_ab, no_pa = not t.get('ab'), not t.get('pa')
    return dict(t, **b, avg_text='-' if no_ab else rate(b['avg']), obp_text='-' if no_pa else rate(b['obp']),
                slg_text='-' if no_ab else rate(b['slg']), ops_text='-' if no_pa else rate(b['ops']))


# ───────────────────────────── 하루 진행
def _active_q(day: date):
    from .models import RookieLog
    return RookieLog.objects.filter(kind__in=('earn', 'start'), day__gt=day - timedelta(days=ACTIVE_DAYS), day__lte=day)


def active_players(day: date) -> set:
    return set(_active_q(day).values_list('player_id', flat=True))


def was_active(p, day: date) -> bool:
    return _active_q(day).filter(player=p).exists()


def day_end(day: date):
    """그날이 끝나는 순간(현지 시각) — 날짜 비교를 DB 시간대 변환(__date)에 기대지 않으려고.
    MySQL 에 시간대 테이블이 없으면 __date 조회가 비어 아무도 경기에 못 나간다."""
    return timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))


def simulate_day(day: date, rng=None) -> int:
    """day 의 경기를 모든 출전 선수에 대해 치른다. 이미 치렀으면 0. 시즌 마지막 날이면 시상까지."""
    from .models import RookiePlayer, RookieSeason
    rng = rng or random.SystemRandom()
    if not in_season(day):
        return 0
    season = get_season(season_no(day))
    played = failed = 0
    with transaction.atomic():
        # 다른 프로세스(밤 cron·화면 따라잡기)가 같은 시즌을 치르는 중이면 기다리지 않고 넘어간다
        s = RookieSeason.objects.select_for_update(skip_locked=True).filter(pk=season.pk).first()
        if s is None or (s.simulated_through and s.simulated_through >= day):
            return 0
        active = active_players(day)
        for p in RookiePlayer.objects.filter(created_at__lt=day_end(day), retired_at__isnull=True) \
                .select_related('user'):
            if p.pk not in active or (p.pending or {}).get('kind') == 'draft':    # 졸업하고 진로를 고르는 중이면 쉰다
                continue
            try:
                with transaction.atomic():             # 선수 한 명의 오류가 다른 선수의 경기를 막지 않게
                    _play(p, s, day, rng)
                played += 1
            except Exception:  # noqa: BLE001
                failed += 1
                logger.exception('야구선수 키우기 경기 진행 실패: player=%s day=%s', p.pk, day)
        try:
            from .rookie_legacy import after_day
            with transaction.atomic():
                after_day(s, day)                      # 오늘의 베스트 9
        except Exception:  # noqa: BLE001
            logger.exception('야구선수 키우기 %s 베스트 9 실패', day)
        s.simulated_through = day
        s.save(update_fields=['simulated_through'])
    if failed:
        logger.error('야구선수 키우기 %s 경기 진행: 성공 %s명, 실패 %s명', day, played, failed)
    if day == s.end:
        try:
            close_season(s)
        except Exception:  # noqa: BLE001 — 다음 실행의 close_due 가 다시 시도한다
            logger.exception('야구선수 키우기 시즌 %s 시상 실패', s.number)
    return played


def _play(p, s, day: date, rng):
    """선수 한 명의 그날 경기 — 타순·보직 판정 → 출전 → 누적 → 경기 경험(성장)·이정표."""
    from .models import RookieGame, RookieSeasonStat
    from . import rookie_career as C
    from . import rookie_legacy as G
    league, lvl = p.league, W.level(p.league)
    assign_role(p, day, lvl)
    stat, _ = RookieSeasonStat.objects.get_or_create(
        season=s, player=p, league=league,
        defaults={'user': p.user, 'name': p.name, 'number': p.number, 'team': p.club, 'role': p.role,
                  'position': p.position, 'age': p.age})
    nos = list(league_games_on(day, league))
    gs = C.game_stats(p)
    pro = W.is_pro(league)
    before = G.pro_totals(p) if pro else None                   # 이정표 비교용(프로 통산)
    debut = pro and not RookieGame.objects.filter(player=p, league=league).exists()
    results = []
    if p.role == 'batter':
        for no in nos:
            r = batter_game(gs, p.position or 'DH', lvl, rng, role=p.lineup, slot=p.slot)
            if r:
                results.append((no, r))
    elif p.lineup == 'sp':
        if pro or (day - EPOCH).days % 2 == p.pk % 2:           # 학생 선발은 이틀에 한 번
            results.append((nos[p.pk % len(nos)], starter_game(gs, lvl, rng)))
    else:
        for no in nos:
            if len(results) < RELIEF_PER_DAY and rng.random() < RELIEF[p.lineup][0]:
                results.append((no, relief_game(gs, lvl, rng, p.lineup)))
    opps = W.opponents(league, p.club)
    games, lines = [], []
    for no, r in results:
        games.append(RookieGame(season=s, player=p, league=league, day=day, no=no, opponent=rng.choice(opps),
                                home=rng.random() < 0.5, team_runs=r['team_runs'], opp_runs=r['opp_runs'],
                                line=dict(r['line'], club=p.club), summary=r['summary']))
        stat.totals = add(stat.totals, r['line'])
        lines.append(r['line'])
    xp = C.game_xp(p, lines) if lines else {}
    if xp:
        games[-1].line['xp'] = xp
    RookieGame.objects.bulk_create(games)
    stat.name, stat.number, stat.team, stat.position, stat.age = p.name, p.number, p.club, p.position, p.age
    stat.best_ovr = max(stat.best_ovr or 0.0, p.ovr)
    stat.war = war(p.role, p.position, stat.totals)
    stat.save()
    fields = ['stats', 'ovr', 'best_ovr'] if xp else []
    if lines and any(C.has(p, t) and t not in (p.traits_seen or []) for t in ('clutch', 'learner')) \
            and RookieGame.objects.filter(player=p).count() >= 15:
        if C.reveal(p, 'clutch', day) | C.reveal(p, 'learner', day):
            fields.append('traits_seen')
    if fields:
        p.save(update_fields=fields)
    if lines and pro:
        G.milestones(p, league, day, before, lines, debut)


def recent_lines(p, day: date, league: str, days: int = 10) -> list:
    from .models import RookieGame
    return list(RookieGame.objects.filter(player=p, league=league, day__lte=day, day__gt=day - timedelta(days=days))
                .values_list('line', flat=True))


def assign_role(p, day: date, lvl: float) -> str:
    """경기 전 타순·보직 판정(한 계단씩). 바뀌면 저장하고 기록에 남긴다. 바뀐 이유(없으면 '')."""
    from . import rookie as R
    recent = recent_lines(p, day - timedelta(days=1), p.league)
    if p.role == 'pitcher':
        role, slot, why = pitcher_role(p.lineup, p.stats, lvl, recent)
    else:
        role, slot, why = batter_role(p.lineup, p.stats, p.ovr, lvl, recent)
    if (role, slot) != (p.lineup, p.slot):
        first = not p.lineup
        up = role_rank(p.role, role) > role_rank(p.role, p.lineup)
        if up and not first and p.role_since and (day - p.role_since).days < MIN_STAY:
            return ''                                   # 새 자리에서 아직 증명할 시간이 필요하다
        changed_role = role != p.lineup
        p.lineup, p.slot = role, slot
        if changed_role:
            p.role_since = day
        p.save(update_fields=['lineup', 'slot', 'role_since'])
        if why and not first:
            R._log(p, 'role', why, day=day)
    return why


def role_rank(kind: str, role: str) -> int:
    """계단 높이 — 타자 백업 0 · 하위 1 · 상위·중심 2, 투수 패전조 0 … 마무리 4, 선발 2."""
    from .rookie_sim import BAT_STEP, PEN_LADDER
    if kind == 'pitcher':
        return 2 if role == 'sp' else PEN_LADDER.index(role) if role in PEN_LADDER else -1
    return BAT_STEP.get(role, -1)


def advance(today: date | None = None, *, max_days: int = 60) -> int:
    """어제까지 치르지 않은 경기일을 차례로 치른다(밤 cron·화면에서 따라잡기). 치른 날 수."""
    from .models import RookieSeason
    today = today or timezone.localdate()
    last = today - timedelta(days=1)
    if last < EPOCH:
        return 0
    done = RookieSeason.objects.exclude(simulated_through=None).order_by('-simulated_through') \
        .values_list('simulated_through', flat=True).first()
    day = max(done + timedelta(days=1) if done else EPOCH, last - timedelta(days=max_days - 1))
    n = 0
    while day <= last:
        if in_season(day):
            simulate_day(day)
            n += 1
        day += timedelta(days=1)
    close_due(today)
    return n


def close_due(today: date | None = None) -> int:
    """정규시즌이 끝났는데 아직 시상하지 않은 시즌을 시상한다(시상 실패 뒤 재시도)."""
    from .models import RookieSeason
    today = today or timezone.localdate()
    n = 0
    for s in RookieSeason.objects.filter(closed=False, end__lt=today):
        if s.simulated_through and s.simulated_through >= s.end:
            try:
                close_season(s)
                n += 1
            except Exception:  # noqa: BLE001
                logger.exception('야구선수 키우기 시즌 %s 시상 재시도 실패', s.number)
    return n


# ───────────────────────────── 기록 조회
def stat_rows(season, league: str, role: str, *, hidden: bool = True):
    from .game_visibility import visible
    from .models import RookieSeasonStat
    qs = RookieSeasonStat.objects.filter(season=season, league=league, role=role).select_related('user', 'player')
    return list(visible(qs, 'user') if hidden else qs)


def season_games(league: str = 'kbo1') -> int:
    """그 리그의 한 시즌 팀 경기 수 — 프로 144, 학생 28(하루 한 경기)."""
    return SEASON_GAMES if W.is_pro(league) else SEASON_DAYS


def team_games(season, league: str = 'kbo1') -> int:
    if season.closed or (season.simulated_through and season.simulated_through >= season.end):
        return season_games(league)
    sim = season.simulated_through
    if not sim:
        return 0
    return games_through(sim) if W.is_pro(league) else min(SEASON_DAYS, (sim - season.start).days + 1)


# 부문 수는 6 — 화면에서 3열·2열로 고아 칸 없이 떨어지게(design-guardrails 5)
BAT_LEADERS = [('avg', '타율', True, 'avg_text'), ('hr', '홈런', False, 'hr'), ('rbi', '타점', False, 'rbi'),
               ('ops', 'OPS', True, 'ops_text'), ('sb', '도루', False, 'sb'), ('war', 'WAR', False, 'war')]
PIT_LEADERS = [('era', '평균자책점', True, 'era_text'), ('w', '다승', False, 'w'), ('so', '탈삼진', False, 'so'),
               ('sv', '세이브', False, 'sv'), ('hld', '홀드', False, 'hld'), ('war', 'WAR', False, 'war')]
LOW_IS_BETTER = {'era', 'whip'}


def leaders(season, league: str, role: str, top: int = 5) -> list:
    rows = stat_rows(season, league, role)
    tg = team_games(season, league)
    views = [{'s': r, 'v': line_view(role, r.totals), 'war': r.war} for r in rows]
    out = []
    for key, label, needs_qual, shown in (PIT_LEADERS if role == 'pitcher' else BAT_LEADERS):
        pool = [x for x in views if not needs_qual or qualified(role, x['s'].totals, tg)]
        val = (lambda x: x['war']) if key == 'war' else (lambda x, k=key: x['v'].get(k, 0))
        pool = [x for x in pool if key in LOW_IS_BETTER or val(x) > 0]
        pool.sort(key=val, reverse=key not in LOW_IS_BETTER)
        out.append({'key': key, 'label': label, 'qual': needs_qual,
                    'rows': [{'s': x['s'], 'value': x['war'] if key == 'war' else x['v'].get(shown)}
                             for x in pool[:top]]})
    return out


def career_highs(role: str, league: str = 'kbo1', limit: int = 20) -> list:
    """그 리그 시즌 가운데 선수마다 가장 좋았던 시즌(WAR) 하나씩 — 커리어하이 비교판."""
    from .game_visibility import visible
    from .models import RookieSeasonStat
    qs = visible(RookieSeasonStat.objects.filter(league=league, role=role), 'user').select_related('season')
    best = {}
    for r in qs:
        if not r.season.closed and team_games(r.season, league) < season_games(league) // 2:
            continue                                    # 진행 중 시즌은 반환점을 지나야 견준다
        key = r.player_id or f'u{r.user_id}:{r.name}'   # 은퇴한 선수도 한 사람에 한 줄
        if key not in best or r.war > best[key].war:
            best[key] = r
    rows = sorted(best.values(), key=lambda r: r.war, reverse=True)[:limit]
    top = rows[0].war if rows and rows[0].war > 0 else 1.0
    return [{'s': r, 'v': line_view(role, r.totals), 'live': not r.season.closed,
             'bar': max(2.0, min(100.0, r.war / top * 100)) if r.war > 0 else 2.0} for r in rows]


RECORDS = [('batter', 'hr', '시즌 최다 홈런', False, 'hr'), ('batter', 'avg', '시즌 최고 타율', True, 'avg_text'),
           ('batter', 'rbi', '시즌 최다 타점', False, 'rbi'), ('batter', 'ops', '시즌 최고 OPS', True, 'ops_text'),
           ('batter', 'sb', '시즌 최다 도루', False, 'sb'), ('batter', 'h', '시즌 최다 안타', False, 'h'),
           ('pitcher', 'w', '시즌 최다승', False, 'w'), ('pitcher', 'era', '시즌 최저 평균자책점', True, 'era_text'),
           ('pitcher', 'so', '시즌 최다 탈삼진', False, 'so'), ('pitcher', 'whip', '시즌 최저 WHIP', True, 'whip_text'),
           ('pitcher', 'sv', '시즌 최다 세이브', False, 'sv'), ('pitcher', 'hld', '시즌 최다 홀드', False, 'hld')]


def season_records(league: str = 'kbo1') -> list:
    """그 리그 단일 시즌 기록 — 끝난 시즌만(진행 중 시즌의 첫날 .500 이 기록이 되지 않게), 비율 기록은 규정을 채운 시즌만."""
    from .game_visibility import visible
    from .models import RookieSeasonStat
    rows = list(visible(RookieSeasonStat.objects.filter(league=league, season__closed=True), 'user')
                .select_related('season'))
    out = []
    for role, key, label, needs_qual, shown in RECORDS:
        pool = []
        for r in rows:
            if r.role != role:
                continue
            if needs_qual and not qualified(role, r.totals, team_games(r.season, league)):
                continue
            v = line_view(role, r.totals)
            if key not in LOW_IS_BETTER and not v.get(key):
                continue
            pool.append((v.get(key, 0), r, v))
        pool.sort(key=lambda x: x[0], reverse=key not in LOW_IS_BETTER)
        best = pool[0] if pool else None
        out.append({'role': role, 'label': label, 'value': best[2].get(shown) if best else None,
                    's': best[1] if best else None, 'live': bool(best and not best[1].season.closed)})
    return out


# ───────────────────────────── 시상
AWARD_STYLE = {                       # 각 나라 최상위 리그 — 포지션별 수상 이름, 투수 포함 여부, 최고 투수상
    'kbo1': {'gg': '골든글러브', 'gg_pitcher': True, 'ace': ''},
    'mlb': {'gg': '실버슬러거', 'gg_pitcher': False, 'ace': '사이영상'},
    'npb1': {'gg': '베스트 나인', 'gg_pitcher': True, 'ace': '사와무라상'},
    'cpbl': {'gg': '베스트 텐', 'gg_pitcher': True, 'ace': ''},
}
MINOR_MVP = {'kbo2': '퓨처스 MVP', 'kbo3': '육성군 MVP', 'mlb_aaa': '트리플A MVP', 'mlb_aa': '더블A MVP',
             'mlb_a': '싱글A MVP', 'npb2': 'NPB 2군 MVP'}
TITLES = [('batter', '타격왕', lambda r: batting(r.totals)['avg'], True, lambda r: rate(batting(r.totals)['avg'])),
          ('batter', '홈런왕', lambda r: r.totals.get('hr', 0), False, lambda r: f"{r.totals.get('hr', 0)}홈런"),
          ('batter', '타점왕', lambda r: r.totals.get('rbi', 0), False, lambda r: f"{r.totals.get('rbi', 0)}타점"),
          ('batter', '도루왕', lambda r: r.totals.get('sb', 0), False, lambda r: f"{r.totals.get('sb', 0)}도루"),
          ('batter', '최다안타', lambda r: r.totals.get('h', 0), False, lambda r: f"{r.totals.get('h', 0)}안타"),
          ('batter', '출루율 1위', lambda r: batting(r.totals)['obp'], True, lambda r: rate(batting(r.totals)['obp'])),
          ('pitcher', '다승왕', lambda r: r.totals.get('w', 0), False, lambda r: f"{r.totals.get('w', 0)}승"),
          ('pitcher', '평균자책점 1위', lambda r: -pitching(r.totals)['era'], True,
           lambda r: f"{pitching(r.totals)['era']:.2f}"),
          ('pitcher', '탈삼진왕', lambda r: r.totals.get('so', 0), False, lambda r: f"{r.totals.get('so', 0)}탈삼진"),
          ('pitcher', '승률왕', lambda r: pitching(r.totals)['wpct'], False, lambda r: rate(pitching(r.totals)['wpct'])),
          ('pitcher', '세이브왕', lambda r: r.totals.get('sv', 0), False, lambda r: f"{r.totals.get('sv', 0)}세이브"),
          ('pitcher', '홀드왕', lambda r: r.totals.get('hld', 0), False, lambda r: f"{r.totals.get('hld', 0)}홀드")]
AMATEUR_TITLES = [t for t in TITLES if t[1] in ('타격왕', '홈런왕', '평균자책점 1위')]
AMATEUR_LABEL = {'타격왕': '타격상', '홈런왕': '홈런상', '평균자책점 1위': '우수투수상'}


def bat_val(r) -> str:
    b = batting(r.totals)
    return f"{rate(b['avg'])} {r.totals.get('hr', 0)}홈런 {r.totals.get('rbi', 0)}타점 WAR {r.war}"


def pit_val(r) -> str:
    p = pitching(r.totals)
    return f"{r.totals.get('w', 0)}승 {r.totals.get('l', 0)}패 ERA {p['era']:.2f} WAR {r.war}"


def award_val(r) -> str:
    return pit_val(r) if r.role == 'pitcher' else bat_val(r)


def gg_val(r) -> str:                  # 다이아몬드 칸에 들어가는 짧은 줄
    if r.role == 'pitcher':
        return f"WAR {r.war} · {r.totals.get('w', 0)}승 {pitching(r.totals)['era']:.2f}"
    return f"WAR {r.war} · {rate(batting(r.totals)['avg'])} {r.totals.get('hr', 0)}홈런"


def rank_key(r):                       # WAR 가 같으면 타자는 OPS, 투수는 낮은 평균자책점·많은 이닝
    if r.role == 'pitcher':
        p = pitching(r.totals)
        return (r.war, -p['era'], p['ip'])
    b = batting(r.totals)
    return (r.war, b['ops'], r.totals.get('pa', 0))


def _titles(give, bats, pits, tg, table, rename=None):
    for j, (role, label, key, needs_qual, shown) in enumerate(table):
        pool = [r for r in (bats if role == 'batter' else pits)
                if (not needs_qual or qualified(role, r.totals, tg))
                and (label != '승률왕' or pitching(r.totals)['decisions'] >= 10)]
        pool = [r for r in pool if needs_qual or key(r) > 0]
        if pool:
            best = shown(max(pool, key=key))
            for r in pool:                  # 공동 수상 — 화면에 보이는 값이 같으면 함께 받는다
                if shown(r) == best:
                    give('title', (rename or {}).get(label, label), r, best, order=30 + j)


def _league_awards(s, code: str, give):
    from .models import RookieSeasonStat
    bats, pits = stat_rows(s, code, 'batter'), stat_rows(s, code, 'pitcher')
    tg = season_games(code)
    if code in AWARD_STYLE:
        style = AWARD_STYLE[code]
        cand_b = [r for r in bats if qualified('batter', r.totals, tg, AWARD_PA)]
        cand_p = [r for r in pits if qualified('pitcher', r.totals, tg, AWARD_IP)]
        if cand_b or cand_p:
            mvp = max(cand_b + cand_p, key=rank_key)
            give('mvp', 'MVP', mvp, award_val(mvp), order=1)
        # 신인왕: 이 회원이 예전 시즌에 이 리그 경기를 뛴 적이 없어야 한다(은퇴 뒤 재입단한 베테랑은 신인이 아니다)
        earlier = {uid for uid, t in RookieSeasonStat.objects.filter(league=code, season__number__lt=s.number)
                   .values_list('user_id', 'totals') if (t or {}).get('g', 0) > 0}
        rookies = [r for r in bats + pits if r.user_id not in earlier
                   and qualified(r.role, r.totals, tg, AWARD_PA / 2 if r.role == 'batter' else AWARD_IP / 2)]
        if rookies:
            roy = max(rookies, key=rank_key)
            give('rookie', '신인왕', roy, award_val(roy), order=2)
        if style['ace'] and cand_p:
            ace = max(cand_p, key=rank_key)
            give('ace', style['ace'], ace, pit_val(ace), order=3)
        if style['gg_pitcher'] and cand_p:
            gp = max(cand_p, key=rank_key)
            give('gg', f"{style['gg']} 투수", gp, gg_val(gp), position='SP', order=10)
        for i, (pos, label) in enumerate(POSITIONS):
            pool = sorted([r for r in cand_b if r.position == pos], key=rank_key, reverse=True)
            for r in pool[:3 if pos == 'OF' else 1]:
                give('gg', f"{style['gg']} {label}", r, gg_val(r), position=pos, order=11 + i)
        _titles(give, bats, pits, tg, TITLES)
    elif W.is_pro(code):
        pool = [r for r in bats + pits if qualified(r.role, r.totals, tg, AWARD_PA if r.role == 'batter' else AWARD_IP)]
        if pool:
            m = max(pool, key=rank_key)
            give('minor', MINOR_MVP.get(code, f'{W.short(code)} MVP'), m, award_val(m), order=50)
    else:
        pool = [r for r in bats if r.totals.get('pa', 0) >= AM_AWARD_PA] + \
               [r for r in pits if r.totals.get('outs', 0) >= AM_AWARD_OUTS]
        if pool:
            m = max(pool, key=rank_key)
            give('minor', f"{W.short(code)} 최우수선수", m, award_val(m), order=50)
        _titles(give, bats, pits, tg, AMATEUR_TITLES, AMATEUR_LABEL)


def close_season(season) -> list:
    """리그마다 시상(AWARD_STYLE·MINOR_MVP·아마추어). 이미 시상했으면 건너뛴다."""
    from .models import RookieAward, RookieSeason, RookieSeasonStat
    from . import rookie as R
    with transaction.atomic():
        s = RookieSeason.objects.select_for_update().get(pk=season.pk)
        if s.closed:
            return []
        awards = []
        codes = set(RookieSeasonStat.objects.filter(season=s).values_list('league', flat=True))
        for code in sorted(codes, key=lambda c: -W.level(c)):
            def give(kind, label, r, value, position='', order=0, code=code):
                awards.append(RookieAward(season=s, user=r.user, player=r.player, stat=r, league=code, kind=kind,
                                          label=label, position=position, name=r.name, team=r.team, role=r.role,
                                          value=value, order=order))
            _league_awards(s, code, give)
        RookieAward.objects.bulk_create(awards)
        s.closed, s.closed_at = True, timezone.now()
        s.save(update_fields=['closed', 'closed_at'])
        for a in awards:
            if a.player_id:
                R._log(a.player, 'award', f'시즌 {s.number} {W.short(a.league)} {a.label} 수상 — {a.value}')
    return awards


# ───────────────────────────── 화면용 묶음
def team_short(code: str) -> str:
    return W.club_short('', code)


def vs_label(role: str, vs: str, line: dict | None = None) -> str:
    line = line or {}
    if role == 'pitcher':
        lead = line.get('lead', 0)
        if line.get('gr'):
            return f'{lead}점 리드' if lead > 0 else f'{-lead}점 차 추격' if lead < 0 else '동점'
        return next((label for key, label, _o, _w in LINEUP_FORMS if key == vs), '')
    if vs in ('setup', 'mop'):
        return '대타 · ' + ('필승조' if vs == 'setup' else '추격조')
    return f"{GRADE_LABEL[vs]} 선발" if vs in GRADE_LABEL else ''


def game_view(g, my_team: str, role: str = 'batter') -> dict:
    vs = g.line.get('vs', '')
    return {'no': g.no, 'day': g.day, 'league': W.short(g.league), 'league_code': g.league,
            'me': W.club_short(g.league, g.line.get('club') or my_team), 'xp': g.line.get('xp') or {},
            'vs': vs, 'vs_label': vs_label(role, vs, g.line), 'vs_lvl': g.line.get('vs_lvl') or '',
            'vs_short': (vs_label(role, vs, g.line) if role == 'pitcher' or vs in ('setup', 'mop')
                         else GRADE_LABEL.get(vs, '')),
            'relief': bool(g.line.get('gr')), 'inn': g.line.get('inn'),
            'splits': [x for x in splits(role, g.line) if x['pa']] if role == 'pitcher' else [],
            'opp': W.club_short(g.league, g.opponent), 'opp_code': g.opponent, 'mine': g.team_runs, 'theirs': g.opp_runs,
            'win': g.team_runs > g.opp_runs, 'summary': g.summary, 'line': g.line, 'home': g.home,
            'ip': ip_text(g.line.get('outs', 0))}


def season_lines(stats, season=None) -> list:
    """시즌 기록 행들 → 화면용(리그 이름·규정 진행률 포함)."""
    out = []
    for r in stats:
        tg = team_games(season or r.season, r.league)
        need = (QUAL_IP if r.role == 'pitcher' else QUAL_PA) * tg
        have = r.totals.get('outs', 0) / 3 if r.role == 'pitcher' else r.totals.get('pa', 0)
        out.append({'s': r, 'v': line_view(r.role, r.totals), 'league': W.short(r.league),
                    'league_name': W.league(r.league)['name'], 'team_name': W.team_label(r.team),
                    'top': r.league in W.TOP_LEAGUES,
                    'splits': splits(r.role, r.totals, r.league),
                    'qual_need': int(math.ceil(need)), 'qual_have': int(have),
                    'qual_pct': round(min(100.0, have / need * 100), 1) if need else 0.0,
                    'qualified': bool(need) and have >= need})
    return out


def player_board(p, today: date | None = None) -> dict:
    """내 선수 화면의 리그 부분 — 시즌 상황, 이번 시즌 기록, 최근 경기일의 경기들, 결장 여부, 트로피."""
    from .models import RookieAward, RookieGame, RookieSeasonStat
    today = today or timezone.localdate()
    st = season_state(today)
    season = get_season(st['number']) if st['phase'] == 'season' else None
    lines = []
    if season:
        rows = sorted(RookieSeasonStat.objects.filter(season=season, player=p).select_related('season'),
                      key=lambda r: -W.level(r.league))
        lines = season_lines(rows, season)
    main = next((x for x in lines if x['s'].league == p.league), lines[0] if lines else None)
    last_day = RookieGame.objects.filter(player=p).order_by('-day').values_list('day', flat=True).first()
    if p.role == 'pitcher' and p.lineup not in ('sp', ''):
        # 구원은 하루 한두 번 — 최근 등판 다섯 번을 보여 준다
        games = [game_view(g, p.team, p.role) for g in RookieGame.objects.filter(player=p).order_by('-day', '-no')[:5]]
    else:
        games = [game_view(g, p.team, p.role) for g in RookieGame.objects.filter(player=p, day=last_day).order_by('no')] \
            if last_day else []
    sim = season.simulated_through if season else None
    created = timezone.localtime(p.created_at).date()           # UTC 날짜로 비교하면 오전 입단자가 결장으로 보인다
    dnp = bool(sim and sim >= max(season.start, created) and not was_active(p, sim))
    trophies = list(RookieAward.objects.filter(player=p).select_related('season').order_by('-season__number', 'order'))
    league = (RookieGame.objects.filter(player=p, day=last_day).values_list('league', flat=True).first()
              if last_day else None) or p.league
    xp = {}
    for g in games:
        for k, v in g['xp'].items():
            xp[k] = round(xp.get(k, 0) + v, 2)
    from .rookie import ROLES
    labels = {k: lab for k, lab, _w in ROLES[p.role]['stats']}
    return {'season': st, 'season_obj': season, 'lines': lines, 'main_line': main, 'games': games,
            'games_day': last_day, 'dnp': dnp and not (p.pending or {}).get('kind') == 'draft',
            'relief_log': bool(games and games[0]['relief'] and len(games) > 1), 'trophies': trophies,
            'pos_label': POS_LABEL.get(p.position, ''), 'opp_levels': opp_levels(league), 'board_league': W.short(league),
            'xp_rows': [{'label': labels.get(k, k), 'gain': v} for k, v in sorted(xp.items(), key=lambda x: -x[1]) if v >= 0.01],
            'graduated': (p.pending or {}).get('kind') == 'draft', 'ladder': ladder_of(p)}


def ladder_of(p) -> dict:
    from .rookie_sim import role_ladder
    return role_ladder(p.role, p.lineup, p.slot, p.stats, p.ovr, W.level(p.league))


def highlights(stat) -> list:
    """명판에 크게 놓을 숫자 몇 개 — [(라벨, 값)]."""
    if stat is None:
        return []
    v = line_view(stat.role, stat.totals)
    if stat.role == 'pitcher':
        return [('승', v.get('w', 0)), ('평균자책점', v['era_text']), ('탈삼진', v.get('so', 0)),
                ('이닝', v['ip_text']), ('WAR', stat.war)]
    return [('타율', v['avg_text']), ('홈런', v.get('hr', 0)), ('타점', v.get('rbi', 0)), ('OPS', v['ops_text']),
            ('WAR', stat.war)]
