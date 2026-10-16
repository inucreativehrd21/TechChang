"""야구선수 키우기 — 리그(시즌·경기·기록·시상). 성장 규칙은 rookie.py.

시즌: 2026-10-19(월) 개막, 4주(28일)에 144경기 — 하루 5~6경기, KBO 한 시즌 분량.
매일 밤 rookie_daily 가 전날 경기를 시뮬레이션하고(advance), 시즌 마지막 날 다음 정산에서 시상한다(close_season).
- 출전: 경기일 포함 최근 3일 안에 활동(TP 획득)이 있어야 엔트리에 든다. 쉬면 결장 → 규정타석·이닝을 못 채운다.
- 리그는 소속 그대로: 1군 · 퓨처스(2군) · 3군(육성군 연습경기). 기록은 리그별로 따로 쌓는다.
- 타자는 그날 모든 경기에, 투수는 선발 로테이션으로 하루 한 경기에 나간다(시즌 ≈ 28선발 170이닝).

경기 모형(타석 승부·상대 선수·내 타순과 보직·경기 시뮬레이션)은 community/rookie_sim.py.
같은 수준끼리면 리그 평균 ≈ .265/.325/.435, 평균자책점 ≈ 4 — test_rookie_league 가 몬테카를로로 지킨다.
투수 보직: 선발(하루 한 경기) · 구원(그날 경기 중 보직별 확률로 하루 두 번까지) — 세이브·홀드·블론세이브.

WAR(추정, 실제 KBO 공식이 아니라 같은 뼈대의 근사):
- 타자 = (wRAA + 대체 수준 20점/600타석 + 포지션 보정 + 수비 + 주루) / 10, wOBA 가중치는 흔히 쓰는 근사값.
- 투수 = (대체 수준 FIP − FIP) × 이닝/9 / 10.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

EPOCH = date(2026, 10, 19)
SEASON_DAYS, SEASON_GAMES = 28, 144
LEVEL = {0: 34.0, 1: 48.0, 2: 64.0}                # 리그별 상대 평균 수준(능력치 척도)
LEAGUE = {0: '3군', 1: '퓨처스', 2: '1군'}
ACTIVE_DAYS = 3                                    # 경기일 포함 최근 3일 안에 활동해야 출전
QUAL_PA, QUAL_IP = 3.1, 1.0                        # 규정타석·규정이닝(팀 경기 수 × 배수, KBO 와 같다)
AWARD_PA, AWARD_IP = 2.0, 0.6                      # MVP·골든글러브 후보 최소(팀 경기 수 × 배수)

PITCHER_POS = 'SP'
POSITIONS = [('C', '포수'), ('1B', '1루수'), ('2B', '2루수'), ('3B', '3루수'), ('SS', '유격수'),
             ('OF', '외야수'), ('DH', '지명타자')]
POS_LABEL = dict(POSITIONS, SP='투수')
POS_ADJ = {'C': 12.0, 'SS': 7.0, '2B': 3.0, '3B': 2.0, 'OF': -2.0, '1B': -10.0, 'DH': -15.0}   # 144경기 기준 점수
ERR_BASE = {'C': .03, '1B': .03, '2B': .05, '3B': .07, 'SS': .08, 'OF': .03}

META_KEYS = ('vs', 'vs_lvl', 'bslot', 'lead', 'inn')                      # 경기 줄 설명 값 — 시즌 누적에서 뺀다

BAT_KEYS = ('g', 'pa', 'ab', 'h', 'd', 't', 'hr', 'rbi', 'r', 'bb', 'hbp', 'so', 'sb', 'cs', 'e', 'def',
            'ph', 'pr', 'dr')                                                  # 대타·대주자·대수비 출장
PIT_KEYS = ('g', 'gs', 'gr', 'w', 'l', 'sv', 'hld', 'bs', 'qs', 'cg', 'sho', 'outs', 'h', 'r', 'er', 'bb', 'hbp',
            'so', 'hr', 'bf', 'np')
LG_WOBA, WOBA_SCALE, FIP_C, REPL_FIP = 0.327, 1.20, 2.94, 5.10   # 몬테카를로로 맞춘 리그 평균


# ───────────────────────────── 시즌 달력
def season_no(day: date) -> int:
    return (day - EPOCH).days // SEASON_DAYS + 1 if day >= EPOCH else 0


def season_bounds(n: int) -> tuple[date, date]:
    start = EPOCH + timedelta(days=(n - 1) * SEASON_DAYS)
    return start, start + timedelta(days=SEASON_DAYS - 1)


def games_through(day: date) -> int:
    """그 시즌에서 day 까지(포함) 치른 팀 경기 수."""
    n = season_no(day)
    if not n:
        return 0
    i = (day - season_bounds(n)[0]).days
    return (i + 1) * SEASON_GAMES // SEASON_DAYS


def games_on(day: date) -> range:
    """day 에 치르는 시즌 경기 번호들(1부터)."""
    n = season_no(day)
    if not n:
        return range(0)
    i = (day - season_bounds(n)[0]).days
    return range(i * SEASON_GAMES // SEASON_DAYS + 1, (i + 1) * SEASON_GAMES // SEASON_DAYS + 1)


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
    played = games_through(today - timedelta(days=1)) if today > start else 0
    return {'phase': 'season', 'number': n, 'start': start, 'end': end, 'played': played,
            'total': SEASON_GAMES, 'pct': round(played / SEASON_GAMES * 100, 1), 'left_days': (end - today).days + 1}


# ───────────────────────────── 경기 모형(rookie_sim)
from .rookie_sim import (BAT_ROLES, BAT_SPLITS, GRADE_LABEL, GROUP_NOTE, LINEUP_FORMS, PIT_ROLES,  # noqa: E402,F401
                         PIT_SPLITS, RELIEF, RELIEF_PER_DAY, STARTER_GRADES, STARTER_PA, batter_game, batter_role,
                         opp_summary, pa_probs, pitcher_role, relief_game, starter_game)

pitcher_game = starter_game                      # 예전 이름(선발 등판)


def opp_levels(league: int) -> dict:
    """리그별 상대 수준 — 상대 선발 등급별 구위와 상대 타선 구간별 대표 능력(화면 안내용)."""
    return opp_summary(LEVEL[league])


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


def splits(role: str, t: dict, league: int | None = None) -> list:
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
            level = round(LEVEL[league] + (o['velocity'] + o['breaking'] + o['control']) / 3)
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
    runs = (wraa + 20 * pa / 600 + POS_ADJ.get(position, 0) * games / SEASON_GAMES + t.get('def', 0)
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
        return dict(t, **p, era_text=f"{p['era']:.2f}", whip_text=f"{p['whip']:.2f}", fip_text=f"{p['fip']:.2f}",
                    wpct_text=rate(p['wpct']))
    b = batting(t)
    return dict(t, **b, avg_text=rate(b['avg']), obp_text=rate(b['obp']), slg_text=rate(b['slg']),
                ops_text=rate(b['ops']))


# ───────────────────────────── 하루 진행
def active_players(day: date) -> set:
    from .models import RookieLog
    return set(RookieLog.objects.filter(kind__in=('earn', 'start'), day__gt=day - timedelta(days=ACTIVE_DAYS),
                                        day__lte=day).values_list('player_id', flat=True))


def simulate_day(day: date, rng=None) -> int:
    """day 의 경기를 모든 출전 선수에 대해 치른다. 이미 치렀으면 0. 시즌 마지막 날이면 시상까지."""
    from .models import RookieGame, RookiePlayer, RookieSeason, RookieSeasonStat
    from . import rookie as R
    rng = rng or random.SystemRandom()
    n = season_no(day)
    if not n:
        return 0
    season = get_season(n)
    played = 0
    with transaction.atomic():
        s = RookieSeason.objects.select_for_update().get(pk=season.pk)
        if s.simulated_through and s.simulated_through >= day:
            return 0
        nos = list(games_on(day))
        active = active_players(day)
        teams = [c for c, _n, _c in R.TEAMS]
        for p in RookiePlayer.objects.filter(created_at__date__lte=day).select_related('user'):
            if p.pk not in active:
                continue
            league, lvl = p.tier, LEVEL[p.tier]
            assign_role(p, day, lvl)
            stat, _ = RookieSeasonStat.objects.get_or_create(
                season=s, player=p, league=league,
                defaults={'user': p.user, 'name': p.name, 'number': p.number, 'team': p.team, 'role': p.role,
                          'position': p.position})
            games = []
            results = []
            if p.role == 'batter':
                for no in nos:
                    r = batter_game(p.stats, p.position or 'DH', lvl, rng, role=p.lineup, slot=p.slot)
                    if r:
                        results.append((no, r))
            elif p.lineup == 'sp':
                results.append((nos[p.pk % len(nos)], starter_game(p.stats, lvl, rng)))
            else:
                for no in nos:
                    if len(results) < RELIEF_PER_DAY and rng.random() < RELIEF[p.lineup][0]:
                        results.append((no, relief_game(p.stats, lvl, rng, p.lineup)))
            for no, r in results:
                games.append(RookieGame(season=s, player=p, league=league, day=day, no=no,
                                        opponent=rng.choice([c for c in teams if c != p.team]),
                                        home=rng.random() < 0.5, team_runs=r['team_runs'], opp_runs=r['opp_runs'],
                                        line=r['line'], summary=r['summary']))
                stat.totals = add(stat.totals, r['line'])
            RookieGame.objects.bulk_create(games)
            stat.name, stat.number, stat.team, stat.position = p.name, p.number, p.team, p.position
            stat.war = war(p.role, p.position, stat.totals)
            stat.save()
            played += 1
        s.simulated_through = day
        s.save(update_fields=['simulated_through'])
    if day == s.end:
        close_season(s)
    return played


def recent_lines(p, day: date, league: int, days: int = 10) -> list:
    from .models import RookieGame
    return list(RookieGame.objects.filter(player=p, league=league, day__lte=day, day__gt=day - timedelta(days=days))
                .values_list('line', flat=True))


def assign_role(p, day: date, lvl: float) -> str:
    """경기 전 타순·보직 판정(한 계단씩). 바뀌면 저장하고 기록에 남긴다. 바뀐 이유(없으면 '')."""
    from . import rookie as R
    recent = recent_lines(p, day - timedelta(days=1), p.tier)
    if p.role == 'pitcher':
        role, slot, why = pitcher_role(p.lineup, p.stats, lvl, recent)
    else:
        role, slot, why = batter_role(p.lineup, p.stats, p.ovr, lvl, recent)
    if (role, slot) != (p.lineup, p.slot):
        first = not p.lineup
        p.lineup, p.slot = role, slot
        p.save(update_fields=['lineup', 'slot'])
        if why and not first:
            R._log(p, 'role', why, day=day)
    return why


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
        simulate_day(day)
        n += 1
        day += timedelta(days=1)
    return n


# ───────────────────────────── 기록 조회
def stat_rows(season, league: int, role: str, *, hidden: bool = True):
    from .game_visibility import visible
    from .models import RookieSeasonStat
    qs = RookieSeasonStat.objects.filter(season=season, league=league, role=role).select_related('user', 'player')
    return list(visible(qs, 'user') if hidden else qs)


def team_games(season) -> int:
    if season.closed or (season.simulated_through and season.simulated_through >= season.end):
        return SEASON_GAMES
    return games_through(season.simulated_through) if season.simulated_through else 0


# 부문 수는 6 — 화면에서 3열·2열로 고아 칸 없이 떨어지게(design-guardrails 5)
BAT_LEADERS = [('avg', '타율', True, 'avg_text'), ('hr', '홈런', False, 'hr'), ('rbi', '타점', False, 'rbi'),
               ('ops', 'OPS', True, 'ops_text'), ('sb', '도루', False, 'sb'), ('war', 'WAR', False, 'war')]
PIT_LEADERS = [('era', '평균자책점', True, 'era_text'), ('w', '다승', False, 'w'), ('so', '탈삼진', False, 'so'),
               ('sv', '세이브', False, 'sv'), ('hld', '홀드', False, 'hld'), ('war', 'WAR', False, 'war')]
LOW_IS_BETTER = {'era', 'whip'}


def leaders(season, league: int, role: str, top: int = 5) -> list:
    rows = stat_rows(season, league, role)
    tg = team_games(season)
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


def career_highs(role: str, limit: int = 20) -> list:
    """1군 시즌 가운데 선수마다 가장 좋았던 시즌(WAR) 하나씩 — 커리어하이 비교판."""
    from .game_visibility import visible
    from .models import RookieSeasonStat
    qs = visible(RookieSeasonStat.objects.filter(league=2, role=role), 'user').select_related('season')
    best = {}
    for r in qs:
        key = r.player_id or f's{r.pk}'
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


def season_records() -> list:
    """1군 단일 시즌 기록 — 비율 기록은 그 시즌 규정을 채운 시즌만."""
    from .game_visibility import visible
    from .models import RookieSeasonStat
    rows = list(visible(RookieSeasonStat.objects.filter(league=2), 'user').select_related('season'))
    out = []
    for role, key, label, needs_qual, shown in RECORDS:
        pool = []
        for r in rows:
            if r.role != role:
                continue
            if needs_qual and not qualified(role, r.totals, team_games(r.season)):
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
def close_season(season) -> list:
    """MVP·신인왕·골든글러브·타이틀·퓨처스 MVP. 이미 시상했으면 건너뛴다."""
    from .models import RookieAward, RookieSeason, RookieSeasonStat
    from . import rookie as R
    with transaction.atomic():
        s = RookieSeason.objects.select_for_update().get(pk=season.pk)
        if s.closed:
            return []
        tg = SEASON_GAMES
        bats, pits = stat_rows(s, 2, 'batter'), stat_rows(s, 2, 'pitcher')
        awards = []

        def give(kind, label, r, value, position='', order=0):
            awards.append(RookieAward(season=s, user=r.user, player=r.player, stat=r, kind=kind, label=label,
                                      position=position, name=r.name, team=r.team, role=r.role, value=value,
                                      order=order))

        def bat_val(r):
            b = batting(r.totals)
            return f"{rate(b['avg'])} {r.totals.get('hr', 0)}홈런 {r.totals.get('rbi', 0)}타점 WAR {r.war}"

        def pit_val(r):
            p = pitching(r.totals)
            return f"{r.totals.get('w', 0)}승 {r.totals.get('l', 0)}패 ERA {p['era']:.2f} WAR {r.war}"

        def gg_val(r):              # 다이아몬드 칸에 들어가는 짧은 줄
            if r.role == 'pitcher':
                return f"WAR {r.war} · {r.totals.get('w', 0)}승 {pitching(r.totals)['era']:.2f}"
            return f"WAR {r.war} · {rate(batting(r.totals)['avg'])} {r.totals.get('hr', 0)}홈런"

        def val(r):
            return pit_val(r) if r.role == 'pitcher' else bat_val(r)

        cand_b = [r for r in bats if qualified('batter', r.totals, tg, AWARD_PA)]
        cand_p = [r for r in pits if qualified('pitcher', r.totals, tg, AWARD_IP)]
        everyone = cand_b + cand_p
        if everyone:
            mvp = max(everyone, key=lambda r: r.war)
            give('mvp', 'MVP', mvp, val(mvp), order=1)
        earlier = set(RookieSeasonStat.objects.filter(league=2, season__number__lt=s.number)
                      .exclude(player=None).values_list('player_id', flat=True))
        rookies = [r for r in bats + pits if r.player_id not in earlier
                   and qualified(r.role, r.totals, tg, AWARD_PA / 2 if r.role == 'batter' else AWARD_IP / 2)]
        if rookies:
            roy = max(rookies, key=lambda r: r.war)
            give('rookie', '신인왕', roy, val(roy), order=2)
        if cand_p:
            gp = max(cand_p, key=lambda r: r.war)
            give('gg', '골든글러브 투수', gp, gg_val(gp), position='SP', order=10)
        for i, (pos, label) in enumerate(POSITIONS):
            pool = sorted([r for r in cand_b if r.position == pos], key=lambda r: r.war, reverse=True)
            for r in pool[:3 if pos == 'OF' else 1]:
                give('gg', f'골든글러브 {label}', r, gg_val(r), position=pos, order=11 + i)
        titles = [('batter', '타격왕', lambda r: batting(r.totals)['avg'], True, lambda r: rate(batting(r.totals)['avg'])),
                  ('batter', '홈런왕', lambda r: r.totals.get('hr', 0), False, lambda r: f"{r.totals.get('hr', 0)}홈런"),
                  ('batter', '타점왕', lambda r: r.totals.get('rbi', 0), False, lambda r: f"{r.totals.get('rbi', 0)}타점"),
                  ('batter', '도루왕', lambda r: r.totals.get('sb', 0), False, lambda r: f"{r.totals.get('sb', 0)}도루"),
                  ('batter', '최다안타', lambda r: r.totals.get('h', 0), False, lambda r: f"{r.totals.get('h', 0)}안타"),
                  ('batter', '출루율 1위', lambda r: batting(r.totals)['obp'], True, lambda r: rate(batting(r.totals)['obp'])),
                  ('pitcher', '다승왕', lambda r: r.totals.get('w', 0), False, lambda r: f"{r.totals.get('w', 0)}승"),
                  ('pitcher', '평균자책점 1위', lambda r: -pitching(r.totals)['era'], True,
                   lambda r: f"{pitching(r.totals)['era']:.2f}"),
                  ('pitcher', '탈삼진왕', lambda r: r.totals.get('so', 0), False, lambda r: f"{r.totals.get('so', 0)}탈삼진"),
                  ('pitcher', '승률왕', lambda r: pitching(r.totals)['wpct'], False,
                   lambda r: rate(pitching(r.totals)['wpct'])),
                  ('pitcher', '세이브왕', lambda r: r.totals.get('sv', 0), False, lambda r: f"{r.totals.get('sv', 0)}세이브"),
                  ('pitcher', '홀드왕', lambda r: r.totals.get('hld', 0), False, lambda r: f"{r.totals.get('hld', 0)}홀드")]
        for j, (role, label, key, needs_qual, shown) in enumerate(titles):
            pool = [r for r in (bats if role == 'batter' else pits)
                    if (not needs_qual or qualified(role, r.totals, tg))
                    and (label != '승률왕' or pitching(r.totals)['decisions'] >= 10)]
            pool = [r for r in pool if needs_qual or key(r) > 0]
            if pool:
                best = max(pool, key=key)
                give('title', label, best, shown(best), order=30 + j)
        fut = [r for r in stat_rows(s, 1, 'batter') + stat_rows(s, 1, 'pitcher')
               if qualified(r.role, r.totals, tg, AWARD_PA if r.role == 'batter' else AWARD_IP)]
        if fut:
            fm = max(fut, key=lambda r: r.war)
            give('futures', '퓨처스 MVP', fm, val(fm), order=50)
        RookieAward.objects.bulk_create(awards)
        s.closed, s.closed_at = True, timezone.now()
        s.save(update_fields=['closed', 'closed_at'])
        for a in awards:
            if a.player_id:
                R._log(a.player, 'award', f'시즌 {s.number} {a.label} 수상 — {a.value}')
    return awards


# ───────────────────────────── 화면용 묶음
def team_short(code: str) -> str:
    from . import rookie as R
    return R.TEAM.get(code, {}).get('name', code).split()[0]


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
    return {'no': g.no, 'day': g.day, 'league': LEAGUE.get(g.league, ''), 'me': team_short(my_team),
            'vs': vs, 'vs_label': vs_label(role, vs, g.line), 'vs_lvl': g.line.get('vs_lvl') or '',
            'vs_short': (vs_label(role, vs, g.line) if role == 'pitcher' or vs in ('setup', 'mop')
                         else GRADE_LABEL.get(vs, '')),
            'relief': bool(g.line.get('gr')), 'inn': g.line.get('inn'),
            'splits': [x for x in splits(role, g.line) if x['pa']] if role == 'pitcher' else [],
            'opp': team_short(g.opponent), 'opp_code': g.opponent, 'mine': g.team_runs, 'theirs': g.opp_runs,
            'win': g.team_runs > g.opp_runs, 'summary': g.summary, 'line': g.line, 'home': g.home,
            'ip': ip_text(g.line.get('outs', 0))}


def season_lines(stats, season=None) -> list:
    """시즌 기록 행들 → 화면용(리그 이름·규정 진행률 포함)."""
    out = []
    for r in stats:
        tg = team_games(season or r.season)
        need = (QUAL_IP if r.role == 'pitcher' else QUAL_PA) * tg
        have = r.totals.get('outs', 0) / 3 if r.role == 'pitcher' else r.totals.get('pa', 0)
        out.append({'s': r, 'v': line_view(r.role, r.totals), 'league': LEAGUE.get(r.league, ''),
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
        rows = list(RookieSeasonStat.objects.filter(season=season, player=p).select_related('season')
                    .order_by('-league'))
        lines = season_lines(rows, season)
    main = next((x for x in lines if x['s'].league == p.tier), lines[0] if lines else None)
    last_day = RookieGame.objects.filter(player=p).order_by('-day').values_list('day', flat=True).first()
    if p.role == 'pitcher' and p.lineup not in ('sp', ''):
        # 구원은 하루 한두 번 — 최근 등판 다섯 번을 보여 준다
        games = [game_view(g, p.team, p.role) for g in RookieGame.objects.filter(player=p).order_by('-day', '-no')[:5]]
    else:
        games = [game_view(g, p.team, p.role) for g in RookieGame.objects.filter(player=p, day=last_day).order_by('no')] \
            if last_day else []
    sim = season.simulated_through if season else None
    dnp = bool(sim and sim >= max(season.start, p.created_at.date()) and (not last_day or last_day < sim))
    trophies = list(RookieAward.objects.filter(player=p).select_related('season').order_by('-season__number', 'order'))
    league = (RookieGame.objects.filter(player=p, day=last_day).values_list('league', flat=True).first()
              if last_day else p.tier)
    return {'season': st, 'season_obj': season, 'lines': lines, 'main_line': main, 'games': games,
            'games_day': last_day, 'dnp': dnp, 'relief_log': bool(games and games[0]['relief'] and len(games) > 1), 'trophies': trophies, 'pos_label': POS_LABEL.get(p.position, ''),
            'opp_levels': opp_levels(league if league is not None else p.tier),
            'ladder': ladder_of(p)}


def ladder_of(p) -> dict:
    from .rookie_sim import role_ladder
    return role_ladder(p.role, p.lineup, p.slot, p.stats, p.ovr, LEVEL[p.tier])


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
