"""야구선수 키우기 — 선수 일생: 학년·진학·드래프트·해외 진출·나이·잠재력·숨은 특성·은퇴(2026-10-17 사용자 요청).

흐름(리그 사다리는 rookie_world):
  리틀야구(초6) → 중학교(1~3) → 고등학교(1~3) → 드래프트 ─ 지명·계약 → KBO 육성군·퓨처스 → 1군
                                                    ├ 거절 → 대학(1~4학년, 졸업 때 다시 드래프트)
                                                    └ 거절 → 해외: 미국 싱글A~메이저리그 · 일본 NPB 2군~1군 · 대만 CPBL
- 학년: 리틀·중·고 한 학년 = 7일, 대학 한 학년 = 30일(프로 한 시즌과 같은 시계 — 2026-10-18 감사: 7일이면 대학이
  나이 한계를 4배 빨리 푸는 지름길이 됐다). 졸업 학년에는 희망 학교를 고르고(진학 지원), 학년이 끝나는 날 합격이 갈린다.
  합격 확률은 같은 나이 가상 동기 집단(CLASS) 안에서의 위치와 활약으로 오르고, 전통 강호는 문이 좁다.
  고르지 않았거나 떨어지면 우리 지역(목록에 없으면 가까운 지역) 학교로 간다.
- 드래프트: 고3·대4 학년이 끝나는 날 선수마다. 평가 점수(평균 50) = 스카우트가 본 잠재력(고졸 35%·대졸 25%, 오차 있음)
  + 동기 집단 대비 OVR + 활약 + 강호 학교 → DRAFT_ROUNDS 구간(ZenGM 의 나이별 잠재력·현재 능력 가중, 파워프로 석세스의
  평가치 구간을 참고). 잘할수록 희망 구단 확률이 오른다(10% → 최대 65%). 해외 제안은 상위층에만, 보통 한 나라.
  결정은 사흘 안에 — 안 고르면 지명 구단과 계약(미지명이면 희망 구단 육성선수). 지명 순위만큼 계약 보너스 TP.
- 나이: 학생은 학년마다 한 살, 프로는 시즌 개막마다 한 살. 마흔다섯이 되는 시즌 개막에 은퇴한다.
- 성장 한계: 잠재력(숨김, 고교 때부터 스카우트 별점) × 나이 비율(AGE_RATIO, 25세부터 1) — 주특기는 FOCUS_ROOM 더.
  한계 6 앞부터 훈련·경기 경험 효과가 줄고, 한계에 닿으면 멈춘다. 훈련 효율(AGE_EFF)은 몸이 덜 자란 학생일수록 낮아
  활동량에 따라 수렴점이 갈린다(출석만과 하루 한도의 차이가 학생 때도 남게). 서른하나부터 몸(구속·체력·파워·주루)이
  해마다 더 빨리 빠진다(파워프로 보통형 31세, FanGraphs 투수 구속 29세~).
- 프로 승격: 위 리그 수준 − 1 + 지금 리그 최소 체류(MIN_STAY 14일, 대졸 7일) + 최근 14일 성적 과제(PROMO_MISSION)
  — 고졸 신인이 며칠 만에 1군에 오르지 않게(파워프로 마이라이프의 2군 미션, 현실 마이너 단계당 약 1년).
- 경기 경험: 출전해서 친 안타·볼넷·도루, 잡은 아웃·삼진이 관련 능력을 조금씩 올린다(game_xp) — 주전일수록 빨리 큰다.
- 숨은 특성: 입단 때 0~2개(TRAITS). 효과가 처음 드러날 때 '숨은 특성 발견'으로 알려 준다.
킥루(축구 선수 키우기)의 공개 가이드에서 뼈대(잠재력 상한·나이·출전·숨은 특성·은퇴 유산)만 참고했다 — 코드·화면은 가져오지 않았다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from . import rookie_world as W
from . import rookie_story as Story
from . import rookie_development as Development

GRADE_DAYS = 7                  # 리틀·중·고 한 학년
UNIV_GRADE_DAYS = 30            # 대학 한 학년 = 프로 한 시즌(rookie_league.CYCLE)
DECIDE_DAYS = 3
MIN_STAY, MIN_STAY_COLLEGE = 14, 7          # 프로 리그 한 단계 최소 체류(일) — 대졸은 짧게
PROMO_DAYS = 14                             # 콜업 테스트의 최근 성적 과제를 보는 기간
PROMO_MISSION = {'batter': {'pa': 20, 'ops': .700}, 'pitcher': {'outs': 24, 'era': 4.50}}
MAX_AGE = 45
RETIRE_HINT_AGE = 38
TAPER = 6.0                     # 한계 몇 앞부터 성장이 줄어드나
FOCUS_ROOM, NATURAL_ROOM = 4.0, 8.0         # 주특기는 한계 +4(천재형 +8)
CAP = 99.0
# 나이 한계 = 잠재력 × 비율(25세부터 1) — 잠재력이 학생 때부터 성장에 작용한다
AGE_RATIO = {12: .50, 13: .55, 14: .60, 15: .64, 16: .68, 17: .72, 18: .75, 19: .80, 20: .85, 21: .89, 22: .92,
             23: .95, 24: .98}
# 훈련 효율(나이 배율) — 12~21세는 이 표, 22~27세 1.0, 그 뒤로 줄어든다(age_mult)
AGE_EFF = {12: .40, 13: .45, 14: .50, 15: .55, 16: .60, 17: .65, 18: .70, 19: .80, 20: .88, 21: .94}
PHYSICAL = ('velocity', 'stamina', 'power', 'speed')
DECLINE_AT, AGING_DECAY = 33, 0.003           # 서른셋부터 몸 능력 하루 감쇠 +0.3%p × (나이 − 32) — 2026-10-19 사용자 요청으로 2년 늦춤
# 같은 나이 가상 동기 집단의 OVR(평균, 표준편차) — scratchpad 하네스(활동량 섞임 × 잠재력 분포)로 뽑은 값.
# 드래프트 평가·진학 합격·학생 '유망주' 표시·학생 리그 수준의 기준(회원 수가 적어 회원끼리 백분위를 매길 수 없다)
CLASS = {12: (36.0, 2.7), 13: (39.9, 3.9), 14: (43.3, 4.6), 15: (46.2, 5.2), 16: (48.9, 5.7), 17: (51.4, 6.2),
         18: (53.6, 6.4), 19: (58.7, 6.2), 20: (61.9, 6.4), 21: (63.9, 6.6), 22: (65.4, 6.8)}
POTENTIAL_MEAN, POTENTIAL_SD, POTENTIAL_RANGE = 82, 6, (66, 97)

TRAITS = {
    'early': {'name': '조기 개화', 'desc': '또래보다 몸이 빨리 커요. 나이 한계가 한 살 먼저 열리고 고교까지 훈련 효과 +10%, 대신 노쇠가 2년 빨리 와요.'},
    'late': {'name': '대기만성', 'desc': '늦게 피는 꽃이에요. 스물둘까지 훈련 효과 −10%, 스물여섯부터 +15%, 노쇠가 2년 늦게 와요.'},
    'grinder': {'name': '연습벌레', 'desc': '훈련 효과 +8%, 하루 훈련 피로도 6회 늦게 와요.'},
    'iron': {'name': '강철 체력', 'desc': '쉬는 날 빠지는 몫이 40% 적고, 노쇠가 절반 속도로 와요.'},
    'clutch': {'name': '큰 경기 체질', 'desc': '승부처에 강해요. 경기에서 클러치(타자)·멘탈(투수) +5.'},
    'learner': {'name': '경험파', 'desc': '경기에서 배우는 게 많아요. 출전 경험으로 오르는 능력치 +60%.'},
    'natural': {'name': '천재형', 'desc': '주특기가 남달라요. 주특기 훈련 배율 ×1.45(보통 ×1.25), 주특기 한계 +8(보통 +4).'},
}
# 드래프트 평가 점수(평균 50, 표준편차 약 10) → 라운드. 아래 값은 하네스로 맞춘다(활동량별 분포는 scratchpad bal_sim.py)
DRAFT_ROUNDS = [(66, 1), (62, 2), (59, 3), (56, 4), (54, 5), (52, 6), (50, 7), (48, 8), (46, 9), (44, 10), (42, 11)]
ABROAD_AT = {'mlb': 70, 'npb': 67, 'cpbl': 63}      # 이 점수 이상이면 그 나라 구단이 제안한다(가장 높은 한 곳 + 가끔 한 곳 더)
ABROAD_POT = {'mlb': 86, 'npb': 0, 'cpbl': 0}       # 메이저리그는 스카우트가 본 잠재력도 높아야
ABROAD = ('mlb', 'npb', 'cpbl')
SIGN_BONUS = [(1, 200), (3, 150), (7, 100), (11, 50)]   # 지명 라운드까지 → 계약 보너스 TP(파워프로 지명 순위 보상)
# 평가에서 잠재력의 무게와 스카우트 눈의 오차(표준편차) — 나머지는 동기 집단 대비 OVR(곧 활동량)이 정한다
DRAFT_W = {'hs': (0.35, 4.0), 'univ': (0.25, 3.0)}

# 경기 경험 — 줄의 기록 하나가 어느 능력에 몇 단위(훈련 1회 = 1단위 × gain)를 주나
XP_RATE = 0.08
BAT_XP = {'pa': {'contact': .10, 'eye': .06}, 'h': {'contact': .25}, 'd': {'power': .35},
          't': {'power': .35, 'speed': .30}, 'hr': {'power': .65}, 'bb': {'eye': .30}, 'sb': {'speed': .40},
          'g': {'defense': .12}}
PIT_XP = {'outs': {'control': .06, 'velocity': .04, 'breaking': .06, 'stamina': .08},
          'so': {'velocity': .10, 'breaking': .10}, 'g': {'mental': .20}, 'sv': {'mental': .30},
          'hld': {'mental': .20}, 'w': {'mental': .20}}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def has(p, code: str) -> bool:
    return code in (p.traits or [])


# ───────────────────────────── 입단 때 뽑는 것
def roll_potential(rng) -> int:
    return int(_clamp(round(rng.gauss(POTENTIAL_MEAN, POTENTIAL_SD)), *POTENTIAL_RANGE))


def roll_traits(rng) -> list:
    r = rng.random()
    n = 0 if r < 0.30 else 1 if r < 0.85 else 2
    pool = list(TRAITS)
    got = []
    while len(got) < n and pool:
        t = rng.choice(pool)
        pool.remove(t)
        if {t, *got} >= {'early', 'late'}:            # 조기 개화와 대기만성은 함께 오지 않는다
            continue
        got.append(t)
    return got


def scout_stars(p) -> int | None:
    """스카우트 별점(1~5) — 고교생이 되어야 평가가 붙는다."""
    if p.age < 16:
        return None
    pot = p.potential or 80
    return 5 if pot >= 92 else 4 if pot >= 87 else 3 if pot >= 81 else 2 if pot >= 75 else 1


STAR_NOTE = {5: '특급 유망주', 4: '상위 지명감', 3: '프로 지명감', 2: '성장 여지 보통', 1: '한계가 낮은 편'}


# ───────────────────────────── 성장 배율·한계
def age_ratio(p) -> float:
    a = p.age + (1 if 'early' in (p.traits_seen or []) else 0)     # 조기 개화는 드러난 뒤부터 한 살 먼저(줄어들지 않게)
    if a > max(AGE_RATIO):
        return 1.0
    return AGE_RATIO.get(a, AGE_RATIO[min(AGE_RATIO)])


def age_cap(p) -> float:
    """지금 나이로 오를 수 있는 끝 = (각성을 넣은) 잠재력 × 나이 비율."""
    return min(CAP, pot_eff(p) * age_ratio(p))


# 각성(2026-10-19 사용자 요청: 라이트 판의 각성을 정식 판에도, 같은 날 개편) — 별은 다섯 칸으로 고정이고, 스카우트 별 다음 빈 칸을
# 보라색 별로 채운다. 한 번 성공하면 잠재력이 한 칸 위 별의 문턱(STAR_FLOOR)까지 — 별 하나짜리도 다섯 개까지 도전할 수 있다.
# 기회: 다 자란 몸으로 다섯 능력이 모두 한계일 때, 또는 (고교 나이부터) 지금 한계 가까이(평균 AWAKEN_NEAR 안쪽)까지
# 열심히 키우고 지금 리그 성적이 좋을 때(performance ≥ AWAKEN_FORM). TP 를 들여 도전하고, 실패·보류 뒤 AWAKEN_WAIT 일.
STAR_FLOOR = {2: 75, 3: 81, 4: 87, 5: 92}             # scout_stars 의 문턱과 같다
AWAKEN_COST, AWAKEN_WAIT, AWAKEN_NEAR, AWAKEN_FORM = 150, 21, 3.0, 1.0


def awakened(p) -> int:
    return int((p.career or {}).get('awaken', 0))


def base_stars(p) -> int:
    pot = p.potential or POTENTIAL_MEAN
    return 5 if pot >= 92 else 4 if pot >= 87 else 3 if pot >= 81 else 2 if pot >= 75 else 1


def pot_eff(p) -> float:
    """각성을 넣은 잠재력 — 보라색 별 n개면 (별 + n)칸의 문턱까지."""
    pot, n = float(p.potential or POTENTIAL_MEAN), awakened(p)
    return pot if not n else float(max(pot, STAR_FLOOR[min(5, base_stars(p) + n)]))


def awaken_gain(p) -> float:
    nxt = min(5, base_stars(p) + awakened(p) + 1)
    return max(1.0, STAR_FLOOR.get(nxt, 0) - pot_eff(p))


def awaken_ready(p, today: date | None = None) -> bool:
    today = today or timezone.localdate()
    if p.retired_at or base_stars(p) + awakened(p) >= 5 or p.age < 16 or (p.pending or {}).get('kind'):
        return False
    nxt = (p.career or {}).get('awaken_next')
    if nxt and today < date.fromisoformat(nxt):
        return False
    gaps = [stat_cap(p, k) - float(p.stats.get(k, 0)) for k in p.stats]
    if age_ratio(p) >= 1.0 and all(g <= 0.5 for g in gaps):
        return True
    return sum(gaps) / len(gaps) <= AWAKEN_NEAR and performance(p, p.league) >= AWAKEN_FORM


AWAKEN_TIER = {2: 0.6, 3: 0.45, 4: 0.3, 5: 0.15}      # 목표 별 칸마다 기본 성공 확률 — 높은 별일수록 어렵다


def awaken_odds(p) -> float:
    """성공 확률 — 목표 별이 높을수록 어렵고, 연습벌레·큰 경기 체질이면 조금 높고, 서른셋 넘으면 낮다."""
    t = p.traits_seen or []
    q = AWAKEN_TIER[min(5, base_stars(p) + awakened(p) + 1)]
    q += (0.08 if 'grinder' in t else 0) + (0.04 if 'clutch' in t else 0)
    q += 0.05 if p.age <= 27 else -0.08 if p.age >= 33 else 0
    return round(_clamp(q, 0.08, 0.7), 2)


def awaken_view(p, today: date | None = None) -> dict | None:
    if not awaken_ready(p, today):
        return None
    return {'odds_pct': int(round(awaken_odds(p) * 100)), 'cost': AWAKEN_COST, 'next_n': awakened(p) + 1,
            'plus': f'{awaken_gain(p):g}', 'can_pay': p.tp >= AWAKEN_COST, 'wait': AWAKEN_WAIT,
            'stars_total': min(5, base_stars(p) + awakened(p))}


def stat_cap(p, stat: str) -> float:
    room = (NATURAL_ROOM if has(p, 'natural') else FOCUS_ROOM) if stat == p.focus else 0.0
    return min(CAP, age_cap(p) + room)


def class_z(p, ovr: float | None = None) -> float:
    """같은 나이 가상 동기 집단에서의 위치(표준점수). 22세 넘으면 22세 기준."""
    mean, sd = CLASS.get(min(max(p.age, min(CLASS)), max(CLASS)))
    return ((p.ovr if ovr is None else ovr) - mean) / sd


def room(s: float, cap: float) -> float:
    left = cap - s
    if left <= 0:
        return 0.0
    return 1.0 if left >= TAPER else left / TAPER


def age_mult(p) -> float:
    a = p.age
    m = (AGE_EFF.get(a, AGE_EFF[min(AGE_EFF)]) if a < 22 else 1.0 if a <= 29 else 0.95 if a <= 32
         else 0.85 if a <= 35 else 0.7 if a <= 38 else 0.55)                 # 2026-10-19 노쇠 2년 늦춤
    if has(p, 'late'):
        m *= 0.9 if a <= 22 else 1.15 if a >= 26 else 1.0
    if has(p, 'early') and a <= 18:
        m *= 1.1
    if has(p, 'grinder'):
        m *= 1.08
    return m


def focus_bonus(p) -> float:
    from . import rookie as R
    return 1.45 if has(p, 'natural') else R.FOCUS_BONUS


def fatigue_at(p) -> int:
    from . import rookie as R
    return R.FATIGUE_AT + (6 if has(p, 'grinder') else 0)


def decline_start(p) -> int:
    return DECLINE_AT + (2 if has(p, 'late') else 0) - (2 if has(p, 'early') else 0)


def decay_for(p, base_rate: float, stat: str) -> float:
    """그날 이 능력이 바닥 위 몫에서 잃는 비율 — 쉬는 날 몫(강철 체력 −40%) + 노쇠(몸 능력)."""
    from . import rookie as R
    r = base_rate
    if has(p, 'iron') and r > R.BASE_DECAY:
        r = R.BASE_DECAY + (r - R.BASE_DECAY) * 0.6
    if stat in PHYSICAL:
        over = p.age - decline_start(p) + 1
        if over > 0:
            r += AGING_DECAY * over * (0.5 if has(p, 'iron') else 1.0)
    return r


def promotion_gate(p, today: date | None = None) -> dict:
    """콜업 테스트의 OVR 밖 조건 — 지금 리그 최소 체류(대졸 짧게)와 최근 성적 과제. 화면 안내와 심사가 같은 값을 쓴다."""
    from . import rookie_league as L
    today = today or timezone.localdate()
    need = MIN_STAY_COLLEGE if (p.career or {}).get('draft_univ') else MIN_STAY
    stay_left = max(0, need - (today - p.league_since).days) if p.league_since else 0
    t = {}
    for line in L.recent_lines(p, today - timedelta(days=1), p.league, days=PROMO_DAYS):
        t = L.add(t, line)
    m = PROMO_MISSION[p.role]
    if p.role == 'pitcher':
        outs = t.get('outs', 0)
        era = L.pitching(t)['era'] if outs else None
        ok = outs >= m['outs'] and era is not None and era <= m['era']
        text = f"최근 {PROMO_DAYS}일 {m['outs'] // 3}이닝 이상, 평균자책점 {m['era']:.2f} 이하"
        now = f"{L.ip_text(outs)}이닝" + (f", {era:.2f}" if outs else '')
    else:
        pa = t.get('pa', 0)
        ops = L.batting(t)['ops'] if pa else None
        ok = pa >= m['pa'] and ops is not None and ops >= m['ops']
        text = f"최근 {PROMO_DAYS}일 {m['pa']}타석 이상, OPS {L.rate(m['ops'])} 이상"
        now = f"{pa}타석" + (f", OPS {L.rate(ops)}" if pa else '')
    if W.next_league(p.league) == 'mlb':
        from . import rookie_balance_rules as Balance
        ready = Balance.overseas_level(p, 'mlb') == 'mlb'
        text += ' · 메이저 스카우팅 평가 통과'
        now += ' · ' + ('평가 통과' if ready else '구위·타격 접근과 장기 성적을 더 증명해야 해요')
        ok = ok and ready
    return {'stay_need': need, 'stay_left': stay_left, 'mission': {'text': text, 'now': now, 'ok': ok},
            'ok': stay_left == 0 and ok}


def cap_message(p, stat: str, label: str) -> str:
    cap = stat_cap(p, stat)
    if age_ratio(p) < 1.0:
        return f'현재 {label} 능력치는 {p.age}세의 성장 한계({cap:.0f})에 닿았어요. 한 살 더 먹으면 한계가 높아져요.'
    if base_stars(p) + awakened(p) < 5:
        return f'현재 {label} 능력치는 타고난 한계({cap:.0f})에 닿았어요. 다섯 능력을 한계 가까이 키우고 성적을 내면 각성에 도전할 수 있어요.'
    return f'현재 {label} 능력치는 타고난 한계({cap:.0f})에 닿았어요. 다른 능력을 키워 보세요.'


def game_stats(p) -> dict:
    """경기 시뮬레이션에 넘길 능력치 — 큰 경기 체질은 승부처 능력 +5."""
    s = dict(p.stats)
    if has(p, 'clutch'):
        if p.role == 'batter':
            s['clutch'] = (float(s.get('contact', 25)) + float(s.get('eye', 25))) / 2 + 5
        else:
            s['mental'] = min(CAP, float(s.get('mental', 25)) + 5)
    from . import rookie_balance_rules as Balance
    return Balance.game_stats(p, Story.game_stats(p, s))


def game_xp(p, lines: list) -> dict:
    """그날 경기 줄들 → 능력치 소폭 상승(한계·나이 반영). p.stats·ovr·best_ovr 를 고친다(저장은 부른 쪽). {능력: 오른 양}."""
    from . import rookie as R
    table = PIT_XP if p.role == 'pitcher' else BAT_XP
    units = {}
    for line in lines:
        for key, spread in table.items():
            n = line.get(key, 0)
            if not isinstance(n, (int, float)) or n <= 0:
                continue
            if key == 'g' and p.role == 'batter' and p.position == 'DH':
                continue
            for stat, w in spread.items():
                units[stat] = units.get(stat, 0.0) + n * w
    from . import rookie_balance_rules as Balance
    development = Balance.profile(p)['development']
    rate = XP_RATE * age_mult(p) * development * .78 * (1.4 if has(p, 'learner') else 1.0) * Development.multiplier(p)
    stats, gains = dict(p.stats), {}
    for stat, u in units.items():
        if stat not in stats:
            continue
        s = float(stats[stat])
        cap = stat_cap(p, stat)
        new = min(cap, s + R.gain(s) * u * rate * room(s, cap))
        if new > s + 1e-6:
            stats[stat] = round(new, 3)
            gains[stat] = round(new - s, 3)
    if gains:
        p.stats = stats
        p.ovr = R.overall(p.role, stats)
        p.best_ovr = max(p.best_ovr, p.ovr)
    return gains


# ───────────────────────────── 숨은 특성
def reveal(p, code: str, day: date | None = None) -> bool:
    """특성이 처음 드러나면 기록하고 True(traits_seen 저장은 부른 쪽)."""
    from . import rookie as R
    if not has(p, code) or code in (p.traits_seen or []):
        return False
    p.traits_seen = list(p.traits_seen or []) + [code]
    t = TRAITS[code]
    R._log(p, 'trait', f"숨은 특성 발견 — {t['name']}: {t['desc']}", day=day)
    return True


# ───────────────────────────── 활약·합격·드래프트
def performance(p, league_code: str) -> float:
    """그 리그에서 쌓은 활약(−2 ~ +2.5) — 타자 OPS, 투수 평균자책점을 리그 평균과 견주고 표본이 작으면 줄인다. 수상 +0.5."""
    from . import rookie_league as L
    from .models import RookieAward, RookieSeasonStat
    t = {}
    for totals in RookieSeasonStat.objects.filter(player=p, league=league_code).values_list('totals', flat=True):
        t = L.add(t, totals or {})
    if p.role == 'pitcher':
        outs = t.get('outs', 0)
        z = (4.2 - L.pitching(t)['era']) / 1.4 * min(1.0, outs / 60) if outs else 0.0
    else:
        pa = t.get('pa', 0)
        z = (L.batting(t)['ops'] - .760) / .12 * min(1.0, pa / 60) if pa else 0.0
    z += 0.5 * RookieAward.objects.filter(player=p, league=league_code).count()
    return round(_clamp(z, -2.0, 2.5), 2)


def accept_chance(p, to: str, school: str, perf: float | None = None) -> float:
    """동기 집단 안 위치(표준점수)와 활약으로 — 강호는 평균이면 4분의 1, 상위 7%쯤이면 3분의 2."""
    hard = W.powerhouse(to, school)
    perf = performance(p, p.league) if perf is None else perf
    z = class_z(p)
    chance = (0.25 + 0.22 * z if hard else 0.85 + 0.08 * z) + 0.05 * _clamp(perf, -1.5, 1.5)
    return round(_clamp(chance, 0.05, 0.98), 2)


def chance_label(c: float) -> str:
    return '높음' if c >= .8 else '보통' if c >= .5 else '낮음' if c >= .25 else '매우 낮음'


def fallback_school(to: str, region: str, rng, exclude: str = '') -> tuple[str, str]:
    """떨어졌거나 고르지 않은 학생의 배정 — 우리 지역, 없으면 맞닿은 지역부터 한 겹씩(강호는 되도록 피한다).
    (학교, 그 학교의 지역)"""
    by_region = W.SCHOOLS_BY_LEAGUE.get(to, {})
    for layer in W.region_layers(region):
        pool = [(r, s) for r in layer for s in by_region.get(r, ()) if s != exclude]
        if pool:
            easy = [(r, s) for r, s in pool if not W.powerhouse(to, s)]
            r, s = rng.choice(easy or pool)
            return s, r
    r, s = rng.choice([(r, s) for r, s in W.schools(to) if s != exclude])
    return s, r


def draft_score(p, rng, perf: float | None = None) -> float:
    """평가 점수(평균 50) — 스카우트가 본 잠재력(DRAFT_W: 고졸 35%·대졸 25%, 어릴수록 오차가 크다) + 동기 집단 대비 OVR
    + 활약. 잠재력 무게를 ZenGM(18세 70%)보다 낮춘 것은 이 게임에서 활동량이 성장의 주인공이기 때문."""
    perf = performance(p, p.league) if perf is None else perf
    w_pot, err = DRAFT_W['univ' if p.league == 'univ' else 'hs']
    scout = (p.potential or POTENTIAL_MEAN) + rng.gauss(0, err)
    z = (w_pot * (scout - POTENTIAL_MEAN) / POTENTIAL_SD + (1 - w_pot) * class_z(p)
         + 0.25 * _clamp(perf, -1.5, 1.5) + (0.3 if W.powerhouse(p.league, p.club) else 0.0))
    return round(50 + 10 * z, 1), scout


def sign_bonus(rnd: int | None) -> int:
    return next((tp for upto, tp in SIGN_BONUS if rnd and rnd <= upto), 0)


def draft_round(score: float) -> int | None:
    return next((r for at, r in DRAFT_ROUNDS if score >= at), None)


# ───────────────────────────── 상태 바꾸기(행 잠금 안에서)
def _path(p, league: str, club: str, day: date):
    from . import rookie_league as L
    career = dict(p.career or {})
    career['path'] = list(career.get('path', [])) + [{'league': league, 'club': club, 'age': p.age,
                                                      'season': L.season_no(day), 'day': day.isoformat()}]
    p.career = career


def _reset_role(p, day: date):
    p.lineup = 'mop' if p.role == 'pitcher' else 'bench'
    p.slot, p.role_since = 0, day


def open_apply(p):
    """졸업 학년이 되면 다음 학교 지원서를 연다."""
    nxt = W.NEXT_SCHOOL.get(p.league)
    p.pending = {'kind': 'apply', 'to': nxt, 'choice': ''} if nxt and W.is_final_grade(p.league, p.grade) else {}


def enter_school(p, to: str, day: date, rng, choice: str = '') -> str:
    """다음 학교로 — 지원한 학교 합격 판정(떨어지면 우리 지역, 목록에 없으면 가까운 지역 학교). 기록 문장을 돌려준다."""
    from . import rookie as R
    perf = performance(p, p.league)
    home = p.region
    ok = bool(choice) and rng.random() < accept_chance(p, to, choice, perf)
    if ok:
        school, where = choice, W.school_region(to, choice)
    else:
        school, where = fallback_school(to, home, rng, exclude=choice)
    near = '우리 지역' if where == home else f'가까운 {where} 지역'
    p.league, p.grade, p.club, p.grade_since = to, 1, school, day
    p.age = W.age_of(to, 1)
    _reset_role(p, day)
    _path(p, to, school, day)
    open_apply(p)
    word = {'ms': '중학교', 'hs': '고등학교', 'univ': '대학교'}[to]
    if ok:
        text = f'{school} 합격! {word} 1학년, {p.age}세 — 신입생은 백업부터 자리를 따내야 해요'
    elif choice:
        text = f'{choice} 불합격 — {near} {school}에 입학했어요({word} 1학년, {p.age}세)'
    else:
        text = f'{school} 입학 — {word} 1학년, {p.age}세(희망 학교를 고르지 않아 {near} 학교로)'
    R._log(p, 'career', text, day=day)
    if to == 'ms':
        reveal(p, 'early', day)
    return text


def run_draft(p, day: date, rng) -> str:
    """고3·대4가 끝나는 날의 신인 드래프트 — 지명(또는 미지명)과 해외 제안을 결정 대기에 올린다."""
    from . import rookie as R
    from . import rookie_league as L
    src = p.league
    perf = performance(p, src)
    score, scout = draft_score(p, rng, perf)
    rnd = draft_round(score)
    offer = None
    if rnd:
        top, floor_ = DRAFT_ROUNDS[0][0], DRAFT_ROUNDS[-1][0]
        want = 0.10 + 0.55 * _clamp((score - floor_) / (top - floor_), 0.0, 1.0)
        team = p.team if rng.random() < want else rng.choice([c for c, _n, _col in W.KBO_TEAMS if c != p.team])
        k = rng.randint(1, 10)
        offer = {'team': team, 'round': rnd, 'in_round': k, 'pick': (rnd - 1) * 10 + k}
    ok = [s for s in ABROAD if score >= ABROAD_AT[s] and scout >= ABROAD_POT[s]]
    if src == 'hs':
        school = list(p.season_stats.filter(league=src).order_by('-season__number')[:1])
        if school and Development.exceptional_school(p, school[0].totals, 30) and 'mlb' not in ok:
            ok.append('mlb')
    # 자격이 되는 나라는 모두, 나라마다 구단 셋 가운데 고른다(2026-10-19 사용자 피드백: 해외 진출 때 뜨는 팀만 뜬다)
    from .rookie_lite import abroad_teams
    abroad = {s: (abroad_teams(s, rng) if s in ok else []) for s in ABROAD}
    season = L.season_no(day) or 1
    p.pending = {'kind': 'draft', 'from': src, 'season': season, 'score': round(score, 1), 'offer': offer,
                 'abroad': abroad, 'deadline': (day + timedelta(days=DECIDE_DAYS)).isoformat()}
    career = dict(p.career or {})
    career[f'draft_{src}'] = dict(offer or {'undrafted': True}, season=season)
    p.career = career
    if offer:
        name = W.PRO_TEAM[offer['team']]['name']
        text = (f"시즌 {season} 신인 드래프트 {rnd}라운드 {offer['in_round']}순위(전체 {offer['pick']}순위) — {name} 지명!"
                + (' 희망 구단이에요' if offer['team'] == p.team else ''))
    else:
        text = f'시즌 {season} 신인 드래프트 미지명 — 육성선수 계약, ' + ('대학 진학, ' if src == 'hs' else '') + '해외 도전 가운데 고르세요'
    R._log(p, 'career', text, day=day)
    return text


def join_pro(p, league: str, club: str, day: date, text: str, bonus: int = 0):
    from . import rookie as R
    from . import rookie_league as L
    from_univ = (p.pending or {}).get('from') == 'univ' or p.league == 'univ'
    p.league, p.club, p.grade, p.grade_since = league, club, 0, None
    p.age = max(p.age + 1, 23 if from_univ else 19)            # 드래프트 이듬해 입단
    p.age_season = L.season_no(day)
    p.pending = {}
    p.league_since = day
    _reset_role(p, day)
    _path(p, league, club, day)
    got = max(0, min(bonus, R.TP_MAX - p.tp))
    p.tp += got
    p.tp_earned += got
    R._log(p, 'career', text + (f' · 계약 보너스 +{got} TP' if got else ''), tp=got, day=day)


def first_pro_league(system: str, ovr: float, college: bool = False) -> str:
    """처음 뛸 리그 — KBO 는 퓨처스 수준에 가까우면(대졸은 늘) 퓨처스, 아니면 육성군. 미국은 고졸 싱글A·대졸 더블A,
    일본은 2군, 대만은 1군."""
    if system == 'kbo':
        return 'kbo2' if college or ovr >= W.level('kbo2') - 4 else 'kbo3'
    ladder = W.SYSTEMS[system]
    return ladder[1] if college and system == 'mlb' else ladder[0]


def decide_now(p, choice: str, day: date, rng, school: str = '') -> str:
    """드래프트 뒤 진로 결정(잠근 행에서). 고른 길의 기록 문장."""
    from . import rookie as R
    pend = p.pending or {}
    if pend.get('kind') != 'draft':
        raise R.GameError('지금은 정할 진로가 없어요.')
    offer, abroad = pend.get('offer'), pend.get('abroad') or {}
    if choice == 'sign':
        if not offer:
            raise R.GameError('지명한 구단이 없어요. 육성선수 계약이나 다른 길을 골라 주세요.')
        league = first_pro_league('kbo', p.ovr, college=pend.get('from') == 'univ')
        name = W.PRO_TEAM[offer['team']]['name']
        join_pro(p, league, offer['team'], day, f"{name} 입단 계약 — {W.short(league)}에서 프로 생활을 시작해요",
                 bonus=sign_bonus(offer.get('round')))
    elif choice == 'develop':
        if offer:
            raise R.GameError('지명을 받았으니 정식 계약을 할 수 있어요.')
        name = W.PRO_TEAM[p.team]['name']
        join_pro(p, 'kbo3', p.team, day, f'{name} 육성선수 계약 — 육성군에서 정식 선수 등록을 노려요')
    elif choice.partition(':')[0] in ABROAD:
        choice, _sep, pick = choice.partition(':')
        got = abroad.get(choice)
        teams = ([got] if got else []) if isinstance(got, str) else list(got or [])   # 예전 제안은 구단 하나(문자열)
        if not teams:
            raise R.GameError(f'{W.SYSTEM_NAME[choice]} 구단의 제안이 없어요.')
        team = pick if pick in teams else teams[0]
        league = first_pro_league(choice, p.ovr, college=pend.get('from') == 'univ')
        join_pro(p, league, team, day, f"{W.SYSTEM_NAME[choice]} 진출 — {W.PRO_TEAM[team]['name']}와 계약, {W.short(league)}부터",
                 bonus=SIGN_BONUS[1][1])
        Development.mark_entry(p, pend.get('from'), choice)
    elif choice == 'univ':
        if pend.get('from') != 'hs':
            raise R.GameError('대학 진학은 고교 졸업 때만 고를 수 있어요.')
        if school not in [s for _r, s in W.schools('univ')]:
            raise R.GameError('진학할 대학을 골라 주세요.')
        if offer:
            R._log(p, 'career', f"{W.PRO_TEAM[offer['team']]['name']}의 지명을 거절하고 대학 진학을 택했어요", day=day)
        p.pending = {}
        return enter_school(p, 'univ', day, rng, choice=school)
    else:
        raise R.GameError('진로를 다시 골라 주세요.')
    return (p.career.get('path') or [{}])[-1].get('club', '')


def default_decision(p, day: date, rng) -> str:
    pend = p.pending or {}
    choice = 'sign' if pend.get('offer') else 'develop'
    from . import rookie as R
    R._log(p, 'career', '결정 기한이 지나 ' + ('지명 구단과 계약해요' if choice == 'sign' else '희망 구단 육성선수로 계약해요'), day=day)
    return decide_now(p, choice, day, rng)


def retire_player(p, reason: str, day: date | None = None):
    from . import rookie as R
    from . import rookie_league as L
    day = day or timezone.localdate()
    career = dict(p.career or {})
    career['retired'] = {'age': p.age, 'league': p.league, 'club': p.club, 'season': L.season_no(day),
                         'reason': reason, 'day': day.isoformat()}
    p.career, p.pending, p.retired_at = career, {}, timezone.now()
    p.save(update_fields=['career', 'pending', 'retired_at', 'updated_at'])
    where = W.club_label(p.league, p.club)
    R._log(p, 'retire', f'{reason} — {p.age}세, {where}에서 유니폼을 벗었어요', day=day)


def _deadline(pend: dict, today: date) -> date:
    """진로 결정 기한 — 기록이 망가져 없으면 이미 지난 것으로 본다(밤 정산이 멈추지 않게)."""
    dl = (pend or {}).get('deadline')
    try:
        return date.fromisoformat(dl) if dl else today - timedelta(days=1)
    except (TypeError, ValueError):
        return today - timedelta(days=1)


def _deadline_passed(p, today: date) -> bool:
    pend = p.pending or {}
    return pend.get('kind') == 'draft' and _deadline(pend, today) < today


def grade_days(code: str) -> int:
    return UNIV_GRADE_DAYS if code == 'univ' else GRADE_DAYS


def _school_due(p, today: date) -> bool:
    from . import rookie_league as L
    if not (W.system_of(p.league) == 'amateur' and p.grade_since is not None
            and (today - p.grade_since).days >= grade_days(p.league) and (p.pending or {}).get('kind') != 'draft'):
        return False
    turn = p.grade_since + timedelta(days=grade_days(p.league))
    return L.games_done(turn - timedelta(days=1))      # 전날 경기를 치른 뒤에만 — 마지막 학교 경기가 옛 학교 기록으로


def _next_grade(p, rng):
    from . import rookie as R
    day = p.grade_since + timedelta(days=grade_days(p.league))   # 학년이 바뀐 날(밀렸으면 그날 기준으로 차례로)
    code = p.league
    if p.grade < W.last_grade(code):
        p.grade += 1
        p.age = W.age_of(code, p.grade)
        p.grade_since = day
        open_apply(p)
        tail = ' — 졸업 학년, ' + ('희망 학교를 고르세요' if code in W.NEXT_SCHOOL else '학년이 끝나는 날 드래프트') \
            if W.is_final_grade(code, p.grade) else ''
        R._log(p, 'career', f'{W.grade_label(code, p.grade)} 진급, {p.age}세{tail}', day=day)
        return
    if code in W.NEXT_SCHOOL:
        pend = p.pending or {}
        enter_school(p, W.NEXT_SCHOOL[code], day, rng, choice=pend.get('choice', '') if pend.get('kind') == 'apply' else '')
    else:
        run_draft(p, day, rng)


FIELDS = ['league', 'club', 'grade', 'grade_since', 'age', 'age_season', 'pending', 'career', 'lineup', 'slot',
          'role_since', 'traits_seen', 'retired_at', 'league_since', 'tp', 'tp_earned', 'updated_at']


def progress(p, today: date | None = None, rng=None) -> bool:
    """settle 이 부른다 — 결정 기한·학년·진학·드래프트·프로 나이·은퇴를 오늘까지 반영. 바뀌었으면 저장하고 True."""
    from . import rookie_league as L
    if p.retired_at:
        return False
    today = today or timezone.localdate()
    rng = rng or random.SystemRandom()
    before = (p.league, p.club, p.grade, p.grade_since, p.age, p.age_season, p.pending, len(p.traits_seen or []))
    for _ in range(16):                                   # 오래 비웠으면 밀린 학년을 차례로(기한 지난 결정은 기본값)
        if _deadline_passed(p, today):
            default_decision(p, min(today, _deadline(p.pending, today) + timedelta(days=1)), rng)
        elif _school_due(p, today):
            _next_grade(p, rng)
        else:
            break
    if W.is_pro(p.league):
        n = L.season_no(today)
        if n > (p.age_season or 0):
            if p.age_season:
                p.age += n - p.age_season
            p.age_season = n
    if p.age >= 24:
        reveal(p, 'late', today)
    if p.age >= 30:
        reveal(p, 'iron', today)
    changed = before != (p.league, p.club, p.grade, p.grade_since, p.age, p.age_season, p.pending,
                         len(p.traits_seen or []))
    if changed:
        p.save(update_fields=FIELDS)
    if W.is_pro(p.league) and p.age >= MAX_AGE:
        retire_player(p, f'{MAX_AGE}세 — 은퇴', today)
        return True
    return changed


# ───────────────────────────── 사용자 동작
def apply_school(user, school: str) -> str:
    from . import rookie as R
    R.settled(user)                                    # 학년 전환은 먼저 커밋(아래가 실패해도 되돌려지지 않게)
    with transaction.atomic():
        p = R.locked(user)
        if p is None:
            raise R.GameError(R.gone(user))
        R.settle(p)
        pend = p.pending or {}
        if pend.get('kind') != 'apply':
            raise R.GameError('지금은 진학 지원 기간이 아니에요.')
        to = pend['to']
        if school not in [s for _r, s in W.schools(to)]:
            raise R.GameError('지원할 학교를 다시 골라 주세요.')
        p.pending = dict(pend, choice=school)
        p.save(update_fields=['pending', 'updated_at'])
        c = accept_chance(p, to, school)
    return f'{school}에 지원했어요. 합격 가능성 {chance_label(c)} — 학년이 끝나는 날 발표해요.'


def decide(user, choice: str, school: str = '', rng=None) -> str:
    from . import rookie as R
    rng = rng or random.SystemRandom()
    p0, before = R.settled(user)                       # 드래프트는 먼저 커밋 — 실패한 결정과 함께 되돌려져 다시 뽑히지 않게
    if p0 is None:
        raise R.GameError(R.gone(user))
    now = p0.pending or {}
    if now.get('kind') == 'draft' and now != before:
        raise R.GameError('드래프트 결과가 방금 나왔어요. 제안을 확인하고 다시 골라 주세요.')
    with transaction.atomic():
        p = R.locked(user)
        if p is None:
            raise R.GameError(R.gone(user))
        R.settle(p)
        decide_now(p, choice, timezone.localdate(), rng, school=school)
        p.save(update_fields=FIELDS)
        return (p.logs.filter(kind='career').values_list('text', flat=True).first() or '')


# ───────────────────────────── 화면용
def _steps(p) -> list:
    code = p.league
    sysname = W.system_of(code)
    if sysname == 'amateur':
        seq = ['little', 'ms', 'hs'] + (['univ'] if code == 'univ' else [])
        cur = seq.index(code)
        drafting = (p.pending or {}).get('kind') == 'draft'
        steps = [{'label': W.short(c), 'state': 'done' if i < cur else 'cur' if i == cur and not drafting else
                  'done' if drafting and i == cur else 'next'} for i, c in enumerate(seq)]
        steps.append({'label': '드래프트', 'state': 'cur' if drafting else 'next'})
        steps.append({'label': '프로', 'state': 'next'})
        return steps
    ladder = W.SYSTEMS[sysname]
    cur = ladder.index(code)
    return [{'label': W.short(c), 'state': 'done' if i < cur else 'cur' if i == cur else 'next'}
            for i, c in enumerate(ladder)]


def career_view(p, today: date | None = None) -> dict:
    """내 선수 화면의 '진로' 칸 — 경로 단계, 학년 진행, 결정 대기(진학 지원·드래프트), 스카우트 평가, 한계, 특성."""
    today = today or timezone.localdate()
    code = p.league
    am = W.system_of(code) == 'amateur'
    pend = p.pending or {}
    v = {'amateur': am, 'steps': _steps(p), 'age': p.age, 'grade_label': W.grade_label(code, p.grade) if am else '',
         'system_name': W.SYSTEM_NAME[W.system_of(code)], 'retired': bool(p.retired_at)}
    if am and p.grade_since and pend.get('kind') != 'draft':
        day_in, span = (today - p.grade_since).days, grade_days(code)
        v['grade_left'] = max(0, span - day_in)
        v['grade_pct'] = round(min(100.0, max(0.0, day_in / span * 100)), 1)
        final = W.is_final_grade(code, p.grade)
        v['next_label'] = ({'little': '중학교 진학', 'ms': '고교 진학'}.get(code, '신인 드래프트') if final
                           else f'{p.grade + 1}학년 진급')
    if pend.get('kind') == 'apply':
        to = pend['to']
        perf = performance(p, code)
        regions = []
        for region in W.REGIONS:
            names = W.SCHOOLS_BY_LEAGUE.get(to, {}).get(region, ())
            if names:
                regions.append({'region': region, 'home': region == p.region,
                                'schools': [{'name': s, 'hard': W.powerhouse(to, s),
                                             'chance': chance_label(accept_chance(p, to, s, perf))} for s in names]})
        regions.sort(key=lambda r: not r['home'])
        choice = pend.get('choice', '')
        v['apply'] = {'to': to, 'to_name': W.league(to)['name'], 'choice': choice, 'regions': regions,
                      'home': p.region, 'home_has': bool(W.SCHOOLS_BY_LEAGUE.get(to, {}).get(p.region)),
                      'chance': chance_label(accept_chance(p, to, choice, perf)) if choice else '',
                      'level': W.level(to), 'perf': perf}
    elif pend.get('kind') == 'draft':
        offer = pend.get('offer')
        left = (_deadline(pend, today) - today).days
        abroad = []
        for s in ABROAD:
            got = (pend.get('abroad') or {}).get(s) or []
            teams = [got] if isinstance(got, str) else list(got)           # 예전 제안은 구단 하나(문자열)
            team = teams[0] if teams else ''
            first = first_pro_league(s, p.ovr, college=pend.get('from') == 'univ')
            abroad.append({'system': s, 'name': W.SYSTEM_NAME[s], 'team': W.PRO_TEAM.get(team, {}), 'code': team,
                           'teams': [W.PRO_TEAM[t] for t in teams],
                           'league': W.league(first)['name'], 'level': W.level(first), 'need': ABROAD_AT[s],
                           'hard': p.ovr < W.level(first) - 6})
        univ = []
        if pend.get('from') == 'hs':
            perf = performance(p, code)
            for region in W.REGIONS:
                names = W.UNIVERSITIES.get(region, ())
                if names:
                    univ.append({'region': region, 'home': region == p.region,
                                 'schools': [{'name': s, 'hard': W.powerhouse('univ', s),
                                              'chance': chance_label(accept_chance(p, 'univ', s, perf))} for s in names]})
            univ.sort(key=lambda r: not r['home'])
        sign_league = first_pro_league('kbo', p.ovr, college=pend.get('from') == 'univ')
        v['draft'] = {'season': pend.get('season'), 'from': pend.get('from'), 'score': pend.get('score'),
                      'offer': offer, 'team': W.PRO_TEAM.get((offer or {}).get('team', ''), {}),
                      'want': bool(offer and offer['team'] == p.team), 'want_team': W.PRO_TEAM.get(p.team, {}),
                      'sign_league': W.short(sign_league), 'abroad': abroad, 'univ': univ,
                      'bonus': sign_bonus((offer or {}).get('round')), 'abroad_bonus': SIGN_BONUS[1][1],
                      'left': max(0, left), 'deadline': _deadline(pend, today)}
    stars = scout_stars(p)
    v['scout'] = ({'stars': stars, 'note': STAR_NOTE[stars], 'range': range(5), 'total': min(5, stars + awakened(p)),
                   'awakened': awakened(p)} if stars else None)
    v['grade_days'] = grade_days(code)
    cap = age_cap(p)
    v['age_cap'] = cap if cap < min(CAP, float(p.potential or CAP)) else None
    v['traits'] = [dict(TRAITS[c], code=c) for c in (p.traits_seen or []) if c in TRAITS]
    v['retire_hint'] = p.age >= RETIRE_HINT_AGE and not p.retired_at
    v['path'] = [dict(x, league_short=W.short(x['league']), club_name=W.club_label(x['league'], x['club']))
                 for x in (p.career or {}).get('path', [])]
    v['drafts'] = [dict(d, src=src, team_name=W.PRO_TEAM.get(d.get('team', ''), {}).get('name', ''))
                   for src in ('hs', 'univ') for d in [(p.career or {}).get(f'draft_{src}')] if d]
    return v
