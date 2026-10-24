"""야구선수 키우기 — 경기 모형: 타석 승부, 상대 선수, 내 타순·보직, 경기 시뮬레이션(2026-10-17 개편).

타석 승부(pa_probs): 타자 능력(컨택·파워·선구안·주루·클러치) 대 투수 능력(구속·제구·변화구·멘탈)을
항목끼리 맞붙인다 — 컨택 대 구위(구속·변화구·멘탈), 선구안 대 제구·멘탈(평정심), 파워 대 구위·멘탈, 득점권에선 클러치 대 멘탈.
기울기 S=9 — 실력 차이가 결과에 크게 드러나게. 평균 타자 기준 타율: 에이스 상대 ≈ .198, 주전 ≈ .256, 백업 ≈ .313
(test_rookie_league 가 지킨다).

능력치 값 균등화(2026-10-18 점검): 예전엔 +5 의 시즌 WAR 가 컨택 0.97·파워 0.76 대 선구안 0.26·주루 0.20, 투수 멘탈 0·
체력 0.04 로 한쪽만 키우는 게 당연했다. 그래서 확률식을 '리그 평균 값 + K·(시그모이드−0.5)' 꼴로 바꿔 모든 능력이
리그 수준이면 예전과 같은 확률이 나오게 두고, 기울기(K)·구위 섞기(MIX)·수비 포지션 배율·주루의 수비 범위·
선발 피로(체력)·불펜 연투 피로(체력)를 다시 나눴다 — +5 값이 타자 0.50~0.57, 선발 0.41~0.46, 불펜 0.12~0.13(유격수 기준,
1루수는 수비 값이 절반, 지명타자 0). 기대값 계산(scratchpad ev.py)과 커리어 하네스로 맞췄다.

상대는 가상 선수(이름 없음 — 실존 선수를 흉내 내지 않는다):
- 상대 타선: 상위(1·2번 — 선구안·주루), 중심(3·4·5번 — 클러치 + 컨택·파워 중 둘), 하위(6~9번 — 밋밋)
- 상대 투수: 선발 에이스·주전·백업, 불펜 필승조·마무리 / 추격·패전조

내 타순(타자): 백업(대타·대주자·대수비) → 하위 타선 주전(6~9번) → 상위 타선 테이블세터(1·2번)
  / 중심 타선 교타자(3번)·거포(4·5번) / 5툴(3번, 어디든). 능력이 다음 계단 기준을 넘거나 최근 성적으로
  증명하면 한 계단 오르고, 능력이 기준보다 크게 떨어지거나 부진이 이어지면 한 계단 내려간다(매일 밤 경기 전).
내 보직(투수): 불펜형은 패전조 → 추격조 → 승리조 → 필승조 → 마무리(필승조·마무리는 멘탈도 필요),
  선발형(체력이 구위만큼 되는 투수)은 패전조(롱릴리프) → 선발 로테이션(구위에 따라 5~1선발).
"""
from __future__ import annotations

import math
from collections import Counter

S = 9.0                                   # 승부 기울기(능력 차이 → 확률). 작을수록 민감
BAT = ('contact', 'power', 'eye', 'speed', 'defense')
PIT = ('velocity', 'control', 'breaking', 'stamina', 'mental')
# 능력치마다 결과에 미치는 힘(기울기) — 리그 평균 값은 그대로, 시그모이드−0.5 에 곱한다
K_BB, K_SO_CON, K_SO_EYE, K_HR = .115, .11, .12, .06
K_BABIP_CON, K_BABIP_SPD, K_DOUBLE, K_TRIPLE = .063, .093, .06, .038
MIX_CON = (.41, .50, .09)                 # 컨택이 맞서는 구위 — 구속·변화구·멘탈
MIX_POW = (.45, .35, .03, .17)            # 파워가 맞서는 구위 — 구속·변화구·제구·멘탈
MIX_EYE = (.57, .43)                      # 선구안이 맞서는 것 — 제구·멘탈(평정심)
K_DEF = .128                              # 수비 기여(한 경기, 포지션 배율 곱)
DEF_POS = {'C': 1.2, 'SS': 1.2, '2B': 1.0, '3B': .9, 'OF': .9, '1B': .5}      # 지명타자는 수비가 없다
DEF_RANGE = {'SS': .165, '2B': .165, 'OF': .10, '3B': .08}                    # 수비 범위에 섞이는 주루 몫
K_STEAL = .173                            # 도루 시도(주루)
F_SP, LIM_SP = .64, .12                   # 선발 피로(리그 수준 대비 체력) · 체력이 늘리는 상대 타자 수
K_RP = .32                                # 불펜 연투 피로(리그 수준 대비 체력)
HIT_RATE = .96                            # 모든 타석의 안타(홈런 포함)를 상대 4% 낮춘다. 남는 확률은 범타로.


def _fatigue(k: float, lvl: float, stamina: float) -> float:
    """체력이 리그 수준보다 낮으면 구위가 깎이고(+), 높으면 버틴다(−). 멀어질수록 덜 늘어난다(다른 능력과 같은 모양)."""
    return k * 4 * S * (_sig((lvl - stamina) / S) - .5)


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _duel(gap: float) -> float:
    """12점까지 원래 차이, 그 이상은 완만하게 18점에 접근한다. 실력 순서는 유지한다.

    최상위 재능이 약한 리그에서 매년 0점대 ERA를 만드는 극단만 누른다.
    능력치·성장 한계는 바꾸지 않고 각 타석의 대결 차이에 적용한다.
    """
    if abs(gap) <= 12:
        return gap / S
    return math.copysign(12 + 6 * math.tanh((abs(gap) - 12) / 6), gap) / S


def _pick(probs: dict, rng) -> str:
    x, acc = rng.random() * sum(probs.values()), 0.0
    for k, v in probs.items():
        acc += v
        if x < acc:
            return k
    return 'OUT'


def _poisson(lam: float, rng) -> int:
    k, p, limit = 0, 1.0, math.exp(-max(lam, 0.0))
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _binom(n: int, p: float, rng) -> int:
    return sum(rng.random() < p for _ in range(n))


# ───────────────────────────── 타석 승부
def pa_probs(b: dict, p: dict, risp: bool = False) -> dict:
    from . import rookie_handedness as Hands
    b, p = Hands.matchup(b, p)
    g = lambda d, k: float(d.get(k, 25))  # noqa: E731
    con, pw, eye, spd = g(b, 'contact'), g(b, 'power'), g(b, 'eye'), g(b, 'speed')
    clutch = float(b.get('clutch', (con + eye) / 2))           # 내 타자는 클러치 능력치가 없다 → 컨택·선구안 평균
    vel, ctl, brk, men = g(p, 'velocity'), g(p, 'control'), g(p, 'breaking'), g(p, 'mental')
    d_con = _duel(con - (vel * MIX_CON[0] + brk * MIX_CON[1] + men * MIX_CON[2]))
    d_eye = _duel(eye - (ctl * MIX_EYE[0] + men * MIX_EYE[1]))
    d_pow = _duel(pw - (vel * MIX_POW[0] + brk * MIX_POW[1] + ctl * MIX_POW[2] + men * MIX_POW[3]))
    d_spd = _duel(spd - (vel + ctl + brk) / 3)
    bb = 0.075 + K_BB * (_sig(d_eye) - .5)
    so = 0.21 - K_SO_CON * (_sig(d_con) - .5) - K_SO_EYE * (_sig(d_eye) - .5)
    hbp = 0.008
    contact = 1 - bb - so - hbp
    hr = contact * (0.0485 + K_HR * (_sig(d_pow * 1.2) - .5))
    bip = contact - hr
    babip = 0.3125 + K_BABIP_CON * (_sig(d_con) - .5) + K_BABIP_SPD * (_sig(d_spd) - .5)
    if risp:                                                    # 득점권: 클러치 대 멘탈
        babip += 0.06 * (_sig(_duel(clutch - men)) - 0.5)
    hits = bip * babip
    d_share, t_share = 0.22 + K_DOUBLE * (_sig(d_pow) - .5), 0.021 + K_TRIPLE * (_sig(d_spd) - .5)
    out = {'BB': bb, 'HBP': hbp, 'SO': so, 'HR': hr, '2B': hits * d_share, '3B': hits * t_share,
           '1B': hits * (1 - d_share - t_share), 'OUT': bip - hits}
    for key in ('1B', '2B', '3B', 'HR'):
        removed = out[key] * (1 - HIT_RATE)
        out[key] -= removed
        out['OUT'] += removed
    return out


# ───────────────────────────── 상대 선수(리그 수준 + 보정)
# 상대 타순 1~9번 — 상위(출루·주루), 중심(클러치 + 컨택·파워), 하위(밋밋)
LINEUP_PROFILE = {
    1: {'contact': 6, 'power': -6, 'eye': 10, 'speed': 12, 'clutch': 0},
    2: {'contact': 8, 'power': -2, 'eye': 8, 'speed': 8, 'clutch': 2},
    3: {'contact': 12, 'power': 8, 'eye': 6, 'speed': 2, 'clutch': 10},
    4: {'contact': 6, 'power': 14, 'eye': 4, 'speed': -6, 'clutch': 12},
    5: {'contact': 8, 'power': 10, 'eye': 2, 'speed': -2, 'clutch': 8},
    6: {'contact': -4, 'power': -2, 'eye': -4, 'speed': -2, 'clutch': -4},
    7: {'contact': -6, 'power': -6, 'eye': -6, 'speed': -4, 'clutch': -6},
    8: {'contact': -8, 'power': -8, 'eye': -6, 'speed': -4, 'clutch': -8},
    9: {'contact': -9, 'power': -10, 'eye': -8, 'speed': 0, 'clutch': -8},
}
LINEUP_GROUP = {1: 'top', 2: 'top', 3: 'heart', 4: 'heart', 5: 'heart', 6: 'bottom', 7: 'bottom', 8: 'bottom', 9: 'bottom'}
LINEUP_FORMS = (('strong', '강타선', 4.0, 25), ('normal', '정상 라인업', 0.0, 50), ('weak', '백업 위주', -6.0, 25))
OPP_PITCHERS = {
    'ace': {'velocity': 12, 'control': 10, 'breaking': 12, 'stamina': 10, 'mental': 10},
    'reg': {'velocity': 0, 'control': 0, 'breaking': 0, 'stamina': 0, 'mental': 0},
    'bak': {'velocity': -8, 'control': -12, 'breaking': -10, 'stamina': -8, 'mental': -10},
    'setup': {'velocity': 10, 'control': 6, 'breaking': 8, 'stamina': -10, 'mental': 10},
    'mop': {'velocity': -6, 'control': -10, 'breaking': -8, 'stamina': -6, 'mental': -8},
}
STARTER_GRADES = (('ace', 20), ('reg', 55), ('bak', 25))
STARTER_PA = {'ace': 3, 'reg': 3, 'bak': 2}                 # 선발과 붙는 타석, 나머지는 불펜
SETUP_SHARE = 0.45                                          # 불펜 타석 중 필승조·마무리 비율

BAT_SPLITS = (('ace', '에이스 선발'), ('reg', '일반 선발'), ('bak', '대체 선발'),
              ('setup', '필승조·마무리'), ('mop', '추격·패전조'), ('member', '회원 투수'))
PIT_SPLITS = (('top', '상위 타선'), ('heart', '중심 타선'), ('bottom', '하위 타선'))
GRADE_LABEL = {'ace': '에이스', 'reg': '일반', 'bak': '대체', 'setup': '필승조', 'mop': '추격조'}
GROUP_NOTE = {'top': '출루·주루', 'heart': '클러치·장타', 'bottom': '밋밋'}


def opp_pitcher(kind: str, lvl: float, rng=None) -> dict:
    jitter = rng.gauss(0, 2) if rng else 0.0
    return dict({k: lvl + off + jitter for k, off in OPP_PITCHERS[kind].items()},
                _throwing='L' if kind in ('ace', 'mop') else 'R')


def opp_batter(slot: int, lvl: float) -> dict:
    return dict({k: lvl + off for k, off in LINEUP_PROFILE[slot].items()},
                _batting='L' if slot in (1, 3, 6) else 'R')


def opp_summary(lvl: float) -> dict:
    """화면 안내 — 상대 선발 등급별 구위, 상대 타선 구간별 대표 능력."""
    def stuff(kind):
        o = OPP_PITCHERS[kind]
        return round(lvl + (o['velocity'] + o['breaking'] + o['control']) / 3)

    def group(keys, slots):
        return round(lvl + sum(LINEUP_PROFILE[s][k] for s in slots for k in keys) / (len(keys) * len(slots)))
    return {'ace': stuff('ace'), 'reg': stuff('reg'), 'bak': stuff('bak'),
            'top': group(('eye', 'speed'), (1, 2)), 'heart': group(('clutch', 'contact', 'power'), (3, 4, 5)),
            'bottom': group(('contact', 'power', 'eye'), (6, 7, 8, 9))}


def _split(line, code: str, o: str):
    line[f'{code}_pa'] += 1
    if o in ('BB', 'HBP'):
        line[f'{code}_bb'] += 1
        return
    line[f'{code}_ab'] += 1
    if o in ('1B', '2B', '3B', 'HR'):
        line[f'{code}_h'] += 1
    if o == 'HR':
        line[f'{code}_hr'] += 1
    if o == 'SO':
        line[f'{code}_so'] += 1


# ───────────────────────────── 내 타순
BAT_ROLES = {
    'bench': '백업(대타·대주자)', 'lower': '하위 타선 주전', 'table': '테이블세터',
    'contact': '중심 타선 교타자', 'slugger': '중심 타선 거포', 'five': '5툴 플레이어',
}
BAT_STEP = {'bench': 0, 'lower': 1, 'table': 2, 'contact': 2, 'slugger': 2, 'five': 2}
SLOT_PA = {1: 4.65, 2: 4.55, 3: 4.45, 4: 4.35, 5: 4.25, 6: 4.1, 7: 4.0, 8: 3.9, 9: 3.8}
SLOT_ON = {1: (68, 24, 7, 1), 2: (55, 30, 12, 3), 3: (45, 33, 17, 5), 4: (45, 33, 17, 5), 5: (45, 33, 17, 5),
           6: (55, 30, 12, 3), 7: (55, 30, 12, 3), 8: (55, 30, 12, 3), 9: (58, 29, 11, 2), 0: (40, 35, 20, 5)}
SLOT_SCORE = {1: .38, 2: .36, 3: .30, 4: .28, 5: .28, 6: .27, 7: .26, 8: .25, 9: .27, 0: .30}


def _ops(lines) -> tuple[int, float]:
    pa = sum(x.get('pa', 0) for x in lines)
    ab = sum(x.get('ab', 0) for x in lines)
    h = sum(x.get('h', 0) for x in lines)
    tb = sum(x.get('h', 0) + x.get('d', 0) + 2 * x.get('t', 0) + 3 * x.get('hr', 0) for x in lines)
    on = h + sum(x.get('bb', 0) + x.get('hbp', 0) for x in lines)
    return pa, (on / pa if pa else 0) + (tb / ab if ab else 0)


def upper_fit(s: dict, lvl: float) -> tuple[str, int] | None:
    """상위·중심 타선에 들 만한 모양 — 5툴 > 거포 > 테이블세터 > 교타자. 없으면 None."""
    c, p, e, sp, d = (float(s.get(k, 25)) for k in BAT)
    if min(c, p, e, sp, d) >= lvl + 10:                         # 5툴 — 모든 능력이 에이스급
        return 'five', 3
    if p >= lvl + 4 and p >= max(e, sp):
        return 'slugger', 4 if p >= lvl + 10 else 5
    if (e + sp) / 2 >= lvl + 2:
        return 'table', 1 if sp >= e else 2
    if c >= lvl + 6:
        return 'contact', 3
    return None


def batter_role(cur: str, s: dict, ovr: float, lvl: float, recent: list) -> tuple[str, int, str]:
    """매일 밤 한 계단씩: (보직, 타순, 바뀐 이유 — 안 바뀌면 '')."""
    pa, ops = _ops(recent)
    cur = cur if cur in BAT_ROLES else 'bench'
    step = BAT_STEP[cur]
    fit = upper_fit(s, lvl)
    lower_slot = 6 if ovr >= lvl else 7 if ovr >= lvl - 3 else 8 if ovr >= lvl - 6 else 9
    if step == 0:
        if ovr >= lvl - 4 or (ovr >= lvl - 10 and pa >= 8 and ops >= .800):
            why = '능력이 올라와' if ovr >= lvl - 4 else f'최근 OPS {ops:.3f}로 증명해'
            return 'lower', lower_slot, f'{why} 하위 타선 주전({lower_slot}번)이 됐어요'
        return 'bench', 0, ''
    if step == 1:
        if ovr < lvl - 9 or (pa >= 25 and ops < .450):
            return 'bench', 0, '부진으로 백업(대타·대주자)으로 내려갔어요'
        proven = ovr >= lvl - 1 and pa >= 30 and ops >= .900
        if fit and (ovr >= lvl + 3 or proven):
            role, slot = fit
            return role, slot, f'{BAT_ROLES[role]}({slot}번)로 올라갔어요'
        return 'lower', lower_slot, ''
    # 상위·중심 타선
    if ovr < lvl - 1 or (pa >= 30 and ops < .550) or not fit:
        return 'lower', lower_slot, f'하위 타선({lower_slot}번)으로 내려갔어요'
    role, slot = fit
    return role, slot, (f'{BAT_ROLES[role]}({slot}번)로 자리를 옮겼어요' if role != cur else '')


# ───────────────────────────── 내 보직(투수)
PEN_LADDER = ('mop', 'chase', 'win', 'setup', 'closer')
PIT_ROLES = {'mop': '패전조', 'chase': '추격조', 'win': '중간계투', 'setup': '셋업맨', 'closer': '마무리', 'sp': '선발'}


def stuff_of(s: dict) -> float:
    g = lambda k: float(s.get(k, 25))  # noqa: E731
    return g('velocity') * .35 + g('breaking') * .30 + g('control') * .20 + g('mental') * .15


def starter_type(s: dict) -> bool:
    """체력이 구위만큼 되는 투수는 선발형."""
    return float(s.get('stamina', 25)) >= (float(s.get('velocity', 25)) + float(s.get('breaking', 25))) / 2 - 2


def pen_need(role: str, lvl: float) -> tuple[float, float]:
    """(구위 기준, 멘탈 기준) — 그 계단에 설 자격."""
    return {'mop': (-99, -99), 'chase': (lvl - 5, -99), 'win': (lvl, -99), 'setup': (lvl + 4, lvl),
            'closer': (lvl + 8, lvl + 6)}[role]


def rotation_rank(s: dict, lvl: float) -> int:
    st = stuff_of(s)
    return 1 if st >= lvl + 10 else 2 if st >= lvl + 5 else 3 if st >= lvl + 1 else 4 if st >= lvl - 1 else 5


def _era(lines) -> tuple[float, float]:
    outs = sum(x.get('outs', 0) for x in lines)
    er = sum(x.get('er', 0) for x in lines)
    ip = outs / 3
    return ip, (er * 9 / ip if ip else 0.0)


def pitcher_role(cur: str, s: dict, lvl: float, recent: list) -> tuple[str, int, str]:
    """매일 밤 한 계단씩: (보직, 선발 순번 — 불펜은 0, 바뀐 이유)."""
    ip, era = _era(recent)
    st, men = stuff_of(s), float(s.get('mental', 25))
    cur = cur if cur in PIT_ROLES else 'mop'
    if cur == 'sp':
        if float(s.get('stamina', 25)) < lvl - 6 or st < lvl - 6 or (ip >= 15 and era >= 6.5):
            return 'mop', 0, '선발에서 빠져 롱릴리프(패전조)로 내려갔어요'
        rank = rotation_rank(s, lvl)
        return 'sp', rank, ''
    if starter_type(s) and cur in ('mop', 'chase', 'win'):
        if st >= lvl - 2 and float(s.get('stamina', 25)) >= lvl - 2 and (ip < 6 or era <= 4.5):
            rank = rotation_rank(s, lvl)
            return 'sp', rank, f'선발 로테이션({rank}선발)에 들어갔어요'
    i = PEN_LADDER.index(cur)
    need_st, need_men = pen_need(cur, lvl)
    if i > 0 and (st < need_st - 4 or men < need_men - 4 or (ip >= 6 and era >= 7.0)):
        down = PEN_LADDER[i - 1]
        return down, 0, f'{PIT_ROLES[down]}으로 내려갔어요'
    if i + 1 < len(PEN_LADDER):
        nxt = PEN_LADDER[i + 1]
        n_st, n_men = pen_need(nxt, lvl)
        proven = ip >= 6 and era <= 3.0
        if men >= n_men and (st >= n_st or (proven and st >= n_st - 2)):
            why = f'최근 평균자책점 {era:.2f}로 증명해 ' if st < n_st else ''
            return nxt, 0, f'{why}{PIT_ROLES[nxt]}으로 올라갔어요'
    return cur, 0, ''


PITCH_MENU = ((30, '슬라이더'), (45, '커브'), (55, '체인지업'), (65, '포크'), (78, '커터'), (88, '스위퍼'))
STYLE = {'velocity': '파이어볼러', 'control': '제구형', 'breaking': '변화구형', 'stamina': '이닝이터', 'mental': '강심장'}


# 몸이 덜 자란 나이의 최고 구속 배율(2026-10-19 사용자 지적: 첫 경기도 전인 리틀야구 투수가 138km/h) —
# 어른 구속(128 + 구속 능력 × 0.3)에 곱한다. 열두 살 90km/h 안팎, 중학 100~120, 고교 125~145, 스물하나부터 어른과 같다.
SPEED_AGE = {12: .66, 13: .71, 14: .76, 15: .81, 16: .86, 17: .90, 18: .93, 19: .95, 20: .97}


def top_speed(vel: float, age: int | None = None) -> int:
    m = 1.0 if age is None else SPEED_AGE.get(age, 1.0 if age > max(SPEED_AGE) else SPEED_AGE[min(SPEED_AGE)])
    return round((128 + vel * 0.3) * m)


def pitch_profile(s: dict, age: int | None = None) -> dict:
    """구종과 스타일 — 화면 표시용. 최고 구속은 구속 능력과 나이에서, 구종 수는 변화구 능력에서."""
    vel, brk = float(s.get('velocity', 25)), float(s.get('breaking', 25))
    best = max(PIT, key=lambda k: float(s.get(k, 25)))
    return {'style': STYLE[best], 'top_speed': top_speed(vel, age),
            'pitches': ['직구'] + [name for need, name in PITCH_MENU if brk >= need]}


def bat_style(s: dict) -> str:
    c, p, e, sp, d = (float(s.get(k, 25)) for k in BAT)
    best = max(c, p, e, sp, d)
    if min(c, p, e, sp, d) >= best - 6:
        return '균형형'
    return {c: '교타자', p: '거포', e: '선구안형', sp: '호타준족', d: '수비형'}[best]


# ───────────────────────────── 경기 — 내 타자
def _runner(line, o, ds, rng):
    """출루 뒤 도루 시도."""
    if o in ('1B', 'BB', 'HBP') and rng.random() < 0.03 + K_STEAL * _sig(ds):
        if rng.random() < 0.55 + 0.35 * _sig(ds):
            line['sb'] += 1
        else:
            line['cs'] += 1


def _plate(line, s, pit, code, slot, ds, rng, cache, member_pa=None):
    if member_pa:
        code = 'member'
    on = rng.choices((0, 1, 2, 3), weights=SLOT_ON[slot])[0]
    risp = on >= 1 and rng.random() < 0.55
    key = (code, risp)
    if key not in cache:
        cache[key] = pa_probs(s, pit, risp=risp)
    o = member_pa['outcome'] if member_pa else _pick(cache[key], rng)
    _split(line, code, o)
    line['pa'] += 1
    if o in ('BB', 'HBP'):
        line['bb' if o == 'BB' else 'hbp'] += 1
        line['rbi'] += on == 3
    else:
        line['ab'] += 1
    if o == 'SO':
        line['so'] += 1
    elif o == 'OUT':
        if not member_pa and on > 0 and rng.random() < .07 and rng.random() < 2 / 3:
            line['rbi'] += 1
            if rng.random() < .55:
                line['sf'] += 1
                line['ab'] -= 1
                line[f'{code}_ab'] -= 1
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
    _runner(line, o, ds, rng)
    if o in ('1B', 'BB', 'HBP', '2B', '3B'):
        base = {'2B': .45, '3B': .7}.get(o, SLOT_SCORE[slot] + .08 * _sig(ds))
        line['r'] += rng.random() < base


def _defense(line, s, position, lvl, rng, share=1.0):
    from .rookie_league import ERR_BASE
    if position == 'DH':
        return
    rw = DEF_RANGE.get(position, 0.0)                         # 유격·2루·외야는 발도 수비 범위다
    d = (float(s.get('defense', 25)) * (1 - rw) + float(s.get('speed', 25)) * rw - lvl) / S
    de = (float(s.get('defense', 25)) - lvl) / S              # 실책은 수비 능력만
    err = rng.random() < ERR_BASE.get(position, .04) * (1.6 - _sig(de)) * share
    line['e'] += err
    line['def'] = round(((_sig(d) - 0.5) * 2 * K_DEF * DEF_POS.get(position, 1.0)
                         + 0.4 * (ERR_BASE.get(position, .04) * 1.1 - err)) * share, 4)


def _score(line, rng):
    team = line.get('rbi', 0) + _poisson(3.7, rng)
    opp = _poisson(4.3, rng)
    if team == opp:
        team, opp = (team + 1, opp) if rng.random() < 0.5 else (team, opp + 1)
    return team, opp


def batter_game(s: dict, position: str, lvl: float, rng, role: str = 'lower', slot: int = 7,
                member_pas=()) -> dict | None:
    """한 경기. 백업은 대타·대주자·대수비로만 나오고, 안 나오는 경기는 None."""
    from .rookie_league import bat_summary
    ds = (float(s.get('speed', 25)) - lvl) / S
    line = Counter(g=1)
    pen_kind = 'setup' if rng.random() < SETUP_SHARE else 'mop'
    pen = opp_pitcher(pen_kind, lvl, rng)
    cache = {}
    if role == 'bench':
        r = 0 if member_pas else rng.random()
        if r < 0.40:                                         # 대타 — 경기 후반 불펜과 한 타석
            line['ph'] += 1
            _plate(line, s, pen, pen_kind, 0, ds, rng, cache, member_pas[0] if member_pas else None)
            text = '대타 ' + bat_summary(line)
            line['vs'] = pen_kind
        elif r < 0.55:                                       # 대주자
            line['pr'] += 1
            _runner(line, '1B', ds + 1.0, rng)
            line['r'] += rng.random() < .40 + .10 * line['sb']
            text = '대주자' + (f" {line['sb']}도루" if line['sb'] else '') + (f" {line['r']}득점" if line['r'] else '')
        elif r < 0.68:                                       # 대수비
            line['dr'] += 1
            _defense(line, s, position, lvl, rng, share=0.35)
            text = '대수비 출장' + (' 실책 1' if line['e'] else '')
        else:
            return None
        team, opp = _score(line, rng)
        return {'line': dict(line, vs=line.get('vs', ''), vs_lvl=0, bslot=0), 'team_runs': team,
                'opp_runs': opp, 'summary': text}
    grade = rng.choices([g for g, _w in STARTER_GRADES], weights=[w for _g, w in STARTER_GRADES])[0]
    sp = opp_pitcher(grade, lvl, rng)
    n = max(len(member_pas), int(SLOT_PA[slot]) + (rng.random() < SLOT_PA[slot] % 1))
    for i in range(n):
        if i < STARTER_PA[grade]:
            _plate(line, s, sp, grade, slot, ds, rng, cache, member_pas[i] if i < len(member_pas) else None)
        else:
            _plate(line, s, pen, pen_kind, slot, ds, rng, cache, member_pas[i] if i < len(member_pas) else None)
    _defense(line, s, position, lvl, rng)
    team, opp = _score(line, rng)
    vs_lvl = round((sp['velocity'] + sp['breaking'] + sp['control']) / 3)
    return {'line': dict(line, vs=grade, vs_lvl=vs_lvl, bslot=slot), 'team_runs': team, 'opp_runs': opp,
            'summary': bat_summary(line)}


# ───────────────────────────── 경기 — 내 투수
def _pitch(t, s, lvl_base, rng, start_slot, max_outs, pull, lvl: float | None = None, member_pas=()):
    """상대 타순을 따라 던진다. pull(t, outs_inning) 이 True 면 내려온다. 다음 타순을 돌려준다.
    lvl 을 주면(선발) 리그 수준 대비 체력만큼 공을 던질수록 구위가 떨어지거나 버틴다."""
    bases = [False, False, False]
    outs_inning = 0
    slot = start_slot
    cache = {}
    tired = _fatigue(F_SP, lvl, float(s.get('stamina', 25))) if lvl is not None else 0.0
    while t['outs'] < max_outs:
        if t['bf'] >= len(member_pas) and pull(t, outs_inning):
            break
        risp = bool(bases[1] or bases[2])
        fat = int(round(tired * min(t['bf'], 30) / 25))
        key = (slot, risp, fat)
        if key not in cache:
            mine = s
            if fat:
                mine = dict(s, **{k: float(s.get(k, 25)) - fat for k in ('velocity', 'control', 'breaking')})
            cache[key] = pa_probs(opp_batter(slot, lvl_base), mine, risp=risp)
        member_pa = member_pas[t['bf']] if t['bf'] < len(member_pas) else None
        if member_pa:
            slot = member_pa['slot']
        o = member_pa['outcome'] if member_pa else _pick(cache[key], rng)
        _split(t, LINEUP_GROUP[slot], o)
        slot = slot % 9 + 1
        t['bf'] += 1
        t['np'] += {'SO': 5, 'BB': 5.5, 'HBP': 3}.get(o, 3.4)
        runs = 0
        if o == 'SO':
            t['so'] += 1
            t['outs'] += 1
            outs_inning += 1
        elif o == 'OUT':
            if not member_pa and bases[0] and outs_inning < 2 and rng.random() < 0.12:
                bases[0] = False
                t['outs'] += 2
                outs_inning += 2
            else:
                t['outs'] += 1
                outs_inning += 1
                if bases[2] and outs_inning < 3 and rng.random() < 0.35:
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
                first_scores = bool(bases[0]) and rng.random() < .4
                runs += bases[2] + bases[1] + first_scores
                bases = [False, True, bool(bases[0]) and not first_scores]
            else:
                scored2 = bases[1] and rng.random() < 0.6
                runs += bases[2] + scored2
                bases = [True, bases[0], bool(bases[1]) and not scored2]
        if runs:
            t['r'] += runs
            t['er'] += sum(rng.random() >= 0.06 for _ in range(runs))
        if outs_inning >= 3:
            outs_inning = 0
            bases = [False, False, False]
    t['np'] = int(round(t['np']))
    return slot


def _form(lvl, rng):
    key, _label, off, _w = rng.choices(LINEUP_FORMS, weights=[f[3] for f in LINEUP_FORMS])[0]
    return key, lvl + off + rng.gauss(0, 2)


def starter_game(s: dict, lvl: float, rng, member_pas=()) -> dict:
    from .rookie_league import pit_summary
    form, base = _form(lvl, rng)
    limit = 26.08 + LIM_SP * (float(s.get('stamina', 25)) - 64) + rng.gauss(0, 3)   # 상대 타자 수(체력 64 ≈ 6이닝)
    t = Counter(g=1, gs=1)

    def pull(t, outs_inning):
        if outs_inning == 0 and t['outs'] and (t['bf'] >= limit or t['r'] >= 5):
            return True
        return t['r'] >= 7 or t['bf'] >= limit + 6
    _pitch(t, s, base, rng, 1, 27, pull, lvl=lvl, member_pas=member_pas)
    pen = _poisson(0.47 * (27 - t['outs']) / 3, rng)
    opp_runs, team = t['r'] + pen, _poisson(4.1, rng)
    if team == opp_runs:
        team, opp_runs = (team + 1, opp_runs) if rng.random() < 0.5 else (team, opp_runs + 1)
    margin = team - t['r']                                                 # 내려올 때 리드(근사)
    if team > opp_runs and t['outs'] >= 15 and margin > 0:
        if not (margin <= 2 and rng.random() < 0.3):                       # 근소한 리드는 불펜이 날리기도 한다
            t['w'] = 1
    elif team < opp_runs and t['r'] >= team and t['r']:
        t['l'] = 1
    t['qs'] = int(t['outs'] >= 18 and t['er'] <= 3)
    t['cg'] = int(t['outs'] >= 27)
    t['sho'] = int(t['cg'] and t['r'] == 0)
    return {'line': dict(t, vs=form, vs_lvl=round(base), lead=0, inn=1), 'team_runs': team, 'opp_runs': opp_runs,
            'summary': pit_summary(t)}


RELIEF = {   # 보직: (경기당 등판 확률, 이닝 수, 등판 이닝, 점수 차 범위 — 음수는 뒤진 상황)
    'mop': (0.30, 2, 6, (-7, -4)),
    'chase': (0.32, 1, 7, (-3, -1)),
    'win': (0.36, 1, 7, (2, 4)),
    'setup': (0.38, 1, 8, (1, 3)),
    'closer': (0.34, 1, 9, (1, 3)),
}
RELIEF_PER_DAY = 2


def relief_game(s: dict, lvl: float, rng, role: str, member_pas=()) -> dict:
    """구원 등판 한 번 — 세이브·홀드·블론 세이브·구원승·패."""
    from .rookie_league import ip_text
    _p, innings, inn, (lo, hi) = RELIEF[role]
    tired = _fatigue(K_RP, lvl, float(s.get('stamina', 25)))   # 연투 피로 — 체력이 낮으면 구위가 깎인다
    if tired:
        s = dict(s, **{k: float(s.get(k, 25)) - tired for k in ('velocity', 'control', 'breaking')})
    form, base = _form(lvl, rng)
    lead = rng.randint(lo, hi)
    t = Counter(g=1, gr=1)

    def pull(t, outs_inning):
        return t['r'] >= 4 or t['bf'] >= 3 * innings + 7
    _pitch(t, s, base, rng, rng.randint(1, 9), 3 * innings, pull, member_pas=member_pas)
    opp_at = _poisson(2.8 if lead > 0 else 4.4, rng)
    if lead < 0:
        opp_at = max(opp_at, -lead + rng.randint(0, 2))      # 뒤진 점수 차가 화면 표시와 맞게(0점 아래로 자르지 않게)
    team_at = opp_at + lead
    opp_runs = opp_at + t['r'] + (_poisson(0.25, rng) if role != 'closer' else 0)
    team_runs = team_at + (_poisson(0.35, rng) if role != 'closer' else 0)
    dec = ''
    if lead > 0:
        if t['r'] >= lead:
            if lead <= 3:
                t['bs'] = 1
                dec = '블론 세이브'
            if team_runs == opp_runs:
                team_runs, opp_runs = (team_runs + 1, opp_runs) if rng.random() < 0.5 else (team_runs, opp_runs + 1)
            if team_runs < opp_runs and t['r'] > lead:
                t['l'] = 1
                dec = '패'
        elif role == 'closer':
            t['sv'] = 1
            dec = '세이브'
        elif lead <= 3:
            t['hld'] = 1
            dec = '홀드'
    elif role == 'chase' and t['r'] == 0 and rng.random() < 0.18:
        team_runs = opp_runs + rng.randint(1, 2)               # 막는 사이 동점·역전 → 구원승
        t['w'] = 1
        dec = '구원승'
    if team_runs == opp_runs:
        team_runs, opp_runs = (team_runs + 1, opp_runs) if rng.random() < 0.5 else (team_runs, opp_runs + 1)
    summary = (f"{inn}회 등판 {ip_text(t['outs'])}이닝 {t['h']}피안타 {t['r']}실점 {t['so']}탈삼진"
               + (f' ({dec})' if dec else ''))
    return {'line': dict(t, vs=form, vs_lvl=round(base), lead=lead, inn=inn), 'team_runs': team_runs,
            'opp_runs': opp_runs, 'summary': summary}


# ───────────────────────────── 계단 안내(화면)
def role_ladder(role: str, lineup: str, slot: int, s: dict, ovr: float, lvl: float, age: int | None = None) -> dict:
    """지금 계단·다음 계단 조건 — 내 선수 화면의 '타순·보직' 칸."""
    L = round(lvl)
    if role == 'batter':
        cur = lineup if lineup in BAT_ROLES else 'bench'
        step = BAT_STEP[cur]
        steps = [('bench', '백업'), ('lower', '하위 타선'), ('upper', '상위·중심 타선')]
        fit = upper_fit(s, lvl)
        if step == 0:
            hint = f'OVR {L - 4} 이상이 되거나, 최근 10일 8타석 이상 OPS .800으로 증명하면 하위 타선 주전'
        elif step == 1:
            hint = (f'OVR {L + 3} 이상 + 모양이 맞으면 한 계단 위: 테이블세터(선구안·주루 평균 {L + 2}), '
                    f'거포(파워 {L + 4}), 교타자(컨택 {L + 6}), 5툴(모든 능력 {L + 10}). '
                    f"최근 30타석 OPS .900이면 OVR {L - 1}부터" + (f' — 지금 맞는 자리: {BAT_ROLES[fit[0]]}' if fit else ''))
        else:
            hint = f'자리 지키기: OVR {L - 1} 이상, 최근 30타석 OPS .550 이상'
        label = BAT_ROLES[cur] if cur == 'bench' else f'{slot}번 {BAT_ROLES[cur]}'
        return {'steps': [{'label': lab, 'state': 'done' if i < step else 'cur' if i == step else 'next'}
                          for i, (_k, lab) in enumerate(steps)], 'label': label, 'hint': hint,
                'style': bat_style(s)}
    st = round(stuff_of(s))
    prof = pitch_profile(s, age)
    if lineup == 'sp':
        hint = f'선발 자리 지키기: 체력·구위 {L - 6} 이상, 최근 15이닝 평균자책점 6.50 미만. 구위 {L + 10}이면 1선발'
        steps = [{'label': '롱릴리프', 'state': 'done'}, {'label': f'{slot}선발', 'state': 'cur'}]
        return {'steps': steps, 'label': f'{slot}선발', 'hint': hint, 'stuff': st, **prof}
    cur = lineup if lineup in PEN_LADDER else 'mop'
    i = PEN_LADDER.index(cur)
    if i + 1 < len(PEN_LADDER):
        nxt = PEN_LADDER[i + 1]
        n_st, n_men = pen_need(nxt, lvl)
        hint = (f'{PIT_ROLES[nxt]}: 구위 {round(n_st)} 이상' + (f', 멘탈 {round(n_men)} 이상' if n_men > -99 else '')
                + f'. 최근 6이닝 평균자책점 3.00 이하면 구위 {round(n_st) - 2}부터')
    else:
        hint = f'마무리 지키기: 구위 {L + 4}·멘탈 {L + 2} 이상, 최근 6이닝 평균자책점 7.00 미만'
    if starter_type(s) and cur in ('mop', 'chase', 'win'):
        hint += f'. 선발형 — 구위·체력 {L - 2} 이상이면 선발 로테이션'
    return {'steps': [{'label': PIT_ROLES[k], 'state': 'done' if j < i else 'cur' if j == i else 'next'}
                      for j, k in enumerate(PEN_LADDER)], 'label': PIT_ROLES[cur], 'hint': hint, 'stuff': st,
            **prof}
