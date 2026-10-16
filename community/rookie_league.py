"""야구선수 키우기 — 리그(시즌·경기·기록·시상). 성장 규칙은 rookie.py.

시즌: 2026-10-19(월) 개막, 4주(28일)에 144경기 — 하루 5~6경기, KBO 한 시즌 분량.
매일 밤 rookie_daily 가 전날 경기를 시뮬레이션하고(advance), 시즌 마지막 날 다음 정산에서 시상한다(close_season).
- 출전: 경기일 포함 최근 3일 안에 활동(TP 획득)이 있어야 엔트리에 든다. 쉬면 결장 → 규정타석·이닝을 못 채운다.
- 리그는 소속 그대로: 1군 · 퓨처스(2군) · 3군(육성군 연습경기). 기록은 리그별로 따로 쌓는다.
- 타자는 그날 모든 경기에, 투수는 선발 로테이션으로 하루 한 경기에 나간다(시즌 ≈ 28선발 170이닝).

경기 모형: 타석마다 볼넷·사구·삼진·인플레이를 '내 능력치 − 그 타석 상대의 능력'으로 정하고(로지스틱),
인플레이는 홈런율·BABIP·장타 비율로 나눈다. 같은 수준끼리면 리그 평균 ≈ .267/.325/.435,
평균자책점 ≈ 3.9 — test_rookie_league 가 몬테카를로로 지킨다. 투수는 주자 상황을 따라가며 실점을 센다.

상대 선수 등급(2026-10-17): 상대는 '리그 평균 ± 무작위'가 아니라 누구인지가 분명하다.
- 타자가 만나는 상대 선발 = 에이스(리그 수준 +12, 20%) · 주전(±0, 55%) · 백업(−10, 25%).
  선발과 3타석(백업 선발은 일찍 내려가 2타석), 나머지는 불펜(리그 수준).
- 투수가 만나는 상대 타순 = 3·4·5번 중심타자(+12) · 1·2·6번 주전(±0) · 7·8·9번 백업(−10),
  경기마다 라인업 형태가 바뀐다(강타선 +4 · 정상 · 백업 위주 −6).
- 가중 평균이 리그 수준과 같아 리그 평균 보정(LG_WOBA·FIP_C)은 그대로다. 경기마다 상대 등급을 남기고,
  시즌 기록에 상대 등급별 성적(<등급>_pa·ab·h·hr·bb·so)을 따로 쌓는다.

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
POS_LABEL = dict(POSITIONS, SP='선발투수')
POS_ADJ = {'C': 12.0, 'SS': 7.0, '2B': 3.0, '3B': 2.0, 'OF': -2.0, '1B': -10.0, 'DH': -15.0}   # 144경기 기준 점수
ERR_BASE = {'C': .03, '1B': .03, '2B': .05, '3B': .07, 'SS': .08, 'OF': .03}

OPP_OFFSET = {'ace': 12.0, 'reg': 0.0, 'bak': -10.0, 'pen': 0.0}           # 상대 능력 = 리그 수준 + 보정
STARTER_GRADES = (('ace', 20), ('reg', 55), ('bak', 25))                    # 상대 선발 등급과 확률(%)
STARTER_PA = {'ace': 3, 'reg': 3, 'bak': 2}                                 # 선발과 붙는 타석, 나머지는 불펜
LINEUP = ('reg', 'reg', 'ace', 'ace', 'ace', 'reg', 'bak', 'bak', 'bak')    # 상대 타순 1~9번의 등급
LINEUP_FORMS = (('strong', '강타선', 4.0, 25), ('normal', '정상 라인업', 0.0, 50), ('weak', '백업 위주', -6.0, 25))
GRADE_LABEL = {'ace': '에이스', 'reg': '주전', 'bak': '백업', 'pen': '불펜'}
BAT_SPLITS = (('ace', '에이스 선발'), ('reg', '주전 선발'), ('bak', '백업 선발'), ('pen', '불펜'))
PIT_SPLITS = (('ace', '중심타자'), ('reg', '주전 타자'), ('bak', '백업 타자'))
META_KEYS = ('vs', 'vs_lvl')                                                # 경기 줄의 설명 값 — 시즌 누적에서 뺀다

BAT_KEYS = ('g', 'pa', 'ab', 'h', 'd', 't', 'hr', 'rbi', 'r', 'bb', 'hbp', 'so', 'sb', 'cs', 'e', 'def')
PIT_KEYS = ('g', 'gs', 'w', 'l', 'qs', 'cg', 'sho', 'outs', 'h', 'r', 'er', 'bb', 'hbp', 'so', 'hr', 'bf', 'np')
LG_WOBA, WOBA_SCALE, FIP_C, REPL_FIP = 0.335, 1.20, 2.85, 4.90   # 몬테카를로로 맞춘 리그 평균


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


# ───────────────────────────── 확률 모형
def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def batter_probs(s: dict, lvl: float) -> dict:
    c, p, e, sp = (float(s.get(k, 25)) for k in ('contact', 'power', 'eye', 'speed'))
    dc, dp, de, ds = ((v - lvl) / 12 for v in (c, p, e, sp))
    bb = 0.035 + 0.075 * _sig(de)
    so = 0.31 - 0.17 * _sig(dc) - 0.04 * _sig(de)
    hbp = 0.008
    contact = 1 - bb - so - hbp
    hr = contact * (0.008 + 0.075 * _sig(dp * 1.2))
    bip = contact - hr
    hits = bip * (0.255 + 0.09 * _sig(dc) + 0.02 * _sig(ds))
    d_share, t_share = 0.17 + 0.10 * _sig(dp), 0.008 + 0.03 * _sig(ds)
    return {'BB': bb, 'HBP': hbp, 'SO': so, 'HR': hr, '2B': hits * d_share, '3B': hits * t_share,
            '1B': hits * (1 - d_share - t_share), 'OUT': bip - hits}


def pitcher_probs(s: dict, lvl: float, risp: bool = False) -> dict:
    v, ctl, br, m = (float(s.get(k, 25)) for k in ('velocity', 'control', 'breaking', 'mental'))
    dk, dc, dq = ((v + br) / 2 - lvl) / 12, (ctl - lvl) / 12, ((v + br + ctl) / 3 - lvl) / 12
    so = 0.13 + 0.15 * _sig(dk)
    bb = 0.115 - 0.085 * _sig(dc)
    hbp = 0.008
    contact = 1 - so - bb - hbp
    hr = contact * (0.07 - 0.05 * _sig(dq))
    bip = contact - hr
    babip = 0.345 - 0.07 * _sig(dq)
    if risp:                                   # 득점권에서는 멘탈이 안타를 막는다
        babip -= 0.04 * (_sig((m - lvl) / 12) - 0.5)
    hits = bip * babip
    return {'BB': bb, 'HBP': hbp, 'SO': so, 'HR': hr, '2B': hits * 0.2, '3B': hits * 0.02, '1B': hits * 0.78,
            'OUT': bip - hits}


def _pick(probs: dict, rng) -> str:
    x, acc = rng.random() * sum(probs.values()), 0.0
    for k, v in probs.items():
        acc += v
        if x < acc:
            return k
    return 'OUT'


def _poisson(lam: float, rng) -> int:
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _binom(n: int, p: float, rng) -> int:
    return sum(rng.random() < p for _ in range(n))


# ───────────────────────────── 경기 시뮬레이션
def _split(line, grade: str, o: str):
    """상대 등급별 누적 — 타석·타수·안타·홈런·볼넷(사구 포함)·삼진."""
    line[f'{grade}_pa'] += 1
    if o in ('BB', 'HBP'):
        line[f'{grade}_bb'] += 1
        return
    line[f'{grade}_ab'] += 1
    if o in ('1B', '2B', '3B', 'HR'):
        line[f'{grade}_h'] += 1
    if o == 'HR':
        line[f'{grade}_hr'] += 1
    if o == 'SO':
        line[f'{grade}_so'] += 1


def opp_levels(league: int) -> dict:
    """리그별 상대 등급의 능력 수치 — 화면 안내용."""
    return {g: round(LEVEL[league] + off) for g, off in OPP_OFFSET.items() if g != 'pen'}


def batter_game(s: dict, position: str, lvl: float, rng) -> dict:
    grade = rng.choices([g for g, _w in STARTER_GRADES], weights=[w for _g, w in STARTER_GRADES])[0]
    starter = lvl + OPP_OFFSET[grade] + rng.gauss(0, 2)
    pen = lvl + rng.gauss(0, 2)
    probs = {'sp': batter_probs(s, starter), 'pen': batter_probs(s, pen)}
    line = Counter(g=1)
    for i in range(4 if rng.random() < 0.6 else 5):
        who = grade if i < STARTER_PA[grade] else 'pen'
        opp = pen if who == 'pen' else starter
        ds = (float(s.get('speed', 25)) - opp) / 10
        o = _pick(probs['pen' if who == 'pen' else 'sp'], rng)
        _split(line, who, o)
        on = rng.choices((0, 1, 2, 3), weights=(55, 30, 12, 3))[0]        # 그 타석의 주자 수
        line['pa'] += 1
        if o in ('BB', 'HBP'):
            line['bb' if o == 'BB' else 'hbp'] += 1
            line['rbi'] += on == 3
        else:
            line['ab'] += 1
        if o == 'SO':
            line['so'] += 1
        elif o == 'OUT':
            line['rbi'] += on > 0 and rng.random() < 0.07
        elif o == 'HR':
            line['h'] += 1
            line['hr'] += 1
            line['rbi'] += on + 1
            line['r'] += 1
        elif o in ('1B', '2B', '3B'):
            line['h'] += 1
            if o == '2B':
                line['d'] += 1
            elif o == '3B':
                line['t'] += 1
            line['rbi'] += _binom(on, {'1B': .35, '2B': .6, '3B': .95}[o], rng)
        if o in ('1B', 'BB', 'HBP'):
            if rng.random() < 0.03 + 0.20 * _sig(ds):                     # 도루 시도
                if rng.random() < 0.55 + 0.35 * _sig(ds):
                    line['sb'] += 1
                else:
                    line['cs'] += 1
        if o in ('1B', 'BB', 'HBP', '2B', '3B'):
            score = {'2B': .45, '3B': .7}.get(o, .30 + .08 * _sig(ds))
            line['r'] += rng.random() < score
    if position != 'DH':
        d = (float(s.get('defense', 25)) - lvl) / 12
        line['e'] += rng.random() < ERR_BASE.get(position, .04) * (1.6 - _sig(d))
        # 수비 득점(경기당): 수비 능력(144경기 ≈ ±10점) + 실책을 평균보다 덜 하면 더한다(실책 1개 = 0.4점)
        line['def'] = round((_sig(d) - 0.5) * 2 * 0.07 + 0.4 * (ERR_BASE.get(position, .04) * 1.1 - line['e']), 4)
    team = line['rbi'] + _poisson(3.7, rng)
    opp_runs = _poisson(4.3, rng)
    if team == opp_runs:
        team, opp_runs = (team + 1, opp_runs) if rng.random() < 0.5 else (team, opp_runs + 1)
    out = dict(line, vs=grade, vs_lvl=round(starter))
    return {'line': out, 'team_runs': team, 'opp_runs': opp_runs, 'summary': bat_summary(line)}


def pitcher_game(s: dict, lvl: float, rng) -> dict:
    form, _label, form_off, _w = rng.choices(LINEUP_FORMS, weights=[f[3] for f in LINEUP_FORMS])[0]
    base = lvl + form_off + rng.gauss(0, 2)                               # 오늘 상대 라인업의 바탕 수준
    cache = {}

    def probs_for(grade, risp):
        if (grade, risp) not in cache:
            cache[(grade, risp)] = pitcher_probs(s, base + OPP_OFFSET[grade], risp=risp)
        return cache[(grade, risp)]

    limit = 12 + 0.22 * float(s.get('stamina', 25)) + rng.gauss(0, 3)     # 상대 타자 수(체력 64 ≈ 6이닝)
    t = Counter(g=1, gs=1)
    bases = [False, False, False]
    outs_inning = 0
    while t['outs'] < 27:
        if outs_inning == 0 and t['outs'] and (t['bf'] >= limit or t['r'] >= 5):
            break                                                         # 이닝 시작 때 교체
        if t['r'] >= 7 or t['bf'] >= limit + 6:
            break                                                         # 이닝 중 강판
        grade = LINEUP[t['bf'] % 9]                                       # 1번 타자부터 차례로
        o = _pick(probs_for(grade, bool(bases[1] or bases[2])), rng)
        _split(t, grade, o)
        t['bf'] += 1
        t['np'] += {'SO': 5, 'BB': 5.5, 'HBP': 3}.get(o, 3.4)
        runs = 0
        if o == 'SO':
            t['so'] += 1
            t['outs'] += 1
            outs_inning += 1
        elif o == 'OUT':
            if bases[0] and outs_inning < 2 and rng.random() < 0.12:     # 병살
                bases[0] = False
                t['outs'] += 2
                outs_inning += 2
            else:
                t['outs'] += 1
                outs_inning += 1
                if bases[2] and outs_inning < 3 and rng.random() < 0.35:  # 희생플라이·땅볼 득점
                    bases[2] = False
                    runs += 1
        elif o in ('BB', 'HBP'):
            t['bb' if o == 'BB' else 'hbp'] += 1
            if all(bases):
                runs += 1
            elif bases[0] and bases[1]:
                bases[2] = True
            elif bases[0]:
                bases[1] = True
            bases[0] = True
        else:
            t['h'] += 1
            if o == 'HR':
                t['hr'] += 1
                runs += 1 + sum(bases)
                bases = [False, False, False]
            elif o == '3B':
                runs += sum(bases)
                bases = [False, False, True]
            elif o == '2B':
                runs += bases[2] + bases[1] + (bases[0] and rng.random() < 0.4)
                bases = [False, True, bool(bases[0]) and rng.random() >= 0.4]
            else:
                scored2 = bases[1] and rng.random() < 0.6
                runs += bases[2] + scored2
                bases = [True, bases[0], bool(bases[1]) and not scored2]
        if runs:
            t['r'] += runs
            t['er'] += sum(rng.random() >= 0.06 for _ in range(runs))    # 6% 는 실책으로 비자책
        if outs_inning >= 3:
            outs_inning = 0
            bases = [False, False, False]
    t['np'] = int(round(t['np']))
    pen = _poisson(0.47 * (27 - t['outs']) / 3, rng)
    opp_runs, team = t['r'] + pen, _poisson(4.1, rng)
    if team == opp_runs:
        team, opp_runs = (team + 1, opp_runs) if rng.random() < 0.5 else (team, opp_runs + 1)
    if team > opp_runs and t['outs'] >= 15 and team > t['r']:
        t['w'] = 1
    elif team < opp_runs and t['r'] >= team and t['r']:
        t['l'] = 1
    t['qs'] = int(t['outs'] >= 18 and t['er'] <= 3)
    t['cg'] = int(t['outs'] >= 27)
    t['sho'] = int(t['cg'] and t['r'] == 0)
    out = dict(t, vs=form, vs_lvl=round(base))
    return {'line': out, 'team_runs': team, 'opp_runs': opp_runs, 'summary': pit_summary(t)}


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
    """상대 등급별 성적 — 타자는 상대 선발 등급·불펜, 투수는 상대 타자 등급. 투수의 타율은 피안타율."""
    rows = []
    for code, label in (PIT_SPLITS if role == 'pitcher' else BAT_SPLITS):
        g = {k: t.get(f'{code}_{k}', 0) for k in ('pa', 'ab', 'h', 'hr', 'bb', 'so')}
        rows.append(dict(g, code=code, label=label,
                         avg_text=rate(g['h'] / g['ab']) if g['ab'] else '-',
                         obp_text=rate((g['h'] + g['bb']) / g['pa']) if g['pa'] else '-',
                         level=round(LEVEL[league] + OPP_OFFSET[code]) if league is not None else None))
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
            stat, _ = RookieSeasonStat.objects.get_or_create(
                season=s, player=p, league=league,
                defaults={'user': p.user, 'name': p.name, 'number': p.number, 'team': p.team, 'role': p.role,
                          'position': p.position})
            games = []
            slots = nos if p.role == 'batter' else nos[p.pk % len(nos):][:1]
            for no in slots:
                r = (pitcher_game(p.stats, lvl, rng) if p.role == 'pitcher'
                     else batter_game(p.stats, p.position or 'DH', lvl, rng))
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
               ('whip', 'WHIP', True, 'whip_text'), ('ip', '이닝', False, 'ip_text'), ('war', 'WAR', False, 'war')]
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
           ('pitcher', 'ip', '시즌 최다 이닝', False, 'ip_text'), ('pitcher', 'qs', '시즌 최다 QS', False, 'qs')]


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
                   lambda r: rate(pitching(r.totals)['wpct']))]
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


def vs_label(role: str, vs: str) -> str:
    if role == 'pitcher':
        return next((label for key, label, _o, _w in LINEUP_FORMS if key == vs), '')
    return f"{GRADE_LABEL[vs]} 선발" if vs in GRADE_LABEL else ''


def game_view(g, my_team: str, role: str = 'batter') -> dict:
    vs = g.line.get('vs', '')
    return {'no': g.no, 'day': g.day, 'league': LEAGUE.get(g.league, ''), 'me': team_short(my_team),
            'vs': vs, 'vs_label': vs_label(role, vs), 'vs_lvl': g.line.get('vs_lvl'),
            'vs_short': GRADE_LABEL.get(vs, '') if role != 'pitcher' else vs_label(role, vs),
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
    games = [game_view(g, p.team, p.role) for g in RookieGame.objects.filter(player=p, day=last_day).order_by('no')] \
        if last_day else []
    sim = season.simulated_through if season else None
    dnp = bool(sim and sim >= max(season.start, p.created_at.date()) and (not last_day or last_day < sim))
    trophies = list(RookieAward.objects.filter(player=p).select_related('season').order_by('-season__number', 'order'))
    league = (RookieGame.objects.filter(player=p, day=last_day).values_list('league', flat=True).first()
              if last_day else p.tier)
    return {'season': st, 'season_obj': season, 'lines': lines, 'main_line': main, 'games': games,
            'games_day': last_day, 'dnp': dnp, 'trophies': trophies, 'pos_label': POS_LABEL.get(p.position, ''),
            'opp_levels': opp_levels(league if league is not None else p.tier)}


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
