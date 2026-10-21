"""야구선수 키우기 라이트 — 한 판 30분, 고1부터 은퇴까지 분기점을 골라 가며 빠르게 진행하는 커리어 시뮬레이터
(2026-10-18 사용자 요청: '진짜 kickru 같은 가벼운 버전, FM 느낌').

정식 '야구선수 키우기'(사이트 활동 TP 로 매일 키우는 판)와 선수·기록이 따로다. 세계(리그·구단·학교)와 경기 모형·지표는
정식 판의 것을 그대로 쓴다(rookie_world · rookie_sim · rookie_league).

한 시즌 = 세 화면:
  비시즌(plan)   — 훈련 프로그램 두 개 + 강도(가볍게·보통·강하게) + 가끔 이벤트 하나를 고른다
  시즌(review)   — 월별 전광판이 넘어가고, 성적·시상·팀 순위·성장·승격이 나온다
  결정(decision) — 드래프트·병역·포스팅·FA·KBO 복귀·은퇴 같은 갈림길(때가 되면)
고1(16세)에서 시작해 34세부터 은퇴를 고를 수 있고 42세면 끝난다. 34세부터 1군 수준에서 크게 밀리면 방출될 수 있다
(VET_CUT) — 보통 18~24시즌, 시즌당 1분 남짓.

성장(grow): 해마다 '능력별 잠재력 × 나이 곡선(CURVE)'의 차이만큼 자라고, 고른 훈련·강도·출전 시간이 그 위에 더한다.
잠재력(숨김, 스카우트 별점으로 짐작)이 끝이다. 강하게 훈련하면 더 크지만 다칠 확률이 오른다. 서른 넘으면 몸
(구속·체력·파워·주루)이 먼저 빠지고 기술(컨택·선구안·제구·변화구·멘탈·수비)은 천천히 빠진다.
경기 모형은 리그 수준과의 차이에 민감하다(+6 ≈ 6 WAR, +12 ≈ 10 WAR) — 그래서 잠재력이 '어디까지 갈 수 있나'를 정한다:
평균 잠재력(65)은 KBO 주전, 상위 25%는 KBO 올스타, 상위 10%는 KBO MVP·메이저리그 주전감, 상위 3%는 메이저리그 스타.
시상은 가상 경쟁자 기준(AWARD_BARS — 해마다 조금씩 흔들리는 문턱)으로 정한다(한 사람만 뛰는 판이라).
킥루(축구)·Football Manager 의 '고르고 넘기는' 진행 감각만 참고했다 — 코드·화면·수치는 가져오지 않았다.

2026-10-18 추가: 훈련 가드레일(같은 훈련 3연속·같은 조합 2연속 금지), 올스타 휴식기 콜업·강등·보직 면담(감독 신뢰),
국가대표(WBC·아시안게임·올림픽·프리미어12), 기사 제목, 은퇴 카드, 능력치 값 균등화(rookie_sim·OVR 평균),
결정적 순간(결승 승부처에서 노림수·구종 선택 — 스카우팅 리포트를 읽으면 이득), 능력치가 바뀐 이유(deltas['_why']).
같은 날 4차: 해외에서 시즌마다 KBO 복귀 제안·스스로 유턴, 커리어 하이는 가장 높은 무대 기준, 상점(집·배트·보호대·액세서리)과
인기(광고 수입·올스타·연봉), 경쟁자 스캔들(내게 기회)·억까 부상, 명예의 전당 투수·야수, 코칭스태프 이름은 무대마다(rookie_staff).
"""
from __future__ import annotations

import hashlib
import json
import math
from . import rookie_contracts as Contracts
from . import rookie_development as Development
from . import rookie_universe as Universe
import random
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from . import rookie as R
from . import rookie_league as L
from . import rookie_names as N
from . import rookie_sim as M
from . import rookie_staff as S
from . import rookie_world as W
from . import rookie_story as Story
from . import rookie_balance_rules as Balance
from . import rookie_pitching as Pitching

START_AGE, RETIRE_FROM, RETIRE_AT = 16, 34, 42
BASE_YEAR = 2026                 # 예전 커리어(flags.start 없음)의 고1 시즌 달력 연도
POT_MEAN, POT_SD, POT_RANGE = 65, 7, (50, 92)
HS_COMPETE = 3.0          # 강호 고교는 주전 경쟁이 세다 — 보직을 정할 때 리그 수준을 이만큼 높게 본다(학교를 고르게 되며 강호만 고르지 않게)
# 나이별 잠재력 몫 — 27~30세가 꼭짓점, 서른둘부터 해마다 더 빨리 빠진다(2026-10-18 노쇠 조정, 2026-10-19 사용자 요청으로
# 노쇠 시작을 2년 늦춤: 예전엔 잠재력 80 선수가 마흔까지 1군 수준을 지켜 통산 400승이 나왔다)
CURVE = {16: .55, 17: .61, 18: .67, 19: .72, 20: .77, 21: .81, 22: .85, 23: .88, 24: .91, 25: .93, 26: .95,
         27: .96, 28: .96, 29: .96, 30: .96, 31: .95, 32: .93, 33: .90, 34: .86, 35: .82, 36: .77, 37: .72,
         38: .66, 39: .60, 40: .54, 41: .48, 42: .43, 43: .38}
DECLINE_FROM = 32           # 이 나이부터 곡선이 빠지는 만큼 능력에 반영(기술은 SKILL_KEEP, 몸은 PHYS_KEEP 배)
PHYS = ('velocity', 'stamina', 'power', 'speed')
# 서른 넘어 빠지는 몫 — 곡선이 빠지는 만큼에 곱한다(기술은 천천히, 몸은 빨리, 강철 체력은 몸도 천천히)
SKILL_KEEP, PHYS_KEEP, IRON_KEEP = 0.85, 1.2, 0.9
# 나이별 훈련 효과 — (이 나이까지, 배율). 나이 들수록 훈련으로 노쇠를 메우기 어렵다(예전엔 서른 넘어도 0.6 이라 빠진 만큼 도로 채웠다)
AGE_TRAIN = ((22, 1.2), (29, 1.0), (32, 0.75), (35, 0.5), (38, 0.3), (99, 0.15))
VET_CUT = 35                # 이 나이부터 1군 수준에서 크게 밀린 베테랑은 시즌 뒤 방출될 수 있다(2군에서 마흔둘까지 버티며 기록만 쌓지 않게)
PLUS, MINUS = 5.0, 6.0                     # 스타일 강점 능력 잠재력 +5, 약점 −6
GAMES = {'hs': 30, 'univ': 40, 'kbo3': 60, 'kbo2': 100, 'kbo1': 144, 'mlb_a': 120, 'mlb_aa': 130, 'mlb_aaa': 140,
         'mlb': 162, 'npb2': 100, 'npb1': 143, 'cpbl': 120}
TEAMS_N = {'kbo1': 10, 'kbo2': 11, 'mlb': 30, 'mlb_aaa': 30, 'mlb_aa': 30, 'mlb_a': 30, 'npb1': 12, 'npb2': 12,
           'cpbl': 6}
POSTSEASON = {'kbo1': (.32, .22, .16, .10, .06), 'npb1': (.30, .20, .15, .12, .10, .08), 'cpbl': (.40, .30, .20, .10),
              'mlb': (.17, .13, .11, .09, .08, .07, .06, .05, .05, .04, .04, .03)}
CHUNKS = {'hs': ('주말리그 전반', '주말리그 후반', '황금사자기', '청룡기', '대통령배', '봉황대기'),
          'univ': ('춘계리그', 'U-리그 1차', 'U-리그 2차', '대학선수권', '추계리그', '전국체전'),
          'pro': ('4월', '5월', '6월', '7월', '8월', '9월')}
TOURNAMENTS = {'hs': ('황금사자기', '청룡기', '대통령배', '봉황대기'), 'univ': ('대학선수권', '전국체전')}
DRAFT_CLASS = {'hs': (54.0, 5.7), 'univ': (62.5, 6.4)}      # 드래프트 동기 집단 OVR(평균, 표준편차) — 하네스로 맞춘 값

STYLES = {
    'batter': {
        'contact': {'label': '교타자', 'desc': '정확하게 맞혀 출루해요', 'plus': ('contact', 'eye'), 'minus': 'power'},
        'power': {'label': '거포', 'desc': '담장을 넘겨요', 'plus': ('power',), 'minus': 'speed'},
        'speed': {'label': '호타준족', 'desc': '치고 달려요', 'plus': ('speed', 'contact'), 'minus': 'power'},
        'glove': {'label': '수비형', 'desc': '수비로 먹고살아요', 'plus': ('defense', 'speed'), 'minus': 'power'},
    },
    'pitcher': {
        'fire': {'label': '파이어볼러', 'desc': '강속구로 윽박질러요', 'plus': ('velocity',), 'minus': 'control'},
        'control': {'label': '제구형', 'desc': '원하는 곳에 던져요', 'plus': ('control', 'mental'), 'minus': 'velocity'},
        'breaking': {'label': '변화구형', 'desc': '휘어 나가는 공으로 잡아요', 'plus': ('breaking',), 'minus': 'velocity'},
        'horse': {'label': '이닝이터', 'desc': '오래 던져요', 'plus': ('stamina', 'control'), 'minus': 'breaking'},
    },
}
PIT_POSITIONS = [('SP', '선발 투수'), ('RP', '구원 투수')]
# 훈련 프로그램 — 한 번에 능력치 합 3.0(2026-10-18 균등화: 예전 밸런스는 0.9×5 = 4.5 라 늘 이득이었다).
# 부작용이 있는 웨이트(주루 −0.5)·구속(부상 위험 +3%p)은 그만큼 더 올려 준다. 안내 글은 그 능력이 경기에서 하는 일.
PROGRAMS = {
    'batter': [('contact', '타격 기술', '컨택 + · 삼진↓ 안타↑', {'contact': 3.0}),
               ('power', '웨이트', '파워 ++ · 홈런·장타 (주루 조금 −)', {'power': 3.5, 'speed': -0.5}),
               ('eye', '영상 분석', '선구안 + · 볼넷↑ 삼진↓', {'eye': 3.0}),
               ('speed', '스프린트·주루', '주루 + · 내야안타·도루·수비 범위', {'speed': 3.0}),
               ('defense', '수비 펑고', '수비 + · 유격·포수일수록 값이 커요', {'defense': 3.0}),
               ('balance', '밸런스', '다섯 능력 조금씩(합은 다른 훈련과 같아요)', {k: 0.6 for k in M.BAT})],
    'pitcher': [('velocity', '구속 프로그램', '구속 ++ · 삼진↑ 장타↓ (부상 위험 +)', {'velocity': 3.5}),
                ('control', '불펜 제구', '제구 + · 볼넷↓', {'control': 3.0}),
                ('breaking', '변화구 개발', '변화구 + · 헛스윙↑ 장타↓', {'breaking': 3.0}),
                ('stamina', '러닝·체력', '체력 + · 긴 이닝·막판 구위(불펜은 연투)', {'stamina': 3.0}),
                ('mental', '멘탈 코칭', '멘탈 + · 볼넷↓·위기에 강함', {'mental': 3.0}),
                ('balance', '밸런스', '다섯 능력 조금씩(합은 다른 훈련과 같아요)', {k: 0.6 for k in M.PIT})],
}
INTENSITY = {'light': ('가볍게', 0.6, 0.03), 'normal': ('보통', 1.0, 0.07), 'hard': ('강하게', 1.5, 0.14)}
TRAITS = {
    'early': ('조기 개화', '또래보다 1년 빨리 자라고, 2년 빨리 늙어요.'),
    'late': ('대기만성', '1년 늦게 자라고, 2년 늦게 늙어요.'),
    'iron': ('강철 체력', '잘 다치지 않고 늦게 늙어요.'),
    'glass': ('유리몸', '자주 다쳐요.'),
    'grinder': ('연습벌레', '훈련 효과가 25% 커요.'),
    'learner': ('경험파', '경기에 나갈수록 크게 자라요.'),
    'clutch': ('큰 경기 체질', '승부처에 강해요(타자는 클러치, 투수는 멘탈 +5).'),
    'natural': ('천재형', '강점 능력이 6 더 높이 자라요.'),
}
AWARD_BARS = {   # 가상 경쟁자 기준 — (평균, 흔들림). 셀 수 있는 기록은 144경기 기준, 리그 경기 수만큼 늘린다
    'mvp': (8.0, 0.8), 'rookie': (3.0, 0.6), 'gg_bat': (5.0, 0.6), 'gg_pit': (4.5, 0.5), 'ace': (5.5, 0.6),
    'avg': (.335, .010), 'hr': (33, 3), 'rbi': (115, 8), 'sb': (35, 5), 'w': (17, 1.5), 'era': (2.30, .20),
    'so': (210, 15), 'sv': (48, 3), 'hld': (30, 4), 'allstar': (2.0, 0.5), 'minor': (5.0, 0.6),
}


class LiteError(ValueError):
    """화면에 그대로 보여 줄 규칙 위반."""


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def has(c, t):
    return t in (c.traits or [])


def man(n: int) -> str:
    """만원 → '12억 3,000만원'."""
    n = int(n or 0)
    if n <= 0:
        return '0원'
    eok, rest = divmod(n, 10000)
    if eok and rest:
        return f'{eok:,}억 {rest:,}만원'
    return f'{eok:,}억원' if eok else f'{rest:,}만원'


# ───────────────────────────── 선수 만들기
# 각성(2026-10-19 사용자 요청, 같은 날 개편) — 별은 다섯 칸으로 고정이고, 스카우트 별(잠재력) 다음 빈 칸을 보라색 별로 채운다.
# 한 번 각성하면 잠재력이 한 칸 위 별의 문턱(STAR_FLOOR)까지 오른다 — 별 하나짜리도 다섯 개까지 도전할 수 있다.
# 기회: 다섯 능력이 모두 한계일 때, 또는 잠재력 가까이(평균 AWAKEN_NEAR 안쪽)까지 열심히 키우고 지난 시즌 성적이 좋을 때.
STAR_FLOOR = {2: 61, 3: 68, 4: 77, 5: 84}             # scout_stars 의 문턱과 같다
AWAKEN_AGE, AWAKEN_WAIT, AWAKEN_NEAR, AWAKEN_FORM = 35, 3, 3.0, 1.0


def awakened(c) -> int:
    return int((c.flags or {}).get('awaken', 0))


def base_stars(c) -> int:
    """잠재력 그대로의 별(오차 없이) — 각성은 여기서부터 다섯 칸까지."""
    p = c.potential
    return 5 if p >= 84 else 4 if p >= 77 else 3 if p >= 68 else 2 if p >= 61 else 1


def pot_eff(c) -> float:
    """각성을 넣은 잠재력 — 보라색 별 n개면 (별 + n)칸의 문턱까지."""
    n = awakened(c)
    return float(c.potential) if not n else float(max(c.potential, STAR_FLOOR[min(5, base_stars(c) + n)]))


def awaken_gain(c) -> float:
    """다음 각성으로 오를 잠재력."""
    nxt = min(5, base_stars(c) + awakened(c) + 1)
    return max(1.0, STAR_FLOOR.get(nxt, 0) - pot_eff(c))


def stat_pot(c, k: str) -> float:
    st = STYLES[c.role][c.style]
    p = pot_eff(c)
    if k in st['plus']:
        p += PLUS + (6.0 if has(c, 'natural') else 0.0)
    elif k == st['minus']:
        p -= MINUS
    return _clamp(p, 40.0, 99.0)


def room_of(c, k: str) -> float:
    """잠재력까지 남은 자리(0~1). 1 이면 오를 몫을 다 받고, 0 이면 그 능력은 훈련해도 더 오르지 않는다."""
    return _clamp((stat_pot(c, k) - float(c.stats[k])) / 5.0, 0.0, 1.0)


def frac(c, k: str, age: int) -> float:
    a = age
    if has(c, 'early'):
        a = a + 1 if a <= 24 else a + 2
    elif has(c, 'late'):
        a = a - 1 if a <= 26 else a - 2
    a = int(_clamp(a, min(CURVE), max(CURVE)))
    f = CURVE[a]
    if a > DECLINE_FROM - 1:
        keep = SKILL_KEEP if k not in PHYS else (IRON_KEEP if has(c, 'iron') else PHYS_KEEP)    # 기술은 천천히, 몸은 빨리
        top = CURVE[DECLINE_FROM - 1]
        f = top - (top - f) * keep
    return f


def roll_traits(rng) -> list:
    n = rng.choices((0, 1, 2), (0.35, 0.5, 0.15))[0]
    pool, got = list(TRAITS), []
    while len(got) < n and pool:
        t = rng.choice(pool)
        pool.remove(t)
        if {'early', 'late'} <= {t, *got} or {'iron', 'glass'} <= {t, *got}:
            continue
        got.append(t)
    return got


def school_choices(region: str) -> list:
    """고향에서 입학할 수 있는 고교 [(지역, 학교)] — 고교 야구부가 없는 지역(울산·세종)은 가장 가까운 겹의 지역 학교."""
    for layer in W.region_layers(region):
        pool = [(r, s) for r, s in W.schools('hs') if r in layer]
        if pool:
            return pool
    return W.schools('hs')


def duty_level(c) -> float:
    """보직을 정할 때 보는 리그 수준 — 강호 고교는 주전 경쟁이 세서 HS_COMPETE 만큼 높고,
    프로는 감독 신뢰가 높을수록 낮게(기회를 더), 낮을수록 높게 본다(신뢰 0 → +4, 100 → −4)."""
    lvl = W.level(c.league)
    if c.league == 'hs' and W.powerhouse('hs', c.club):
        lvl += HS_COMPETE
    if W.is_pro(c.league):
        lvl -= _clamp((trust(c) - TRUST_START) / 40, -1.25, 1.25)
    return lvl


def create(user, *, name, role, position, style, region, team, number=0, rng=None, guest='', school=''):
    """고향 고교 1학년으로 시작 — school 을 고르면 그 학교(고향 지역 학교여야 한다), 안 고르면 지역 학교 가운데 하나.
    user 가 없으면 손님 판(guest = 세션 표식) — 로그인하면 계정으로 옮긴다(claim_guest)."""
    from django.contrib.auth.models import User
    from .models import LiteCareer
    rng = rng or random.SystemRandom()
    if user is None and not guest:
        raise LiteError('잠시 뒤 다시 시도해 주세요.')
    if role not in STYLES or style not in STYLES[role]:
        raise LiteError('투수·타자와 스타일을 다시 골라 주세요.')
    valid = [c for c, _l in PIT_POSITIONS] if role == 'pitcher' else [c for c, _l in L.POSITIONS]
    if position not in valid:
        raise LiteError('포지션을 다시 골라 주세요.')
    if region not in W.REGIONS or team not in R.TEAM:
        raise LiteError('지역과 희망 구단을 골라 주세요.')
    pool = [s for _r, s in school_choices(region)]
    if school and school not in pool:
        raise LiteError('고향 지역 고등학교 가운데에서 골라 주세요.')
    name = (name or '').strip()[:12] or (user.username[:12] if user else '새내기')
    if N.blocked(name):
        raise LiteError(N.MESSAGE)
    with transaction.atomic():
        if user is not None:
            User.objects.select_for_update().filter(pk=user.pk).first()
            mine = LiteCareer.objects.filter(user=user)
        else:
            mine = LiteCareer.objects.filter(user__isnull=True, guest=guest)
        if mine.filter(retired_at__isnull=True).exists():
            raise LiteError('진행 중인 커리어가 있어요. 은퇴한 뒤에 새로 시작할 수 있어요.')
        wait = quit_wait(mine)
        if wait:
            raise LiteError(f'스스로 은퇴하면 5분 동안은 새 선수를 만들 수 없어요. {wait_text(wait)} 뒤에 다시 시작해 주세요.')
        c = LiteCareer(user=user, guest='' if user else guest, name=name, number=max(0, min(99, int(number or 0))), role=role, position=position,
                       style=style, region=region, team=team, age=START_AGE, league='hs', club=school or rng.choice(pool), grade=1,
                       potential=int(_clamp(round(rng.gauss(POT_MEAN, POT_SD)), *POT_RANGE)), traits=roll_traits(rng))
        c.stats = {k: round(max(25.0, stat_pot(c, k) * frac(c, k, START_AGE) + rng.gauss(0, 2)), 1)
                   for k in R.stat_keys(role)}
        c.ovr = c.best_ovr = R.overall(role, c.stats)
        c.flags = {'kbo_years': 0, 'pro_years': 0, 'leagues': [], 'served': False, 'exempt': False,
                   'start': timezone.localdate().year, 'trust': TRUST_START}
        c.peak = 'hs'
        c.pending = plan_step(c, rng)
        c.save()
    return c


def claim_guest(user, guest: str) -> int:
    """로그인한 회원에게 손님 판을 옮긴다 — 은퇴한 판은 모두, 진행 중인 판은 회원에게 진행 중인 판이 없을 때만."""
    from .models import LiteCareer
    if not guest or user is None:
        return 0
    with transaction.atomic():
        n = LiteCareer.objects.filter(user__isnull=True, guest=guest, retired_at__isnull=False).update(user=user, guest='')
        if not LiteCareer.objects.filter(user=user, retired_at__isnull=True).exists():
            n += LiteCareer.objects.filter(user__isnull=True, guest=guest, retired_at__isnull=True).update(user=user, guest='')
    return n


def scout_stars(c) -> int:
    """스카우트 별점(1~5) — 어릴수록 흐릿하다(잠재력 ± 오차를 선수마다 고정)."""
    noise = ((c.pk or 7) * 37 % 9 - 4) * (1.0 if c.age < 19 else 0.5 if c.age < 23 else 0.0)
    p = c.potential + noise
    return 5 if p >= 84 else 4 if p >= 77 else 3 if p >= 68 else 2 if p >= 61 else 1


STAR_NOTE = {5: '메이저리그 재목', 4: '리그 간판감', 3: '1군 주전감', 2: '1군 백업감', 1: '갈 길이 멀다'}


# ───────────────────────────── 비시즌 — 훈련과 이벤트
def _event_pool(c):
    """조건이 맞는 이벤트들 — (코드, 무게)."""
    pro = W.is_pro(c.league)
    last = c.seasons.order_by('-year').first() if c.pk else None
    pool = [('form', 3 if c.age <= 30 else 1), ('mentor', 2), ('camp', 2)]
    if c.role == 'batter' and c.position in ('SS', 'C', '2B', '3B', 'OF') and 18 <= c.age <= 30:
        pool.append(('position', 2))
    if c.role == 'pitcher' and c.age <= 30:
        pool.append(('pitch', 2))
    if last and last.games and _bad(last):
        pool.append(('slump', 4))
        pool.append(('approach', 5))
    if pro and float((c.flags or {}).get('workload', 0)) >= .25:
        pool.append(('recovery', 4))
    if pro and last and last.duty.startswith(('백업', '패전')) and c.age >= 21:
        pool.append(('trade', 3))
    if pro and c.ovr >= W.level(c.league) + 4:
        pool.append(('media', 2))
    pool += [('interview', 3), ('conduct', 2)]
    return pool


def _bad(s) -> bool:
    t = s.totals or {}
    if t.get('outs'):
        return L.pitching(t)['era'] >= 5.5
    return bool(t.get('pa')) and L.batting(t)['ops'] < .600


# 말하는 사람 — 그림은 테크창 연구실 사람들(media/lab/chars/<키>_idle.png). 팀 코칭스태프(lead·coding·hrd·checker)는
# 지금 소속(고교·대학·나라·구단)마다 다른 사람이고(rookie_staff), 스카우트·기자·에이전트·해설위원은 커리어 내내 같은 사람이다.
def who_is(c, who: str) -> tuple:
    """(이름, 직함)."""
    return S.staff(c.league, c.club, who, c.role)


DECISION_WHO = {'draft': 'data', 'military': 'lead', 'posting': 'charter', 'fa': 'charter', 'return': 'charter',
                'retire': 'lead', 'released': 'lead', 'end': 'lead', 'awaken': 'hrd'}
EVENTS = {
    'interview': {'who': 'charter', 'title': lambda c: '기자 인터뷰',
                 'text': lambda c: '최근 성적과 앞으로의 목표를 묻는 질문이에요. 답변은 팬과 감독에게 전해져요.',
                 'choices': [(k, label, hint) for k, label, _tone, hint in Story.CHOICES['interview']]},
    'conduct': {'who': 'lead', 'title': lambda c: '경기 전날의 선택',
                'text': lambda c: '회복과 훈련, 팬과의 만남, 늦은 약속. 어떤 일정을 보낼지 정해요.',
                'choices': [(k, label, hint) for k, label, _tone, hint in Story.CHOICES['conduct']]},
    'form': {'who': 'coding', 'title': lambda c: '투구폼 교정 제안' if c.role == 'pitcher' else '타격폼 교정 제안',
             'text': lambda c: '폼을 한번 뜯어고쳐 볼까요? 잘 맞으면 한 단계 올라서지만, 몸에 안 붙으면 한 시즌을 헤맬 수도 있어요.'
             if c.role == 'batter' else '팔 각도를 조금 바꿔 볼까요? 잘 맞으면 공이 달라지지만, 안 맞으면 한 시즌을 헤맬 수도 있어요.',
             'choices': [('accept', '교정해 볼게요', '성공하면(55%) 핵심 능력 +4, 실패하면 −2'), ('decline', '지금 폼을 지킬게요', '변화 없음')]},
    'mentor': {'who': 'hrd', 'title': lambda c: '베테랑과 비시즌 훈련',
               'text': lambda c: '팀 베테랑이 이번 비시즌 개인 훈련에 같이 가자고 해요. 경기 운영을 많이 배울 거예요.',
               'choices': [('accept', '따라갈게요', '멘탈·선구안(제구) +2'), ('decline', '혼자 준비할게요', '체력 +1')]},
    'camp': {'who': 'checker', 'title': lambda c: '해외 개인 훈련 캠프',
             'text': lambda c: '미국 트레이닝 센터에서 초청이 왔어요. 최신 장비로 몸을 만들 수 있지만, 쉴 틈은 없어요.',
             'choices': [('accept', '다녀올게요', '강점 능력 +2, 이번 시즌 부상 위험 +3%p'), ('decline', '국내에서 쉴게요', '이번 시즌 부상 위험 −3%p')]},
    'position': {'who': 'lead', 'title': lambda c: '포지션 변경 제안',
                 'text': lambda c: f'{L.POS_LABEL.get(c.position, c.position)} 말고 다른 자리를 맡아 보면 어때요? 수비 부담이 줄면 타격에 집중할 수 있어요.',
                 'choices': [('accept', '해 볼게요', '수비 부담이 적은 자리(1루수·지명타자 쪽)로, 컨택·파워 +1'), ('decline', '지금 자리를 지킬게요', '수비 +1')]},
    'pitch': {'who': 'coding', 'title': lambda c: '새 구종 연마',
              'text': lambda c: '구종을 하나 더 익혀 보면 어때요? 손에 붙으면 타자들이 훨씬 까다로워할 거예요.',
              'choices': [('accept', '새 구종을 익힐게요', '성공하면(60%) 변화구 +4, 실패하면 제구 −1'), ('decline', '가진 공을 다듬을게요', '제구 +1')]},
    'national': {'who': 'lead', 'title': lambda c: '국가대표 차출',
                 'text': lambda c: '국가대표팀 명단에 이름이 올랐어요. 큰 무대 경험이 되지만 비시즌에 쉴 시간은 줄어요.',
                 'choices': [('accept', '태극마크를 달게요', '멘탈 +2, 우승하면 병역 특례(KBO), 부상 위험 +3%p'), ('decline', '소속팀에 집중할게요', '변화 없음')]},
    'slump': {'who': 'hrd', 'title': lambda c: '슬럼프',
              'text': lambda c: '지난 시즌은 생각만큼 안 풀렸죠. 이번 비시즌을 어떻게 보낼까요?',
              'choices': [('accept', '특타·특훈으로 이겨낼게요', '핵심 능력 +2, 부상 위험 +3%p'), ('decline', '푹 쉬면서 머리를 비울게요', '멘탈 +1, 부상 위험 −3%p')]},
    'trade': {'who': 'charter', 'title': lambda c: '트레이드 요청',
              'text': lambda c: '지난 시즌엔 기회가 거의 없었어요. 구단에 트레이드를 요청해 볼까요?',
              'choices': [('accept', '트레이드를 요청할게요', '같은 리그 다른 구단으로(출전 기회를 찾아)'), ('decline', '남아서 경쟁할게요', '멘탈 +1')]},
    'media': {'who': 'charter', 'title': lambda c: '예능 출연 제안',
              'text': lambda c: '인기 예능에서 출연 제안이 왔어요. 팬은 늘겠지만 훈련 시간은 줄어요.',
              'choices': [('accept', '출연할게요', '인기 +6, 연봉 +10%, 훈련 효과 −20%'), ('decline', '야구에 집중할게요', '훈련 효과 +10%')]},
}


EVENTS.update({
    'approach': {'who': 'coding', 'title': lambda c: '상대의 공략에 대응할 때예요',
                 'text': lambda c: '최근 약점이 반복해서 공략당하고 있어요. 장점을 일부 양보하고 접근을 바꿀지, 기존 방식을 유지할지 정해요.',
                 'choices': [('accept', '접근을 수정할게요', '이번 시즌 타자는 컨택 +1.5·선구안 +0.5·파워 −2, 투수는 제구 +1.5·체력 +0.5·구속 −2'),
                             ('decline', '기존 장점을 유지할게요', '추가 보정 없이 원래 능력으로 승부해요')]},
    'recovery': {'who': 'hrd', 'title': lambda c: '누적 부담을 관리해요',
                 'text': lambda c: '지난 시즌의 많은 출전이 몸에 남아 있어요. 출전과 훈련을 이어갈지, 회복에 시간을 쓸지 정해요.',
                 'choices': [('accept', '회복과 재활을 우선할게요', '누적 부담 −70%, 이번 시즌 훈련 효과 −15%, 부상 위험 −2%p'),
                             ('decline', '정상 일정을 이어갈게요', '훈련 효과 유지, 누적 부담이 실전 체력과 부상 위험에 남아요')]},
})


def plan_step(c, rng) -> dict:
    """비시즌 화면 — 이벤트는 70% 확률로 하나."""
    ev = None
    pool = _event_pool(c)
    if pool and rng.random() < 0.7:
        codes, weights = zip(*pool)
        ev = rng.choices(codes, weights)[0]
    shop = None
    if W.is_pro(c.league) and rng.random() < ACC_STOCK:               # 한정품은 가끔만 들어온다(사기 어렵게)
        left = [k for k in ACCESSORY if k not in ((c.flags or {}).get('acc') or [])]
        shop = rng.choice(left) if left else None
    return {'kind': 'plan', 'event': ev, 'intl': intl_offers(c), 'shop': shop}


def event_view(c, code: str | None) -> dict | None:
    if not code:
        return None
    e = EVENTS[code]
    name, role = who_is(c, e['who'])
    return {'code': code, 'title': e['title'](c), 'text': e['text'](c), 'who': e['who'], 'who_name': name, 'who_role': role,
            'background': 'press-room' if code in ('interview', 'media') else 'manager-office',
            'choices': [{'key': k, 'label': lab, 'hint': _event_hint(c, code, k, h)} for k, lab, h in e['choices']]}


def _event_hint(c, code, choice, fallback):
    """투타에 따라 실제로 바뀌는 능력만 안내한다. 기존 선택 키와 효과는 유지한다."""
    pit = c.role == 'pitcher'
    if code == 'mentor':
        return ('멘탈 +2 · 제구 +1' if pit else '선구안 +2 · 컨택 +1') if choice == 'accept' else ('체력 +1' if pit else '주루 +1')
    if code == 'slump' and choice == 'decline':
        return ('멘탈 +1 · ' if pit else '') + '부상 위험 −3%p'
    if code == 'trade' and choice == 'decline' and not pit:
        return '소속 구단에서 주전 경쟁을 이어가요'
    return fallback


def _core(c) -> str:
    """'핵심 능력' — 스타일의 첫 강점."""
    return STYLES[c.role][c.style]['plus'][0]


def _note(c, k: str, delta: float, why: str):
    """시즌 중 능력치를 바꾼 일 — 결산의 '왜 바뀌었나'에 쓴다."""
    if abs(delta) >= 0.05:
        c.flags = c.flags if isinstance(c.flags, dict) else {}
        c.flags.setdefault('ledger', []).append([k, round(delta, 2), why])


def apply_event(c, code: str, choice: str, rng, mods: dict) -> str:
    """이벤트 선택의 효과 — 능력치·플래그를 고치고 소식 문장을 돌려준다. mods: 이번 시즌 부상·훈련·연봉 보정."""
    s, core = c.stats, _core(c)
    if code in ('approach', 'recovery'):
        if choice not in ('accept', 'decline'):
            raise LiteError('현재 이벤트의 선택지를 골라 주세요.')
        if choice == 'accept' and code == 'approach':
            c.flags['approach_year'] = c.year
            return '이번 시즌 접근을 수정해 장점 일부를 양보하고 약점에 대응해요.'
        if choice == 'accept':
            c.flags['workload'] = float(c.flags.get('workload', 0)) * .3
            mods['train'] *= .85
            mods['injury'] -= .02
            return '훈련 시간을 줄이고 회복해 누적 부담을 덜었어요.'
        return '기존 접근과 정상 일정을 유지해요.'
    if code in ('interview', 'conduct'):
        return Story.resolve(c, Story.encounter(c, code, rng), choice, rng)

    def bump(k, v, why):
        if k in s:
            old = float(s[k])
            s[k] = round(_clamp(old + v, 25.0, stat_pot(c, k) + 2), 1)
            _note(c, k, s[k] - old, why)
    if code == 'form':
        if choice == 'accept':
            if rng.random() < 0.55:
                bump(core, 4, '폼 교정 성공')
                return '폼 교정에 성공했어요 — ' + ('공이 달라졌어요' if c.role == 'pitcher' else '타구가 달라졌어요')
            bump(core, -2, '폼 교정 실패')
            return '폼 교정이 몸에 붙지 않아 애를 먹었어요'
        return '익숙한 폼을 지켰어요'
    if code == 'mentor':
        if choice == 'accept':
            bump('mental' if c.role == 'pitcher' else 'eye', 2, '베테랑 멘토링')
            bump('control' if c.role == 'pitcher' else 'contact', 1, '베테랑 멘토링')
            return '베테랑에게 경기 운영을 배웠어요'
        bump('stamina' if c.role == 'pitcher' else 'speed', 1, '혼자 준비')
        return '혼자 비시즌을 보냈어요'
    if code == 'camp':
        if choice == 'accept':
            for k in STYLES[c.role][c.style]['plus']:
                bump(k, 2, '해외 캠프')
            mods['injury'] += 0.03
            return '해외 캠프에서 몸을 새로 만들었어요'
        mods['injury'] -= 0.03
        return '국내에서 푹 쉬었어요'
    if code == 'position':
        if choice == 'accept':
            c.position = rng.choice(['1B', 'DH']) if c.position in ('C', '3B', '1B') else rng.choice(['OF', '1B', 'DH'])
            bump('contact', 1, '포지션 변경')
            bump('power', 1, '포지션 변경')
            return f'{L.POS_LABEL[c.position]}로 자리를 옮겼어요'
        bump('defense', 1, '수비 훈련')
        return '지금 자리를 지키기로 했어요'
    if code == 'pitch':
        if choice == 'accept':
            if rng.random() < 0.6:
                bump('breaking', 4, '새 구종 성공')
                return '새 구종을 손에 넣었어요'
            bump('control', -1, '새 구종 실패')
            return '새 구종이 손에 익지 않았어요'
        bump('control', 1, '가진 공 다듬기')
        return '가진 공을 다듬었어요'
    if code == 'national':
        if choice == 'accept':
            bump('mental' if c.role == 'pitcher' else 'eye', 2, '국가대표')
            mods['injury'] += 0.03
            win = rng.random() < 0.45
            mods['national'] = '우승' if win else '준우승' if rng.random() < 0.4 else '탈락'
            if win and c.league.startswith('kbo') and not c.flags.get('served'):
                c.flags['exempt'] = True
                return '국가대표 우승! 병역 특례를 받았어요'
            return f"국가대표로 뛰었어요 — {mods['national']}"
        return '소속팀 훈련에 집중했어요'
    if code == 'slump':
        if choice == 'accept':
            bump(core, 2, '특타·특훈')
            mods['injury'] += 0.03
            return '특타·특훈으로 비시즌을 보냈어요'
        bump('mental', 1, '휴식')
        mods['injury'] -= 0.03
        return '푹 쉬면서 머리를 비웠어요'
    if code == 'trade':
        if choice == 'accept' and W.is_pro(c.league):
            sysname = W.system_of(c.league)
            if sysname in W.SYSTEM_TEAMS:
                c.club = rng.choice([t for t, _n, _col in W.SYSTEM_TEAMS[sysname] if t != c.club])
                c.flags['trust'] = TRUST_START
                team = W.club_label(c.league, c.club)
                mods.setdefault('press', []).append(press('[트레이드]', f"{c.name}, {team} 이적…‘출전 기회 찾아’"))
                return f"{team}{josa(team, '으로/로')} 트레이드됐어요"
        bump('mental', 1, '남아서 경쟁')
        return '남아서 경쟁하기로 했어요'
    if code == 'media':
        if choice == 'accept':
            mods['train'] *= 0.8
            mods['salary'] *= 1.1
            c.flags['fame'] = round(float(c.flags.get('fame', 0)) + 6, 1)
            return '예능에 나가서 팬이 늘었어요(인기 +6)'
        mods['train'] *= 1.1
        return '야구에만 집중했어요'
    return ''


# ───────────────────────────── 성장
def grow(c, programs, intensity: str, pt: float, war: float, rng, train_mult: float = 1.0, age_keep: float = 1.0) -> dict:
    """한 해 성장 — 나이 곡선 + 훈련 + 출전 경험 + 활약. {능력: 변화}. age_keep: 노쇠 관리팀이면 나이로 빠지는 몫을 덜어 낸다."""
    _lab, mult, _inj = INTENSITY[intensity]
    plus = {}
    for code in programs:
        for k, v in dict((p[0], p[3]) for p in PROGRAMS[c.role])[code].items():
            plus[k] = plus.get(k, 0.0) + v
    if c.role == 'pitcher' and (c.flags or {}).get('starter_course'):
        plus['stamina'] = plus.get('stamina', 0) + .8
        plus['mental'] = plus.get('mental', 0) + .3
    age_train = next(v for at, v in AGE_TRAIN if c.age <= at)
    development, experience, aging, stalled = Balance.growth_factors(c)
    deltas, why = {}, {}
    for k in list(c.stats):
        s, pot = float(c.stats[k]), stat_pot(c, k)
        room = room_of(c, k)
        nat = pot * (frac(c, k, c.age + 1) - frac(c, k, c.age))
        if nat > 0:
            nat *= Balance.profile(c)['development']
        if nat < 0:
            nat *= age_keep * aging
        tr = plus.get(k, 0.0) * mult * age_train * train_mult * (1.25 if has(c, 'grinder') else 1.0)
        tr *= development
        exp = experience * math.sqrt(max(0, pt)) * (1.4 if has(c, 'learner') else 1.0)
        perf = 0.25 if war >= 4 and k in ('eye', 'mental') else 0.0
        noise = rng.gauss(0, 0.8)
        gains = [('성장', max(0.0, nat)), ('훈련', max(0.0, tr)), ('출전 경험', exp), ('활약 보너스', perf)]
        parts = gains + [('나이(노쇠)', min(0.0, nat)), ('훈련 부작용', min(0.0, tr)), ('컨디션 기복', noise)]
        if stalled:
            parts.append(('성장 정체기', -.35 * room))
        care_cut = sum(v for _l, v in gains) * (1 - Development.multiplier(c))
        if care_cut:
            parts.append(('고졸 미국 직행 적응', -care_cut))
        # 잠재력에 가까울수록 오를 몫이 깎인다 — 훈련한 능력이 왜 안 올랐는지 장부에 그대로 남긴다
        cut = (sum(v for _l, v in gains) - care_cut) * (1.0 - room)
        raw = s + sum(v for _l, v in parts) - cut
        new = _clamp(raw, 25.0, pot)
        if raw > pot:
            cut += raw - pot
        elif raw < 25.0:
            parts.append(('바닥', 25.0 - raw))
        if cut:
            parts.append(('잠재력 한계', -cut))              # 타고난 끝에 닿아 더 못 오른 몫
        deltas[k] = round(new - s, 1)
        why[k] = [(lab, v) for lab, v in parts if abs(v) >= 0.05]
        c.stats[k] = round(new, 1)
    c.ovr = R.overall(c.role, c.stats)
    c.best_ovr = max(c.best_ovr, c.ovr)
    deltas['_why'] = why
    return deltas


# ───────────────────────────── 시즌
def duty_for(c, lvl: float) -> tuple[str, int, str]:
    """시즌 보직 — 타자는 백업·하위 타선·상위/중심 타선, 투수는 선발 또는 불펜 사다리(rookie_sim 과 같은 문턱)."""
    s = c.stats
    if c.role == 'batter':
        d = c.ovr - lvl
        fit = M.upper_fit(s, lvl)
        if d >= 3 and fit:
            role, slot = fit
        elif d >= -4:
            role, slot = 'lower', 6 if d >= 0 else 7 if d >= -2 else 8
        else:
            role, slot = 'bench', 0
        return role, slot, M.BAT_ROLES[role] + (f' · {slot}번' if slot else '')
    st = M.stuff_of(s)
    if Pitching.current(c) == 'SP' and st >= lvl - 3 and float(s['stamina']) >= lvl - 4:
        rank = M.rotation_rank(s, lvl)
        return 'sp', rank, f'{rank}선발'
    role = 'mop'
    for r in M.PEN_LADDER:
        need_st, need_men = M.pen_need(r, lvl)
        if st >= need_st and float(s['mental']) >= need_men:
            role = r
    return role, 0, M.PIT_ROLES[role]


def _game_stats(c) -> dict:
    s = dict(c.stats)
    on = (c.flags or {}).get('gear_on') or {}
    if on.get('year') == c.year:                                       # 이번 시즌에 산 배트·글러브
        for k, v in (on.get('boost') or {}).items():
            if k in s:
                s[k] = float(s[k]) + v
    if has(c, 'clutch'):
        if c.role == 'batter':
            s['clutch'] = (float(s['contact']) + float(s['eye'])) / 2 + 5
        else:
            s['mental'] = float(s['mental']) + 5
    return Balance.game_stats(c, Story.game_stats(c, s))


def _chunks(code: str) -> tuple:
    return CHUNKS.get(code if code in ('hs', 'univ') else 'pro')


def _ok(role, t, G) -> bool:
    if role == 'pitcher':
        ip = t.get('outs', 0) / 3
        return ip >= G * 0.3 and L.pitching(t)['era'] <= 4.2
    return t.get('pa', 0) >= G * 1.5 and L.batting(t)['ops'] >= .720


def _short(role, t) -> str:
    if not t:
        return '-'
    if role == 'pitcher':
        p = L.pitching(t)
        bits = [f"{L.ip_text(t.get('outs', 0))}이닝", f"ERA {p['era']:.2f}" if t.get('outs') else '']
        for key, unit in (('w', '승'), ('sv', '세이브'), ('hld', '홀드'), ('so', '탈삼진')):     # '17세'는 나이로 읽혀서 풀어 쓴다
            if t.get(key):
                bits.append(f'{t[key]}{unit}')
        return ' '.join(b for b in bits if b)
    b = L.batting(t)
    return f"{L.rate(b['avg'])} {t.get('hr', 0)}홈런 {t.get('rbi', 0)}타점 OPS {L.rate(b['ops'])}"


def _hot(role, t) -> bool:
    if not t:
        return False
    if role == 'pitcher':
        return t.get('outs', 0) >= 30 and L.pitching(t)['era'] <= 2.0
    return t.get('pa', 0) >= 40 and L.batting(t)['ops'] >= 1.000


def awards_for(c, code, t, war, G, first, half, rng) -> list:
    """한 리그에서 뛴 몫의 시상. G 는 그 몫의 경기 수(시즌 중 옮기면 절반), half 는 전반기 기록(올스타)."""
    out = []
    if not t:
        return out
    scale = G / 144

    def bar(key, games=True):
        m, sd = AWARD_BARS[key]
        return rng.gauss(m, sd) * (scale if games else 1.0)

    def give(kind, label):
        out.append({'kind': kind, 'label': label})
    pit = c.role == 'pitcher'
    if code in W.TOP_LEAGUES:
        style = L.AWARD_STYLE[code]
        if half and L.war(c.role, 'SP' if pit else c.position, half) >= bar('allstar') - fame(c) / 60:   # 팬 투표
            give('allstar', '올스타')
        if war * (1.4 if pit else 1.0) >= bar('mvp'):
            give('mvp', 'MVP')
        if first and c.age <= 27 and war >= bar('rookie'):
            give('rookie', '신인왕')
        if pit:
            if style['ace'] and t.get('gs') and war >= bar('ace') and L.pitching(t)['era'] <= 2.6:
                give('ace', style['ace'])
            if style['gg_pitcher'] and war >= bar('gg_pit'):
                give('gg', f"{style['gg']} 투수")
            ip = t.get('outs', 0) / 3
            if t.get('w', 0) >= bar('w'):
                give('title', '다승왕')
            if ip >= G and L.pitching(t)['era'] <= bar('era', False):
                give('title', '평균자책점 1위')
            if t.get('so', 0) >= bar('so'):
                give('title', '탈삼진왕')
            if t.get('sv', 0) >= bar('sv'):
                give('title', '세이브왕')
            if t.get('hld', 0) >= bar('hld'):
                give('title', '홀드왕')
        else:
            if war >= bar('gg_bat'):
                give('gg', f"{style['gg']} {L.POS_LABEL.get(c.position, '')}")
            b = L.batting(t)
            if t.get('pa', 0) >= 3.1 * G and b['avg'] >= bar('avg', False):
                give('title', '타격왕')
            if t.get('hr', 0) >= bar('hr'):
                give('title', '홈런왕')
            if t.get('rbi', 0) >= bar('rbi'):
                give('title', '타점왕')
            if t.get('sb', 0) >= bar('sb'):
                give('title', '도루왕')
    elif W.is_pro(code):
        if war * (1.4 if pit else 1.0) >= bar('minor'):
            give('minor', L.MINOR_MVP.get(code, f'{W.short(code)} MVP'))
    else:
        if pit:
            p = L.pitching(t)
            if t.get('outs', 0) / 3 >= G * 0.9 and p['era'] <= rng.gauss(1.6, 0.3):
                give('minor', f'{W.short(code)} 최우수선수')
                give('title', '우수투수상')
        else:
            b = L.batting(t)
            if t.get('pa', 0) >= G * 2.5 and b['ops'] >= rng.gauss(1.050, 0.06):
                give('minor', f'{W.short(code)} 최우수선수')
            if t.get('pa', 0) >= G * 2.5 and b['avg'] >= rng.gauss(.420, .02):
                give('title', '타격상')
            if t.get('hr', 0) >= rng.gauss(6, 1) * G / 30:
                give('title', '홈런상')
    return out


def salary_for(c, war: float, mult: float = 1.0, splits=None) -> int:
    """만원. 계약(FA·해외)이 있으면 그 연봉, 없으면 리그·지난 활약 기준."""
    code = c.league
    if not W.is_pro(code):
        return 0
    deal = (c.flags or {}).get('contract')
    if deal and deal.get('years', 0) > 0:
        if Contracts.active(c):
            return Contracts.salary(deal, splits=splits, league=c.league)
        return int(deal['annual'] * mult)
    _totals, recent_war, _games = Balance.recent(c, W.system_of(code))
    service = (c.flags or {}).get('top_service', {}).get(code, 0)
    return int(Balance.annual(c, code, recent_war, service) * mult)


# ───────────────────────────── 돈·상점·인기(2026-10-18 사용자 요청: 번 돈으로 집·배트·보호대·액세서리)
# 보유 현금 = flags['cash'](없으면 통산 수입 — 예전 판은 번 돈을 모두 모아 둔 셈). 금액은 모두 만원.
GEAR = {   # 소모품 — 이번 시즌만 쓴다(시즌마다 다시 산다). 투수는 배트 대신 글러브
    'bat': {'name': {'batter': '배트', 'pitcher': '글러브'},
            'tiers': (('pro', '프로 모델', 500, 1.0), ('craft', '장인 수제', 2000, 2.0)),
            'stats': {'batter': ('contact', 'power'), 'pitcher': ('control', 'breaking')}},
    'guard': {'name': {'batter': '보호대', 'pitcher': '보호대'},
              'tiers': (('basic', '기본', 300, 0.04), ('fit', '맞춤', 1200, 0.08))},
}
HOUSE = {'dorm': ('구단 숙소', 0, 0, 0.0), 'rent': ('구단 근처 아파트 월세', 0, 3000, 0.03),
         'own': ('내 집 마련(매매)', 100000, 0, 0.05)}            # (이름, 매매가, 시즌마다 월세, 부상 위험을 줄이는 몫) — 값은 리그 물가를 곱한다
# 2026-10-19 밸런스(사용자 지적: 장비를 다 사면 절대 안 다친다) — 예전엔 보호대 25%·집 25%를 곱해 44%까지 줄었고,
# 강철 체력·가볍게와 겹치면 1%대였다. 장비·집은 더해서 최대치까지만, 어떤 경우에도 2%는 남는다.
# 2차(같은 날, 사용자: 아직도 사기 — 의존도를 낮추고, 리그가 오를수록 값이 부담스럽게, 돈 쓸 곳을 훨씬 많이):
# 보호대·집 몫을 절반으로, 최대 25% → 12%. 값은 리그 물가(PRICE_LEAGUE)를 곱한다 — 측정(40판): 예전엔 퓨처스 선수도 85%가
# 장비를 다 샀고 1군·해외는 100%, 은퇴 때 현금 중앙값 38억·상위 10% 1,402억이 그대로 남았다.
GEAR_CUT_MAX = 0.12
INJURY_FLOOR = 0.02
PRICE_LEAGUE = {'kbo3': 1.0, 'kbo2': 1.2, 'mlb_a': 1.0, 'mlb_aa': 1.2, 'mlb_aaa': 1.5, 'npb2': 1.5, 'cpbl': 2.5,
                'kbo1': 4.0, 'npb1': 15.0, 'mlb': 40.0}            # 리그 물가 — 같은 물건도 큰 무대일수록 비싸다(연봉 차이만큼)
ACCESSORY = {'chain': ('금목걸이', 20000, 4), 'earring': ('다이아 귀걸이', 80000, 7),
             'watch': ('한정판 명품 시계', 250000, 12)}              # (이름, 값, 인기 +) — 한 번 사면 평생. 값은 리그 물가의 1/4을 곱한다
# 돈 쓸 곳(2026-10-19 사용자 요청) — 값은 모두 리그 물가를 곱한다(만원).
CARE = {   # 관리팀 — 비시즌에 계약하면 다음 시즌 하나만(시즌마다 다시)
    'trainer': ('개인 트레이너', 1500, '이번 비시즌 훈련 효과 +10%'),
    'physio': ('전담 물리치료사', 1000, '다치면 결장 기간이 절반, 큰 부상도 가볍게'),
    'aging': ('노쇠 관리팀', 2500, '이번 시즌 나이로 빠지는 능력 −30%(영양사·필라테스)'),
}
CARE_TRAIN, CARE_AGE = 1.10, 0.70
CAMP = ('해외 전지훈련', 4000, 1.0)     # 비시즌에 한 번 — 고른 능력 +1(잠재력 한계까지)
FAN = ('팬 감사 이벤트', 2000, 3)        # 비시즌에 한 번 — 인기 +3(시간이 지나면 잊힌다)
GIVE = {   # 나눔 — 평생 한 번씩, 인기(평생)와 기사
    'school': ('모교에 장학금 기부', 5000, 3, '[미담]', '{nm}, 모교 후배들에게 장학금…‘받은 만큼 돌려주고 싶었다’'),
    'parents': ('부모님께 집 선물', 25000, 2, '[미담]', '효자 {nm}, 부모님께 집 선물…‘이제 제가 모실게요’'),
    'foundation': ('유소년 야구 재단 설립', 60000, 8, '[단독]', '{nm}, 사재 털어 유소년 야구 재단 설립…‘제2의 {nm} 키운다’'),
}
INVEST_SHARE, INVEST_MIN = 0.2, 5000    # 지인 사업 투자 — 보유 현금의 20%(5,000만원 이상 있을 때)
INVEST_OUT = ((2.0, .25, '대박'), (1.0, .30, '본전'), (0.5, .25, '반토막'), (0.0, .20, '쪽박'))   # 기대값 0.925 — 평균 7.5% 잃는다
TAX = ((1400, .06), (5000, .15), (8800, .24), (15000, .35), (30000, .38), (50000, .40), (100000, .42), (None, .45))   # 종합소득세(만원)


def price_of(c, base: int, league: str | None = None) -> int:
    """리그 물가를 곱한 값(만원, 100만원 단위)."""
    return int(round(base * PRICE_LEAGUE.get(league or c.league, 1.0) / 100.0)) * 100


def acc_price(c, base: int) -> int:
    return int(round(base * max(1.0, PRICE_LEAGUE.get(c.league, 1.0) / 4) / 100.0)) * 100


def income_tax(income: int) -> int:
    """연봉·광고 수입에 붙는 세금(만원) — 구간마다 세율이 오른다."""
    tax, low = 0.0, 0
    for top, rate in TAX:
        if top is None or income <= top:
            tax += max(0, income - low) * rate
            break
        tax += (top - low) * rate
        low = top
    return int(tax // 10 * 10)
ACC_STOCK = 0.25            # 비시즌마다 한정품이 매장에 들어올 확률(프로만)
FAME_LEAGUE = {'mlb': 1.5, 'npb1': 1.1, 'kbo1': 1.0, 'cpbl': 0.7}
FAME_AWARD = {'mvp': 10, 'rookie': 4, 'gg': 4, 'ace': 5, 'title': 3, 'allstar': 2, 'ring': 3, 'national': 2, 'minor': 1}
FAME_KEEP = 0.82            # 해마다 인기의 18%는 잊힌다
AD_MULT = {'mlb': 4.0, 'npb': 1.6, 'kbo': 1.0, 'cpbl': 0.6}
FAME_LABEL = ((85, '월드 스타'), (60, '국민 스타'), (35, '전국구'), (15, '지역 스타'), (0, '무명'))


def cash(c) -> int:
    f = c.flags or {}
    return int(f['cash']) if 'cash' in f else int(c.earnings or 0)


def _spend(c, amount: int, what: str):
    have = cash(c)
    if amount > have:
        raise LiteError(f"{what}{josa(what, '을/를')} 사기엔 돈이 모자라요. 보유 현금은 {man(have)}이에요.")
    c.flags = dict(c.flags or {})
    c.flags['cash'] = have - amount


def _fame_of(flags: dict) -> int:
    bonus = sum(ACCESSORY[a][2] for a in flags.get('acc') or [] if a in ACCESSORY)
    bonus += sum(GIVE[g][2] for g in flags.get('give') or [] if g in GIVE)
    return int(round(_clamp(float(flags.get('fame', 0)) + bonus, 0, 100)))


def fame(c) -> int:
    """인기(0~100) — 성적·수상으로 쌓이고 해마다 조금씩 잊힌다. 액세서리는 평생 더해 준다."""
    return _fame_of(c.flags or {})


def fame_label(v: int) -> str:
    return next(lab for at, lab in FAME_LABEL if v >= at)


def fame_after(flags: dict, season) -> float:
    """시즌을 마친 뒤의 인기(액세서리 몫 빼고) — 무대가 클수록, 상을 받을수록."""
    k = FAME_LEAGUE.get(season.league, 0.3 if W.is_pro(season.league) else 0.15)
    gain = max(0.0, season.war) * 1.5 * k + sum(FAME_AWARD.get(a['kind'], 0) for a in season.awards or [])
    gain += sum(4 for a in season.awards or [] if a['kind'] == 'national' and ('금메달' in a['label'] or a['label'].endswith('우승')))
    return round(_clamp(float(flags.get('fame', 0)) * FAME_KEEP + gain, 0, 100), 1)


def ad_income(flags: dict, league: str) -> int:
    """광고 수입(만원) — 인기 25부터. 메이저리그면 몸값이 다르다."""
    f = _fame_of(flags)
    if not W.is_pro(league) or f < 25:
        return 0
    return int((f - 20) ** 2 * 3 * AD_MULT.get(W.system_of(league), 1.0)) // 100 * 100


def gear_cut(c, gear=None, house=None) -> float:
    """장비·집이 부상 위험에 곱하는 값(0.75~1) — 보호대와 집의 몫을 더하되 GEAR_CUT_MAX 까지만."""
    house = house or (c.flags or {}).get('house', 'dorm')
    gear = _gear_now(c) if gear is None else gear
    cut = HOUSE.get(house, HOUSE['dorm'])[3]
    if gear.get('guard'):
        cut += dict((t[0], t[3]) for t in GEAR['guard']['tiers'])[gear['guard']]
    return 1.0 - min(GEAR_CUT_MAX, cut)


def injury_odds(c, intensity: str, extra: float = 0.0, cut: float | None = None, known_only: bool = False) -> float:
    """이번 시즌 부상 확률 — 강도·나이·특성·장비·집. known_only 면 드러나지 않은 특성은 빼고(화면에 숨은 특성이 새지 않게)."""
    traits = (c.traits_seen or []) if known_only else (c.traits or [])
    p = INTENSITY[intensity][2] + max(0, c.age - (DECLINE_FROM - 1)) * 0.01 + extra
    p *= 0.5 if 'iron' in traits else 1.8 if 'glass' in traits else 1.0
    p *= gear_cut(c) if cut is None else cut
    p *= 1 + (50 - Story.value(c, 'discipline')) * .001
    p += float((c.flags or {}).get('workload', 0)) * .025
    return max(INJURY_FLOOR, p)


def _gear_now(c) -> dict:
    g = (c.flags or {}).get('gear') or {}
    return g if g.get('year') == c.year else {}


def _effect(c, key: str, v: float) -> str:
    if key == 'bat':
        labels = dict((k, lab) for k, lab, _w in R.ROLES[c.role]['stats'])
        return f"이번 시즌 경기에서 {'·'.join(labels[k] for k in GEAR['bat']['stats'][c.role])} +{v:g}"
    return f'이번 시즌 부상 위험 −{int(v * 100)}%'


def shop_view(c) -> dict:
    """비시즌 상점 화면 — 보유 현금, 이번 시즌 장비, 집, 들어온 한정품."""
    f = c.flags or {}
    have, gear = cash(c), _gear_now(c)
    rows = []
    for key, g in GEAR.items():
        order = [t[0] for t in g['tiers']]
        mine = gear.get(key)
        rows.append({'key': key, 'name': g['name'][c.role], 'mine': dict((t[0], t[1]) for t in g['tiers']).get(mine, ''),
                     'tiers': [{'code': code, 'label': f"{lab} {g['name'][c.role]}" if key == 'bat' else f'{lab} 보호대',
                                'price': man(price_of(c, price)), 'cost': price_of(c, price), 'effect': _effect(c, key, v), 'own': code == mine,
                                'can': price_of(c, price) <= have and (not mine or order.index(code) > order.index(mine)),
                                'why': ('own' if code == mine else 'lower' if mine and order.index(code) < order.index(mine)
                                        else 'poor' if price_of(c, price) > have else '')}
                               for code, lab, price, v in g['tiers']]})
    house = f.get('house', 'dorm')
    houses = []
    for code, (lab, buy_, rent_, cut) in HOUSE.items():
        buy_p, rent_p = price_of(c, buy_), price_of(c, rent_)
        houses.append({'code': code, 'label': lab, 'own': code == house,
                       'price': man(buy_p) if buy_p else (f'시즌마다 {man(rent_p)}' if rent_p else '무료'),
                       'effect': f'부상 위험 −{int(cut * 100)}%' + ('(평생)' if code == 'own' else '') if cut else '부상 위험 그대로',
                       'can': code != house and house != 'own' and (buy_p <= have) and (code != 'rent' or rent_p <= have),
                       'why': ('now' if code == house else 'owned' if house == 'own'
                               else 'poor' if buy_p > have or (code == 'rent' and rent_p > have) else '')})
    stock = (c.pending or {}).get('shop')
    item = None
    if stock in ACCESSORY and stock not in (f.get('acc') or []):
        name, price, plus = ACCESSORY[stock]
        item = {'code': stock, 'name': name, 'price': man(acc_price(c, price)), 'plus': plus, 'can': acc_price(c, price) <= have}
    owned = [ACCESSORY[a][0] for a in f.get('acc') or [] if a in ACCESSORY]
    v = fame(c)

    def row(item_, code, label, base, effect, done):
        p = price_of(c, base)
        return {'item': item_, 'code': code, 'label': label, 'price': man(p), 'cost': p, 'effect': effect,
                'can': not done and p <= have, 'why': 'done' if done else 'poor' if p > have else ''}
    care_now = _care_now(c)
    care = [row('care', k, lab, base, eff, bool(care_now.get(k))) for k, (lab, base, eff) in CARE.items()]
    labels = dict((k, lab) for k, lab, _w in R.ROLES[c.role]['stats'])
    camp = dict(row('camp', '', CAMP[0], CAMP[1], f'고른 능력 +{CAMP[2]:g}(잠재력 한계까지)', f.get('camp') == c.year),
                stats=[{'key': k, 'label': labels[k], 'room': round(stat_pot(c, k) - float(c.stats[k]), 1)} for k in labels])
    fan = row('fan', '', FAN[0], FAN[1], f'인기 +{FAN[2]}(시간이 지나면 잊혀요)', f.get('fan') == c.year)
    gives = [row('give', k, lab, base, f'인기 +{plus}(평생) · 기사', k in (f.get('give') or []))
             for k, (lab, base, plus, _t, _h) in GIVE.items()]
    inv = f.get('invest')
    invest = {'amount': man(int(have * INVEST_SHARE)), 'can': have >= INVEST_MIN and not inv,
              'open': man(inv['amount']) if inv else '', 'why': 'open' if inv else 'poor' if have < INVEST_MIN else ''}
    return {'cash': man(have), 'pro': W.is_pro(c.league), 'gear': rows, 'house': HOUSE.get(house, HOUSE['dorm'])[0],
            'houses': houses, 'stock': item, 'owned': owned, 'fame': v, 'fame_label': fame_label(v),
            'price_x': f"{PRICE_LEAGUE.get(c.league, 1.0):g}", 'cut_max': int(GEAR_CUT_MAX * 100),
            'plan': plan_state(c), 'plan_cost': man(plan_state(c)['spend']), 'cash_raw': have, 'care': care, 'camp': camp, 'fan': fan, 'gives': gives, 'invest': invest,
            'given': [GIVE[g][0] for g in f.get('give') or [] if g in GIVE]}


def plan_state(c) -> dict:
    """한 번에 사기 화면의 체크 상태 — 저장해 둔 계획(flags['shop_plan'])을 이어받되, 이미 샀거나 돈이 모자라 못 사는 칸은 풀린다
    (2026-10-19 사용자 요청: 매년 하나씩 누르기 번거롭다). 앞 칸부터 값을 더해 가며 현금 안에서만 체크가 남는다."""
    f = c.flags or {}
    plan = f.get('shop_plan') or {}
    have = left = cash(c)
    gear, care = _gear_now(c), _care_now(c)
    out = {'bat': '', 'guard': '', 'care': [], 'fan': False, 'camp': ''}

    def take(price: int) -> bool:
        nonlocal left
        if price <= left:
            left -= price
            return True
        return False
    for key in ('bat', 'guard'):
        want = plan.get(key) or ''
        tiers = {t[0]: t for t in GEAR[key]['tiers']}
        order = [t[0] for t in GEAR[key]['tiers']]
        mine = gear.get(key)
        if want in tiers and not (mine and order.index(want) <= order.index(mine)) and take(price_of(c, tiers[want][2])):
            out[key] = want
    for k in CARE:
        if k in (plan.get('care') or []) and not care.get(k) and take(price_of(c, CARE[k][1])):
            out['care'].append(k)
    if plan.get('fan') and f.get('fan') != c.year and take(price_of(c, FAN[1])):
        out['fan'] = True
    camp = plan.get('camp') or ''
    if camp in c.stats and f.get('camp') != c.year and stat_pot(c, camp) - float(c.stats[camp]) > 0 and take(price_of(c, CAMP[1])):
        out['camp'] = camp
    out['spend'] = have - left
    return out


def buy_plan(c, form: dict) -> str:
    """체크한 것을 한 번에 산다 — 계획은 저장해 다음 해에도 체크된 채로 열린다. 돈이 모자란 칸은 건너뛴다."""
    if (c.pending or {}).get('kind') != 'plan':
        raise LiteError('상점은 비시즌에만 열려요.')
    if not W.is_pro(c.league):
        raise LiteError('프로가 되면 연봉으로 쓸 수 있어요.')
    want = {'bat': form.get('bat') or '', 'guard': form.get('guard') or '',
            'care': [k for k in form.get('care') or [] if k in CARE], 'fan': bool(form.get('fan')),
            'camp': form.get('camp') if form.get('camp_on') and form.get('camp') in c.stats else ''}
    c.flags = dict(c.flags or {}, shop_plan=want)
    jobs = ([('bat', want['bat'])] if want['bat'] else []) + ([('guard', want['guard'])] if want['guard'] else []) \
        + [('care', k) for k in want['care']] + ([('fan', '')] if want['fan'] else []) + ([('camp', want['camp'])] if want['camp'] else [])
    done, skipped = 0, 0
    for item, code in jobs:
        try:
            buy(c, item, code)
            done += 1
        except LiteError as ex:
            skipped += '모자라' in str(ex)
    parts = ([f'{done}가지를 샀어요'] if done else []) + ([f'돈이 모자라 {skipped}가지는 건너뛰었어요'] if skipped else [])
    return ' · '.join(parts) or '새로 살 것이 없어요'


def _care_now(c) -> dict:
    g = (c.flags or {}).get('care') or {}
    return g if g.get('year') == c.year else {}


def buy(c, item: str, code: str) -> str:
    """상점에서 사기 — 비시즌에만. 고친 c 와 소식 문장(저장은 부른 쪽)."""
    if (c.pending or {}).get('kind') != 'plan':
        raise LiteError('상점은 비시즌에만 열려요.')
    f = c.flags = dict(c.flags or {})
    if item in GEAR:
        g = GEAR[item]
        tiers = {t[0]: t for t in g['tiers']}
        if code not in tiers:
            raise LiteError('살 물건을 다시 골라 주세요.')
        gear = dict(_gear_now(c)) or {'year': c.year}
        order = [t[0] for t in g['tiers']]
        if gear.get(item) and order.index(gear[item]) >= order.index(code):
            raise LiteError('이번 시즌에 쓸 것은 이미 샀어요.')
        _code, lab, price, v = tiers[code]
        name = f"{lab} {g['name'][c.role]}" if item == 'bat' else f'{lab} 보호대'
        _spend(c, price_of(c, price), name)
        gear[item] = code
        c.flags['gear'] = gear
        return f"{name}{josa(name, '을/를')} 샀어요 — {_effect(c, item, v)}"
    if item == 'house':
        now = f.get('house', 'dorm')
        if code not in HOUSE or code == now:
            raise LiteError('집을 다시 골라 주세요.')
        if now == 'own':
            raise LiteError('이미 내 집이 있어요.')
        lab, price, rent, _cut = HOUSE[code]
        price, rent = price_of(c, price), price_of(c, rent)
        if code == 'own':
            _spend(c, price, '집')
            c.flags['house'] = 'own'
            return f'내 집을 마련했어요! {man(price)}이 나갔어요'
        if code == 'rent' and rent > cash(c):
            raise LiteError(f'월세 {man(rent)}을 낼 돈이 모자라요.')
        c.flags['house'] = code
        return (f'{lab}에 들어가요 — 시즌을 시작할 때마다 {man(rent)}이 나가요' if code == 'rent'
                else '구단 숙소로 돌아갔어요 — 월세가 더 나가지 않아요')
    if item == 'acc':
        stock = (c.pending or {}).get('shop')
        if code != stock or code not in ACCESSORY or code in (f.get('acc') or []):
            raise LiteError('지금 매장에 없는 물건이에요.')
        name, price, plus = ACCESSORY[code]
        _spend(c, acc_price(c, price), name)
        c.flags['acc'] = list(f.get('acc') or []) + [code]
        c.pending = dict(c.pending, shop=None)
        return f"{name}{josa(name, '을/를')} 샀어요 — 인기 +{plus}(평생)"
    if not W.is_pro(c.league):
        raise LiteError('프로가 되면 연봉으로 쓸 수 있어요.')
    if item == 'care':
        if code not in CARE:
            raise LiteError('계약할 사람을 다시 골라 주세요.')
        now = dict(_care_now(c)) or {'year': c.year}
        if now.get(code):
            raise LiteError('이번 시즌엔 이미 계약했어요.')
        lab, base, eff = CARE[code]
        _spend(c, price_of(c, base), lab)
        now[code] = True
        c.flags['care'] = now
        return f"{lab}{josa(lab, '와/과')} 계약했어요 — {eff}"
    if item == 'camp':
        labels = dict((k, lab) for k, lab, _w in R.ROLES[c.role]['stats'])
        if code not in labels:
            raise LiteError('전지훈련에서 키울 능력을 골라 주세요.')
        if f.get('camp') == c.year:
            raise LiteError('이번 비시즌엔 이미 다녀왔어요.')
        _spend(c, price_of(c, CAMP[1]), CAMP[0])
        old = float(c.stats[code])
        c.stats[code] = round(max(old, min(stat_pot(c, code), old + CAMP[2])), 1)
        c.ovr = R.overall(c.role, c.stats)
        c.flags['camp'] = c.year
        up = round(c.stats[code] - old, 1)
        return (f"해외 전지훈련을 다녀왔어요 — {labels[code]} +{up:g}" if up > 0
                else f"해외 전지훈련을 다녀왔지만 {labels[code]}{josa(labels[code], '은/는')} 이미 잠재력 끝이에요")
    if item == 'fan':
        if f.get('fan') == c.year:
            raise LiteError('팬 감사 이벤트는 비시즌에 한 번이에요.')
        _spend(c, price_of(c, FAN[1]), FAN[0])
        c.flags['fan'] = c.year
        c.flags['fame'] = round(_clamp(float(f.get('fame', 0)) + FAN[2], 0, 100), 1)
        return f'팬 감사 이벤트를 열었어요 — 인기 +{FAN[2]}'
    if item == 'give':
        if code not in GIVE or code in (f.get('give') or []):
            raise LiteError('이미 했거나 없는 나눔이에요.')
        lab, base, plus, tag, head = GIVE[code]
        _spend(c, price_of(c, base), lab)
        c.flags['give'] = list(f.get('give') or []) + [code]
        c.flags['press'] = list(f.get('press') or []) + [press(tag, head.format(nm=c.name))]
        return f'{lab} — {man(price_of(c, base))}, 인기 +{plus}(평생)'
    if item == 'invest':
        if f.get('invest'):
            raise LiteError('맡긴 돈의 결과가 아직 안 나왔어요. 시즌이 끝나면 알려 줄게요.')
        have = cash(c)
        if have < INVEST_MIN:
            raise LiteError(f'투자하려면 현금이 {man(INVEST_MIN)} 이상 있어야 해요.')
        amount = int(have * INVEST_SHARE)
        _spend(c, amount, '투자')
        c.flags['invest'] = {'year': c.year, 'amount': amount}
        return f'지인 사업에 {man(amount)}을 맡겼어요 — 결과는 시즌이 끝나면 나와요'
    raise LiteError('살 물건을 다시 골라 주세요.')


# ───────────────────────────── 조사(받침에 따라)
_LETTER_BATCHIM = set('LMNRlmnr')
_DIGIT_BATCHIM = {'0': 'ㅇ', '1': 'ㄹ', '3': 'ㅁ', '6': 'ㄱ', '7': 'ㄹ', '8': 'ㄹ'}


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사 — pair '이/가'·'을/를'·'은/는'·'와/과'·'으로/로'. 괄호 안 글자는 빼고 본다."""
    w = (word or '').split('(')[0].rstrip(' ‘’\'"')
    ch = w[-1:] if w else ''
    batchim, rieul = False, False
    if '가' <= ch <= '힣':
        jong = (ord(ch) - 0xAC00) % 28
        batchim, rieul = jong != 0, jong == 8
    elif ch in _DIGIT_BATCHIM:
        batchim, rieul = True, _DIGIT_BATCHIM[ch] == 'ㄹ'
    elif ch in _LETTER_BATCHIM:
        batchim, rieul = True, ch in 'LRlr'
    first, second = pair.split('/')
    if pair == '으로/로':
        return '로' if (not batchim or rieul) else '으로'
    if pair in ('이/가', '을/를', '은/는', '과/와'):
        return first if batchim else second
    return second if batchim else first          # '와/과' 처럼 받침 없는 쪽을 앞에 쓴 경우


# ───────────────────────────── 훈련 가드레일(같은 판을 똑같이 돌리지 않게, 2026-10-18 사용자 요청)
def train_rules(c) -> dict:
    """같은 훈련은 연속 3번 금지 — 지난 두 비시즌에 모두 고른 훈련은 이번에 잠긴다. 같은 조합은 연속 2번 금지."""
    log = [sorted(x) for x in ((c.flags or {}).get('train_log') or [])][-2:]
    locked = sorted(set(log[-1]) & set(log[-2])) if len(log) >= 2 else []
    return {'locked': locked, 'banned': log[-1] if log else []}


def check_programs(c, programs) -> list:
    valid = {p[0]: p[1] for p in PROGRAMS[c.role]}
    progs = sorted({p for p in programs if p in valid})
    if len(progs) != 2:
        raise LiteError('훈련 프로그램을 꼭 두 개 골라 주세요.')
    rules = train_rules(c)
    for p in progs:
        if p in rules['locked']:
            raise LiteError(f'‘{valid[p]}’ 훈련은 두 비시즌 연속으로 했어요. 이번엔 다른 훈련을 골라 주세요.')
    if progs == rules['banned']:
        raise LiteError('지난 비시즌과 똑같은 조합이에요. 하나는 바꿔 주세요.')
    return progs


def pick_programs(c, rng) -> list:
    """규칙 안에서 아무 조합 — 자동 진행(테스트·하네스)용."""
    rules = train_rules(c)
    pool = [p[0] for p in PROGRAMS[c.role] if p[0] not in rules['locked']]
    while True:
        progs = sorted(rng.sample(pool, 2))
        if progs != rules['banned']:
            return progs


# ───────────────────────────── 달력·국가대표(2026-10-18 사용자 요청: 아시안게임·WBC·프리미어12, 올림픽 금메달 병역 면제)
def cal_year(c, year: int | None = None) -> int:
    """시즌의 달력 연도 — 고1 시즌이 선수를 만든 해."""
    return int((c.flags or {}).get('start') or BASE_YEAR) + (year or c.year) - 1


INTL = {   # 게임 속 일정(첫 해·주기). tiers = (코드, 결과, 누적 확률) — 내가 강할수록 위로 조금 당긴다
    'wbc': {'name': 'WBC', 'when': 'pre', 'month': '3월', 'first': 2026, 'every': 3, 'need': 4.0, 'games': 7,
            'injury': 0.04, 'tiers': (('champ', '우승', .07), ('final', '준우승', .15), ('semi', '4강', .32),
                                      ('quarter', '8강', .62), ('out', '1라운드 탈락', 1.0))},
    'olympics': {'name': '올림픽', 'when': 'mid', 'month': '8월', 'first': 2028, 'every': 4, 'need': 2.5, 'games': 6,
                 'injury': 0.03, 'exempt': True,
                 'tiers': (('gold', '금메달', .17), ('silver', '은메달', .33), ('bronze', '동메달', .52), ('out', '노메달', 1.0))},
    'asian': {'name': '아시안게임', 'when': 'mid', 'month': '9월', 'first': 2026, 'every': 4, 'need': 2.5, 'young': 25,
              'wild': 7.0, 'games': 5, 'injury': 0.03, 'exempt': True,
              'tiers': (('gold', '금메달', .55), ('silver', '은메달', .78), ('bronze', '동메달', .92), ('out', '노메달', 1.0))},
    'premier12': {'name': '프리미어12', 'when': 'post', 'month': '11월', 'first': 2027, 'every': 4, 'need': 2.5, 'games': 8,
                  'injury': 0.03, 'tiers': (('champ', '우승', .18), ('final', '준우승', .34), ('semi', '4강', .56),
                                            ('out', '슈퍼라운드 탈락', 1.0))},
}
INTL_LEVEL = 69.0                 # 국제대회 상대 수준(KBO + 5)
INTL_TOP = ('champ', 'gold', 'final', 'silver')


def intl_this_year(c) -> list:
    y = cal_year(c)
    return [k for k, t in INTL.items() if y >= t['first'] and (y - t['first']) % t['every'] == 0]


def intl_offers(c) -> list:
    """올해 대표팀에 뽑히는 대회 — 프로(해외 포함), 현역 복무 중 제외. 아시안게임은 25세 이하 + 와일드카드."""
    flags = c.flags or {}
    if not W.is_pro(c.league) or (flags.get('army') or {}).get('kind') == 'active':
        return []
    base, out = W.level('kbo1'), []
    for k in intl_this_year(c):
        t = INTL[k]
        if k == 'asian':
            ok = (c.age <= t['young'] and c.ovr >= base + t['need']) or c.ovr >= base + t['wild']
        else:
            ok = c.ovr >= base + t['need']
        if ok:
            out.append(k)
    return out


def intl_view(c, keys) -> list:
    flags = c.flags or {}
    free = not flags.get('served') and not flags.get('exempt')
    return [{'key': k, 'name': INTL[k]['name'], 'month': INTL[k]['month'], 'when': INTL[k]['when'],
             'risk': int(round(INTL[k]['injury'] * 100)), 'exempt': bool(INTL[k].get('exempt')) and free,
             'reward': '참가 인기 +6 · 국제 평판 +3 · 대회 수당, 상위 성적이면 추가 보상'} for k in keys]


def play_intl(c, key, rng) -> dict:
    """대표팀으로 한 대회 — 내 성적과 대한민국 성적."""
    t = INTL[key]
    s = _game_stats(c)
    role, slot, _d = duty_for(c, INTL_LEVEL)
    tot = {}
    for i in range(t['games']):
        r = None
        if c.role == 'batter':
            r = M.batter_game(s, c.position, INTL_LEVEL, rng, role=role if role != 'bench' else 'lower', slot=slot or 7)
        elif role == 'sp':
            if i % 3 == 0:
                r = M.starter_game(s, INTL_LEVEL, rng)
        elif rng.random() < 0.55:
            r = M.relief_game(s, INTL_LEVEL, rng, role)
        if r:
            tot = L.add(tot, r['line'])
    u = rng.random() - _clamp(0.015 * (c.ovr - INTL_LEVEL + 2), -0.05, 0.10)
    code, label = t['tiers'][-1][:2]
    for tc, tl, cum in t['tiers']:
        if u < cum:
            code, label = tc, tl
            break
    return {'key': key, 'name': t['name'], 'tier': code, 'result': label, 'line': _short(c.role, tot)}


def national_reward(c, key, tier):
    """게임 안의 대표팀 보상. 대회 참가와 최종 성적은 각각 한 번만 지급한다."""
    marker = f'{c.year}:{key}:{"entry" if tier == "entry" else "result"}'
    flags = dict(c.flags or {})
    seen = list(flags.get('national_rewarded') or [])
    if marker in seen:
        return ''
    seen.append(marker)
    flags['national_rewarded'] = seen[-200:]
    base = {'wbc': 3000, 'premier12': 2000, 'olympics': 1500, 'asian': 1000}[key]
    standing = {'champ': 3, 'gold': 3, 'final': 2, 'silver': 2, 'semi': 1, 'bronze': 1}.get(tier, 0)
    money = base if tier == 'entry' else base * standing
    flags['cash'] = cash(c) + money
    c.earnings += money
    Story.put(c, flags)
    gain = 6 if tier == 'entry' else 6 * standing
    text = Story.change(c, f'{INTL[key]["name"]} ' + ('참가 보상' if tier == 'entry' else '성적 보상'),
                        fame=gain, intl_rep=3 if tier == 'entry' else standing * 2,
                        confidence=2 if tier == 'entry' else standing * 2)
    return text + (f' · 대회 수당 {man(money)}' if money else '')


def _intl(c, key, state, rng):
    """대회 하나를 치르고 그 결과를 이번 시즌에 반영 — 부상 위험·멘탈·병역 특례·기사."""
    t, nm = INTL[key], c.name
    res = play_intl(c, key, rng)
    reward = national_reward(c, key, 'entry')
    state['news'].append(reward)
    if not res.get('final') and res['tier'] not in INTL_TOP:
        state['news'].append(national_reward(c, key, res['tier']))
    if res['tier'] in ('gold', 'silver', 'champ', 'final'):
        res['final'] = True                                   # 결승 — 메달 색은 결정적 순간에서
    state['intl'].append(res)
    if t['when'] == 'post':                                   # 시즌 뒤(11월) — 다음 시즌 몸이 무겁다
        c.flags['tired'] = {'injury': t['injury'], 'train': 0.9}
    else:
        state['mods']['injury'] += t['injury']
    if res['tier'] in INTL_TOP:
        k = 'mental' if c.role == 'pitcher' else 'eye'
        old = float(c.stats[k])
        c.stats[k] = round(min(stat_pot(c, k) + 2, old + 1.0), 1)
        _note(c, k, c.stats[k] - old, f"{t['name']} 큰 무대 경험")
    if res.get('final'):
        title = f"대한민국 결승 진출!…{nm} 태극마크 투혼"
    elif res['tier'] == 'out':
        title = f"대한민국 {res['result']}…{nm}도 고개 숙여"
    else:
        title = f"대한민국 {res['result']}…{nm} 태극마크 투혼"
    state['press'].append(press(f"[{t['name']}]", title, res['line']))
    state['news'].append(f"{t['month']} {t['name']} 국가대표 — 대한민국 {'결승 진출' if res.get('final') else res['result']}")
    flags = c.flags
    if t.get('exempt') and res['tier'] == 'gold' and not res.get('final') and not flags.get('served') \
            and not flags.get('exempt') and not flags.get('army'):
        flags['exempt'] = True
        state['press'].append(press('[오피셜]', f"{nm}, {t['name']} 금메달로 병역 특례…‘꿈같은 하루’"))
        state['news'].append(f"{t['name']} 금메달로 병역 특례를 받았어요")


# ───────────────────────────── 감독 신뢰·면담(2026-10-18 사용자 요청: 보직 변경·강등·승격 때 면담, 고집은 역효과)
TRUST_START = 50
LG_OPS, LG_ERA = .750, 4.40               # 리그 수준과 같은 선수의 평균(rookie_sim 표본)
ROLE_TIER = {'bench': 0, 'lower': 1, 'mop': 0, 'chase': 0, 'win': 1, 'setup': 1, 'closer': 2, 'sp': 2}


def trust(c) -> int:
    return int((c.flags or {}).get('trust', TRUST_START))


def _trust(c, d: int):
    c.flags['trust'] = int(_clamp(trust(c) + d, 0, 100))


def role_tier(code: str) -> int:
    return ROLE_TIER.get(code, 2)                         # 타자 상위·중심 타선(테이블세터·교타자·거포·5툴)은 2


def _role_text(c, role: str, slot: int, lvl: float) -> str:
    if c.role == 'batter':
        return M.BAT_ROLES[role] + (f' · {slot}번' if slot else '')
    if role == 'sp':
        return f'{M.rotation_rank(c.stats, lvl)}선발'
    return M.PIT_ROLES[role]


def shift_role(c, role: str, step: int, lvl: float) -> tuple:
    """보직 한 계단 위·아래 — (role, slot, 보직 글)."""
    if c.role == 'batter':
        if step > 0:
            new, slot = ('lower', 8) if role == 'bench' else (M.upper_fit(c.stats, lvl) or ('table', 2))
        else:
            new, slot = ('bench', 0) if role == 'lower' else ('lower', 6)
    else:
        slot = 0
        if step > 0:
            new = 'win' if role in ('mop', 'chase') else ('sp' if c.position == 'SP' else 'closer')
        else:
            new = 'win' if role == 'sp' else 'setup' if role == 'closer' else 'chase'
    return new, slot, _role_text(c, new, slot, lvl)


def perf_z(role: str, t: dict, G: float) -> float | None:
    """평균 대비 성적(표준 단위) — 타자 OPS, 투수 평균자책점. 표본이 적으면 0 쪽으로 줄인다. 너무 적으면 None."""
    if not t:
        return None
    if role == 'pitcher':
        ip = t.get('outs', 0) / 3
        if ip < 3:
            return None
        return round((LG_ERA - L.pitching(t)['era']) / 1.0 * min(1.0, ip / max(1.0, G * 0.2)), 2)
    pa = t.get('pa', 0)
    if pa < 10:
        return None
    return round((L.batting(t)['ops'] - LG_OPS) / 0.075 * min(1.0, pa / max(1.0, G * 2.0)), 2)


SURNAMES = '김이박최정강조윤장임한오서신권황안송류홍'
GIVEN = '민준서도현우지하윤재성태진승건영호석찬혁규원'
ABROAD_NAMES = {
    'mlb': (('제이크', '타일러', '라이언', '브랜든', '카일', '저스틴', '오스틴', '네이선', '루이스', '호세'),
            ('존슨', '밀러', '윌리엄스', '브라운', '데이비스', '가르시아', '로드리게스', '마르티네스', '앤더슨', '테일러'), ' '),
    'npb': (('다나카', '스즈키', '사토', '다카하시', '이토', '와타나베', '야마모토', '나카무라', '고바야시', '가토'),
            ('쇼타', '유키', '다이스케', '겐타', '료', '하야토', '슌', '다쿠미', '렌', '가이토'), ' '),
    'cpbl': (('천', '린', '황', '장', '왕', '리', '우', '차이'), ('즈웨이', '관위', '젠밍', '쯔하오', '위청', '쥔제'), ''),
}


def rival_name(league: str, rng) -> str:
    sysname = W.system_of(league)
    if sysname in ABROAD_NAMES:
        a, b, sep = ABROAD_NAMES[sysname]
        return f'{rng.choice(a)}{sep}{rng.choice(b)}'
    return rng.choice(SURNAMES) + rng.choice(GIVEN) + rng.choice(GIVEN)


def make_rival(c, league: str, kind: str, rng) -> dict:
    """같은 경쟁자의 실력·부상·관계를 다음 면담까지 이어간다."""
    return Universe.rival_report(c, league, kind)


def _want(c) -> str:
    return '주전' if c.role == 'batter' else ('선발' if c.position == 'SP' else '필승조')


STUBBORN_HINT = '성적이 받쳐 주면 통하지만, 아니면 역효과가 나요'
MEET_CHOICES = {
    **{kind: (lambda c, kind=kind: Story.choices(c, kind)) for kind in ('highlight', 'manager', 'interview', 'conduct', 'rival')},
    'promote': lambda c: [('accept', '맡겨 주시는 자리에서 뭐든 할게요', '수용', '감독 신뢰 ↑'),
                          ('demand', f'{_want(c)} 자리가 아니면 안 올라갈래요', '고집', STUBBORN_HINT)],
    'demote': lambda c: [('accept', '받아들일게요. 내려가서 감을 찾아올게요', '수용', '감독 신뢰 ↑'),
                         ('argue', '여기서 이겨 내고 싶어요. 한 번만 더 기회를 주세요', '고집', STUBBORN_HINT),
                         ('trade', '차라리 트레이드해 주세요', '강수', '받아 주는 팀이 있으면 이적, 없으면 불화')],
    'role_down': lambda c: [('accept', '팀을 위해서라면 할게요', '수용', '감독 신뢰 ↑'),
                            ('argue', '제 자리를 지키고 싶어요', '고집', STUBBORN_HINT)],
    'role_up': lambda c: [('accept', '기대에 꼭 보답할게요', '다짐', '감독 신뢰 ↑'),
                          ('modest', '아직 부족해요. 지금 자리에서 더 배울게요', '신중', '지금 보직을 지켜요')],
}


def _meeting(c, about: str, phase: str, t: dict, G: float, rng, to=None, new_role=None, old_role=None) -> dict:
    """면담 화면 — merit(성적·실력이 고집을 받쳐 주는 정도)를 지금 정해 둔다."""
    z = perf_z(c.role, t, G) or 0.0
    if about == 'promote':
        gap = (c.ovr - (W.level(to) - 1)) / 3
    elif about == 'demote':
        gap = (c.ovr - (W.level(c.league) - 3)) / 3
    else:
        gap = (c.ovr - duty_level(c)) / 4
    m = {'kind': 'decision', 'what': 'meeting', 'about': about, 'phase': phase, 'to': to,
         'merit': round(0.6 * z + 0.4 * gap, 2), 'line': _short(c.role, t),
         'rival': make_rival(c, to or c.league, 'up' if about in ('promote', 'role_up') else 'down', rng)}
    if new_role:
        m['new_role'] = list(new_role)
    if old_role:
        m['old_role'] = list(old_role)
    return m


def meeting_view(c, m) -> dict:
    if m.get('pitch_event'):
        return dict(m['pitch_event'], about='pitch_role', who_name=who_is(c, 'lead')[0],
                    who_role=who_is(c, 'lead')[1], contract_scene=True, mid=m.get('phase') == 'mid')
    if m.get('market_event'):
        return dict(m['market_event'], about='career_market', contract_scene=True,
                    who_name=who_is(c, 'lead')[0], who_role=who_is(c, 'lead')[1])
    if m['about'] == 'demote' and c.league == 'mlb' and Contracts.active(c):
        return dict(Contracts.assignment_view(c, f'{c.pk}:{c.year}:assignment:{m.get("phase")}'),
                    about='demote', contract_scene=True, mid=m.get('phase') == 'mid')
    if m.get('encounter'):
        e = m['encounter']
        name, role = who_is(c, 'critic' if e['kind'] == 'highlight' else 'charter' if e['kind'] == 'interview' else 'lead')
        return dict(e, about=m['about'], mid=True, who_name=name, who_role=role, trust=trust(c))
    about, mid = m['about'], m.get('phase') == 'mid'
    r = m.get('rival') or {}
    to_name = W.league(m['to'])['name'] if m.get('to') else ''
    duty = (m.get('new_role') or ['', 0, ''])[2]
    feel = '타격감' if c.role == 'batter' else '구위'
    sc = m.get('scandal')
    if sc and about == 'promote':
        title = f"{W.short(m['to'])} 긴급 콜업"
        text = f"{to_name} {r['pos']} {r['name']} 선수가 {sc['why']}. 그 자리를 메울 사람이 필요해요. 전반기 {m['line']}, 올라올 준비 됐죠?"
    elif sc:
        title = '긴급 보직 면담'
        text = f"{r['name']} 선수가 {sc['why']}. 후반기엔 {duty} 자리를 맡아 줘요."
    elif about == 'promote':
        title = f"{W.short(m['to'])} 콜업"
        text = (f"{to_name} {r['pos']} {r['name']} 선수가 부진해요({r['line']}). 전반기 {m['line']}, 지금 {feel}이면 충분하대요. 올라갈 준비 됐죠?"
                if mid else f"시즌 내내 지켜봤어요({m['line']}). 다음 시즌엔 {to_name}에서 시작해요. 올라갈 준비 됐죠?")
    elif about == 'demote':
        title = f"{W.short(m['to'])}행 통보"
        text = (f"{to_name}에서 {r['pos']} {r['name']} 선수가 펄펄 날고 있어요({r['line']}). 전반기 성적({m['line']})으로는 자리를 지키기 어려워요. 당분간 내려가서 감을 찾아오죠."
                if mid else f"올 시즌은 힘들었죠({m['line']}). 다음 시즌은 {to_name}에서 다시 시작해요.")
    elif about == 'role_down':
        title = '보직 변경 통보'
        text = (f"전반기 성적({m['line']})이 아쉬워요. {r['name']} 선수가 요즘 좋아서({r['line']}), 후반기엔 {duty} 자리에서 뛰어 줘요."
                if mid else f"다음 시즌엔 {duty} 자리에서 시작해 줘요. {r['name']} 선수와 경쟁해서 다시 올라오면 돼요.")
    else:
        title = '보직 면담'
        text = (f"전반기에 정말 잘해 줬어요({m['line']}). {r['name']} 선수가 주춤해서({r['line']}), 후반기엔 {duty} 자리를 맡아 줘요."
                if mid else f"다음 시즌엔 {duty} 자리를 맡아 줘요. 기대가 커요.")
    name, role = who_is(c, 'lead')
    return {'about': about, 'title': title, 'text': text, 'mid': mid, 'rival': r, 'who': 'lead', 'who_name': name,
            'who_role': role, 'trust': trust(c), 'scandal': (sc or {}).get('word', ''),
            'choices': [{'key': k, 'label': lab, 'tone': tone, 'hint': h} for k, lab, tone, h in MEET_CHOICES[about](c)]}


def _move(c, to: str):
    c.league = to
    if W.is_pro(to) and (not W.is_pro(c.peak or 'hs') or W.level(to) > W.level(c.peak)):
        c.peak = to


def _pin(c, role_triple):
    role, slot, duty = role_triple
    c.flags['pin'] = {'year': c.year, 'league': c.league, 'role': role, 'slot': slot, 'duty': duty}


def _sticks(merit: float, need: float, rng) -> bool:
    """고집이 통하나 — merit 가 need 보다 높을수록 잘 통하지만(최대 92%), 낮아도 가끔 통한다(최소 8%)."""
    return rng.random() < _clamp(0.5 + (merit - need) * 0.6, 0.08, 0.92)


def _punish(c, rng):
    """괘씸죄 — 지금(또는 다음 시즌 시작) 보직에서 한 계단 내려 못 박는다."""
    role, _slot, _duty = _duty_now(c)
    if role_tier(role) > 0:
        _pin(c, shift_role(c, role, -1, duty_level(c)))


def resolve_meeting(c, m: dict, choice: str, rng) -> tuple:
    if m.get('pitch_event'):
        text = Pitching.resolve(c, m['pitch_event'], choice, rng)
        if m.get('phase') == 'mid':
            state = m['half']
            role, slot, duty = duty_for(c, duty_level(c))
            if state['splits'][-1]['role'] != role:
                state['splits'].append(dict(league=c.league, club=c.club, role=role, slot=slot,
                                            duty=duty, **{'from': 3}, chunks=[{} for _ in range(6)]))
        return text, []
    if m.get('market_event'):
        return Balance.market_reply(c, m['market_event'], choice, rng), []
    text, items = _resolve_meeting(c, m, choice, rng)
    if (m.get('rival') or {}).get('id'):
        Universe.remember(c, m['rival']['id'], choice, text)
    return text, items


def _resolve_meeting(c, m: dict, choice: str, rng) -> tuple:
    """면담 답의 결과 — (소식 글, 기사들). 고집은 merit 가 받쳐 주면 통하고, 아니면 신뢰·출전·기사로 돌아온다."""
    about, merit = m['about'], float(m.get('merit') or 0.0)
    merit += (Story.value(c, 'confidence') - 50) / 60 + (Story.value(c, 'discipline') - 50) / 100
    if about == 'demote' and c.league == 'mlb' and Contracts.active(c):
        try:
            text = Contracts.assignment_reply(c, choice, rng, c.year)
        except ValueError as ex:
            raise LiteError(str(ex)) from ex
        if (c.flags or {}).get('mlb_bench_season') == c.year:
            _pin(c, Contracts.bench_role(c))
        return text, [press('[계약 조항]', f'{c.name} — MLB 로스터 결정', text)]
    if m.get('encounter'):
        try:
            text = Story.resolve(c, m['encounter'], choice, rng)
        except ValueError as ex:
            raise LiteError(str(ex)) from ex
        return text, [press('[선택]', f'{c.name} — {m["encounter"]["title"]}', text)]
    if choice not in [k for k, *_ in MEET_CHOICES[about](c)]:
        raise LiteError('면담에서 어떻게 답할지 골라 주세요.')
    Story.change(c, '감독 면담에 답했어요', confidence=6 if choice == 'accept' else 9 if choice in ('argue', 'demand') else 2,
                 discipline=5 if choice in ('accept', 'modest') else -5)
    c.flags = dict(c.flags or {})
    nm, out = c.name, []
    to = m.get('to')
    if about == 'promote':
        lg = W.short(to)
        if choice == 'accept':
            _trust(c, 5)
            _move(c, to)
            out.append(press('[콜업]', f"{nm}, {lg} 부름 받았다…‘맡겨 주시면 뭐든’", m['line']))
            return f"{W.league(to)['name']}{josa(W.league(to)['name'], '으로/로')} 올라갔어요!", out
        if _sticks(merit, 1.0, rng):
            _trust(c, -3)
            _move(c, to)
            want = 'sp' if c.position == 'SP' and c.role == 'pitcher' else 'setup' if c.role == 'pitcher' else 'lower'
            lvl = duty_level(c)
            natural = duty_for(c, lvl)
            if role_tier(natural[0]) < role_tier(want):
                _pin(c, (want, 6 if want == 'lower' else 0, _role_text(c, want, 6 if want == 'lower' else 0, lvl)))
            out.append(press('', f"‘자신감 폭발’ {nm}, ‘{_want(c)} 아니면 안 간다’ 배짱 통했다", m['line']))
            return f'배짱이 통했어요 — {_want(c)} 자리를 약속받고 올라갔어요', out
        _trust(c, -12)
        c.flags['doghouse'] = 1
        _punish(c, rng)
        out.append(press('[단독]', f"{lg} 콜업 거절한 {nm}…‘{_want(c)} 아니면 안 간다’ 구단 ‘황당’"))
        return '감독이 크게 실망했어요 — 콜업은 없던 일이 되고, 출전도 줄었어요', out
    if about == 'demote':
        lg, here = W.short(to), W.short(c.league)
        if choice == 'accept':
            _trust(c, 6)
            k = 'mental' if c.role == 'pitcher' else 'eye'
            before = float(c.stats[k])
            c.stats[k] = round(min(stat_pot(c, k) + 2, before + 1.0), 1)
            _note(c, k, c.stats[k] - before, '강등을 받아들인 다짐')
            _move(c, to)
            out.append(press('', f"{nm}, {lg}행…‘다시 올라오겠다’", m['line']))
            return f"{lg}{josa(lg, '으로/로')} 내려갔어요. 다시 올라오면 돼요", out
        if choice == 'argue':
            if _sticks(merit, 0.2, rng):
                _trust(c, -3)
                out.append(press('', f"‘한 번 더’ {nm}, {here} 잔류…감독 ‘믿어 보겠다’", m['line']))
                return '감독이 한 번 더 믿어 주기로 했어요', out
            _trust(c, -10)
            c.flags['doghouse'] = 1
            _move(c, to)
            if rng.random() < 0.55:
                out.append(press('[단독]', f"{nm}, {lg}행 통보에 감독실서 언성…불화설 솔솔"))
            return '감독의 마음은 바뀌지 않았어요 — 분위기만 나빠졌어요', out
        sysname = W.system_of(c.league)
        if _sticks(merit, 0.6, rng) and sysname in W.SYSTEM_TEAMS:
            Contracts.transfer(c, rng.choice([t for t, _n, _col in W.SYSTEM_TEAMS[sysname] if t != c.club]))
            c.flags['trust'] = TRUST_START
            team = W.club_label(c.league, c.club)
            out.append(press('[트레이드]', f"{nm}, {team} 유니폼…‘새 출발’", m['line']))
            return f"{team}{josa(team, '으로/로')} 트레이드됐어요 — 새 팀에서 다시 시작해요", out
        _trust(c, -15)
        c.flags['doghouse'] = 1
        _move(c, to)
        out.append(press('[단독]', f"‘트레이드 요청’ {nm}, 결국 {lg}행…구단 ‘팀워크 해쳐’"))
        return '받아 주는 팀이 없었어요 — 결국 내려가고, 감독과 사이도 틀어졌어요', out
    new, old = m.get('new_role'), m.get('old_role')
    mid = m.get('phase') == 'mid'
    if about == 'role_down':
        if choice == 'accept':
            _trust(c, 6)
            if mid and new:
                _pin(c, new)
            return '새 보직을 받아들였어요', out
        if _sticks(merit, 0.2, rng):
            _trust(c, -2)
            if old:
                _pin(c, old)
            out.append(press('', f"{nm}, 보직 지켰다…감독 ‘실력으로 증명하라’", m['line']))
            return '자리를 지켰어요 — 이제 실력으로 보여 줘야 해요', out
        _trust(c, -10)
        if new:
            _pin(c, new)
        if rng.random() < 0.45:
            out.append(press('[단독]', f"보직 변경에 반기 든 {nm}…감독과 냉기류"))
        prv = W.prev_league(c.league)
        if prv and not (c.league == 'mlb' and Contracts.veto(c)) and rng.random() < 0.35:
            _move(c, prv)
            c.flags.pop('pin', None)
            lg = W.short(prv)
            out.append(press('', f"결국 {lg}행…{nm}, 감독 눈 밖에 났다"))
            return f"감독이 아예 {lg}{josa(lg, '으로/로')} 내려보냈어요", out
        return '감독의 결정은 그대로예요 — 분위기만 나빠졌어요', out
    # role_up
    if choice == 'accept':
        _trust(c, 4)
        if mid and new:
            _pin(c, new)
        if new:
            out.append(press('', f"{nm}, {new[2]} 낙점…‘기대에 보답하겠다’", m['line']))
        return '새 보직을 맡았어요!', out
    _trust(c, 2)
    k = 'mental' if c.role == 'pitcher' else 'eye'
    before = float(c.stats[k])
    c.stats[k] = round(min(stat_pot(c, k) + 2, before + 0.5), 1)
    _note(c, k, c.stats[k] - before, '신중한 선택')
    if old:
        _pin(c, old)
    return '지금 자리에서 더 배우기로 했어요', out


# ───────────────────────────── 기사(2026-10-18 사용자 요청: 실제 스포츠 기사 제목처럼)
EPITHET = {'contact': '안타 제조기', 'power': '거포', 'speed': '대도', 'glove': '수비 달인',
           'fire': '파이어볼러', 'control': '제구 마술사', 'breaking': '변화구 장인', 'horse': '이닝이터'}


def press(tag: str, title: str, sub: str = '') -> dict:
    return {'tag': tag, 'title': title, 'sub': sub}


def season_press(c, s, rows: list) -> list:
    """시즌 기사 제목들 — 시상·기록·팀·부진. 많아야 여섯."""
    out, nm, t = [], c.name, s.totals or {}
    ep, pit = EPITHET.get(c.style, ''), c.role == 'pitcher'
    lg, team, line = W.short(s.league), W.club_short(s.league, s.club), _short(c.role, t)
    pro = W.is_pro(s.league)
    G = rows[-1]['G'] if rows else s.games
    b = L.batting(t) if t.get('pa') else None
    p = L.pitching(t) if t.get('outs') else None
    for a in s.awards:
        k, lab = a['kind'], a['label']
        if k == 'mvp':
            n = c.mvp + 1
            out.append(press('[오피셜]', f"‘{ep}’ {nm}, {'생애 첫' if n == 1 else f'통산 {n}번째'} {lg} MVP 등극", line))
        elif k == 'rookie':
            out.append(press('', f"‘괴물 신인’ {nm}, {lg} 신인왕 품었다", line))
        elif k == 'ace':
            out.append(press('[오피셜]', f"{nm}, {lab} 수상…‘{lg} 최고 투수’ 공인", line))
        elif k == 'gg':
            out.append(press('', f"{nm}, {lab} 수상…‘이 자리 최고’ 공인", line))
        elif k == 'allstar':
            out.append(press('', f"{nm}, {lg} 올스타 선정…올스타 무대 선다"))
        elif k == 'minor':
            out.append(press('', f"‘{lg} 폭격’ {nm}, {lab}", line))
        elif k == 'title':
            tmpl = {'홈런왕': f"‘홈런 공장장’ {nm}, {t.get('hr', 0)}홈런으로 홈런왕 등극",
                    '타격왕': f"{nm}, 타율 {L.rate(b['avg']) if b else ''} 타격왕…‘안타 기계’ 증명",
                    '타점왕': f"‘해결사’ {nm}, {t.get('rbi', 0)}타점 쓸어 담아 타점왕",
                    '도루왕': f"‘{ep}’ {nm}, {t.get('sb', 0)}도루로 도루왕",
                    '다승왕': f"{nm}, {t.get('w', 0)}승 다승왕…‘에이스’ 공인",
                    '평균자책점 1위': f"‘언터처블’ {nm}, 평균자책점 {p['era']:.2f} 1위" if p else '',
                    '탈삼진왕': f"‘닥터 K’ {nm}, {t.get('so', 0)}탈삼진 탈삼진왕",
                    '세이브왕': f"‘끝판왕’ {nm}, {t.get('sv', 0)}세이브 세이브왕",
                    '홀드왕': f"‘불펜 지킴이’ {nm}, {t.get('hld', 0)}홀드 홀드왕"}.get(lab)
            out.append(press('', tmpl or f"{W.club_short(s.league, s.club)} {nm}, {lab} 수상", line))
    # 기록 이정표
    if b and t.get('hr', 0) >= 40:
        out.append(press('', f"{nm}, 시즌 {t['hr']}홈런 고지…‘{ep}’ 본색", line))
    elif b and t.get('hr', 0) >= 30 and t.get('sb', 0) >= 30:
        out.append(press('', f"{nm}, {t['hr']}-{t['sb']} 달성…호타준족의 정석", line))
    if p and p['era'] <= 2.0 and t.get('outs', 0) / 3 >= G and pro:
        out.append(press('', f"‘언터처블’ {nm}, 평균자책점 {p['era']:.2f}…리그를 지배했다", line))
    if p and t.get('so', 0) >= 200:
        out.append(press('', f"{nm}, 시즌 {t['so']}탈삼진…‘K 머신’ 가동", line))
    # 팀
    rings = [a['label'] for a in s.awards if a['kind'] == 'ring']
    for r in rings:
        out.append(press('[우승]', f"{team}, {r}…{nm} ‘{ep}’ 활약", line))
    if pro and not rings and s.team_rank == 1:
        out.append(press('', f"{team}, 정규시즌 1위 확정…{nm} 맹활약"))
    if pro and s.team_of and s.team_rank == s.team_of:
        out.append(press('', f"{team} 최하위 추락…{nm}도 고개 숙여"))
    # 월간·부진
    hot = [m['label'] for m in s.months if m.get('hot')]
    if len(hot) >= 2 and pro:
        out.append(press('', f"‘{hot[0]}의 사나이’ {nm}, 월간 MVP급 활약"))
    if b and t.get('pa', 0) >= G * 2 and b['ops'] < .600:
        out.append(press('', f"‘계륵’ 전락? {nm}, 타율 {L.rate(b['avg'])} 깊은 부진", line))
    if p and t.get('outs', 0) / 3 >= G * 0.3 and p['era'] >= 6.0:
        out.append(press('', f"흔들리는 {nm}, 평균자책점 {p['era']:.2f}…반등 절실", line))
    if s.league == 'hs' and c.grade >= 3 and scout_stars(c) >= 4:
        out.append(press('', f"‘스카우트 눈도장’ {W.club_short(s.league, s.club)} {nm}, 드래프트 상위 지명 후보"))
    out = [x for x in out if x['title']]
    if not out and pro and s.games:
        z = perf_z(c.role, t, G)
        if z is None:
            out.append(press('', f"벤치 지킨 {nm}, 기회를 기다린다"))
        elif z >= 1.0:
            out.append(press('', f"‘{ep}’ {nm}, {team} 핵심으로 우뚝", line))
        elif z >= 0:
            out.append(press('', f"{nm}, 제 몫 다한 시즌…다음 시즌 도약 노린다", line))
        else:
            out.append(press('', f"{nm}, 아쉬움 남긴 시즌…‘겨울에 다시 만든다’", line))
    return out[:6]


# ───────────────────────────── 시즌(전반기 → 올스타 휴식기 면담 → 후반기)
def _sum_chunks(chunks) -> dict:
    t = {}
    for x in chunks:
        if x:
            t = L.add(t, x)
    return t


def _duty_now(c) -> tuple:
    pin = (c.flags or {}).get('pin')
    if pin and pin.get('year') == c.year and pin.get('league') == c.league:
        return pin['role'], pin['slot'], pin['duty']
    return duty_for(c, duty_level(c))


def _sim_chunks(c, state, lo: int, hi: int, rng):
    """지금 줄(split)의 리그·보직으로 6구간 가운데 [lo, hi) 구간을 치른다."""
    sp = state['splits'][-1]
    code = sp['league']
    lvl, G = W.level(code), GAMES.get(code, 120)
    s = _game_stats(c)
    a, b = state['out']
    fixtures = Universe.club_fixtures(code, G, sp['club']) if W.is_pro(code) else ()
    for i in range(G * lo // 6, G * hi // 6):
        if a <= i / G < b:
            continue
        r = None
        if c.role == 'batter':
            r = M.batter_game(s, c.position, lvl, rng, role=sp['role'], slot=sp['slot'])
        elif sp['role'] == 'sp':
            if i % 5 == state['offset']:
                r = M.starter_game(s, lvl, rng)
        elif rng.random() < M.RELIEF[sp['role']][0]:
            r = M.relief_game(s, lvl, rng, sp['role'])
        if r:
            j = min(5, i * 6 // G)
            sp['chunks'][j] = L.add(sp['chunks'][j], r['line'])
            if fixtures:
                sp.setdefault('scores', {})[str(fixtures[i]['day'])] = {'club': sp['club'], 'for': r['team_runs'], 'against': r['opp_runs']}
    if fixtures:
        end = min(G, G * hi // 6) - 1
        Universe.advance(c, c.year, code, G, fixtures[end]['day'] + 1, sp.get('scores'))


def start_season(c, programs, intensity, event_choice, intl_choices, rng) -> dict:
    """비시즌 결정 → 3월 대회 → 전반기. 이어 갈 상태(state)를 돌려준다(JSON 으로 pending 에 담을 수 있게)."""
    progs = check_programs(c, programs)
    Universe.rivals(c)
    if intensity not in INTENSITY:
        raise LiteError('훈련 강도를 골라 주세요.')
    pend = c.pending or {}
    offered = list(pend.get('intl') or [])
    if any(intl_choices.get(k) not in ('go', 'skip') for k in offered):
        raise LiteError('국가대표 소집에 어떻게 할지 먼저 골라 주세요.')
    flags = c.flags = dict(c.flags or {})
    flags['train_log'] = ([sorted(x) for x in flags.get('train_log') or []] + [progs])[-2:]
    mods = {'injury': 0.0, 'train': 1.0, 'salary': 1.0, 'national': ''}
    tired = flags.pop('tired', None)
    if tired:
        mods['injury'] += tired.get('injury', 0.0)
        mods['train'] *= tired.get('train', 1.0)
    flags['ledger'] = []
    state = {'programs': progs, 'intensity': intensity, 'mods': mods, 'news': [], 'intl': [], 'start': dict(c.stats),
             'press': list(flags.pop('press', None) or []), 'go': [k for k in offered if intl_choices.get(k) == 'go']}
    nm, code = c.name, c.league
    # 집·장비(상점) — 월세는 시즌마다 나가고, 장비는 이번 시즌만 쓴다. cut 은 부상 위험에 곱한다(gear_cut)
    house = flags.get('house', 'dorm')
    if house == 'rent':
        rent = price_of(c, HOUSE['rent'][2])
        if cash(c) >= rent:
            flags['cash'] = cash(c) - rent
            state['news'].append(f'월세 {man(rent)}을 냈어요')
        else:
            flags['house'] = house = 'dorm'
            state['news'].append('월세를 낼 돈이 모자라서 구단 숙소로 돌아갔어요')
    gear = flags.pop('gear', None) or {}
    flags.pop('gear_on', None)
    if gear.get('year') != c.year:
        gear = {}
    cut = gear_cut(c, gear=gear, house=house)
    care = flags.pop('care', None) or {}                               # 관리팀 — 이번 시즌 하나
    if care.get('year') == c.year:
        if care.get('trainer'):
            mods['train'] *= CARE_TRAIN
        if care.get('aging'):
            mods['age'] = CARE_AGE
        state['physio'] = bool(care.get('physio'))
    if gear:
        if gear.get('bat'):
            v = dict((t[0], t[3]) for t in GEAR['bat']['tiers'])[gear['bat']]
            flags['gear_on'] = {'year': c.year, 'boost': {k: v for k in GEAR['bat']['stats'][c.role]}}
    if pend.get('event'):
        state['news'].append(apply_event(c, pend['event'], event_choice, rng, mods))
        state['press'].extend(mods.pop('press', []))
    for k in offered:
        if k not in state['go']:
            state['press'].append(press('', f"{nm}, {INTL[k]['name']} 대표팀 고사…‘소속팀에 집중’"))
    for k in state['go']:
        if INTL[k]['when'] == 'pre':
            _intl(c, k, state, rng)
    c.ovr = R.overall(c.role, c.stats)
    state['ovr_start'] = c.ovr
    G = GAMES.get(code, 120)
    # 부상 — 강도·나이·특성·이번 비시즌 선택·국가대표
    p_inj = injury_odds(c, intensity, mods['injury'] + (0.03 if 'velocity' in progs else 0.0), cut)
    state['out'] = [0.0, 0.0]
    if rng.random() < max(0.0, p_inj):
        size = rng.choices((0.12, 0.3, 0.6), (0.55, 0.3, 0.15))[0]
        if state.get('physio'):                                        # 전담 물리치료사 — 빨리 돌아오고 큰 부상도 가볍게
            size *= 0.5
        a = rng.random()
        state['out'] = [a, min(1.0, a + size)]
        n = max(1, int(G * (state['out'][1] - a)))
        where = _chunks(code)[min(5, int(a * 6))]
        state['news'].append(f"{where}에 다쳐서 {n}경기를 쉬었어요")
        if size >= 0.3:
            state['press'].append(press('', f"{nm}, {where} 부상 악재…{n}경기 결장"))
        if size >= 0.6:
            for k in PHYS:
                if k in c.stats:
                    old = float(c.stats[k])
                    c.stats[k] = round(max(25.0, old - rng.uniform(1, 3)), 1)
                    _note(c, k, c.stats[k] - old, '큰 부상')
    elif rng.random() < BAD_LUCK_P:                                    # 뜻밖의 부상 — 장비·집·강도와 상관없이 그냥 운이 나빴다
        txt, head, pro_only = rng.choice([x for x in BAD_LUCK if W.is_pro(code) or not x[2]])
        size = rng.uniform(0.06, 0.16)
        a = rng.random() * (1 - size)
        state['out'] = [a, a + size]
        n = max(1, int(G * size))
        where = _chunks(code)[min(5, int(a * 6))]
        state['news'].append(f'뜻밖의 부상 — {where}에 {txt}. {n}경기를 쉬었어요')
        state['press'].append(press('[황당]', f'{nm}, {head}…{n}경기 결장'))
    role, slot, duty = _duty_now(c)
    state['offset'] = rng.randrange(5)
    state['splits'] = [{'league': code, 'club': c.club, 'role': role, 'slot': slot, 'duty': duty, 'from': 0,
                        'chunks': [{} for _ in range(6)]}]
    _sim_chunks(c, state, 0, 3, rng)
    for k in state['go']:
        if INTL[k]['when'] == 'mid':
            _intl(c, k, state, rng)
    return state


def break_meeting(c, state, rng) -> dict | None:
    """올스타 휴식기 — 윗리그 같은 자리 주전이 부진하고 내가 잘하면 콜업, 그 반대면 강등, 같은 리그 안에선 보직."""
    flags = c.flags or {}
    code = c.league
    if not W.is_pro(code) or flags.get('army'):
        return None
    sp = state['splits'][-1]
    t = _sum_chunks(sp['chunks'])
    pitch_event = Pitching.offer(c, t, c.year)
    if pitch_event:
        return dict(kind='decision', what='meeting', about='pitch_role', phase='mid',
                    half=state, pitch_event=pitch_event)
    G = GAMES.get(code, 120) / 2
    z = perf_z(c.role, t, G)
    if z is None:
        return None
    tr = (trust(c) - TRUST_START) / 50
    nxt, prv = W.next_league(code), W.prev_league(code)
    if rng.random() < SCANDAL_P:
        m = _scandal(c, state, t, G, rng)
        if m:
            return m
    if nxt and (nxt != 'mlb' or Balance.overseas_level(c, 'mlb') == 'mlb') and not flags.get('doghouse') and z >= 0.7 and c.ovr >= W.level(nxt) - 5:
        m = _meeting(c, 'promote', 'mid', t, G, rng, to=nxt)
        if z - m['rival']['z'] + (c.ovr - (W.level(nxt) - 1)) / 3 + tr >= 1.2:
            return dict(m, half=state)
    if prv and z <= -0.8 and flags.get('mlb_bench_season') != c.year:
        m = _meeting(c, 'demote', 'mid', t, G, rng, to=prv)
        if -z + m['rival']['z'] + (W.level(code) - 2 - c.ovr) / 3 - tr >= 1.5:
            return dict(m, half=state)
    tier, lvl = role_tier(sp['role']), duty_level(c)
    old = (sp['role'], sp['slot'], sp['duty'])
    if z >= 1.3 and tier < 2 and rng.random() < 0.6:
        return dict(_meeting(c, 'role_up', 'mid', t, G, rng, new_role=shift_role(c, sp['role'], 1, lvl), old_role=old),
                    half=state)
    if z <= -1.3 and tier > 0 and rng.random() < 0.6:
        return dict(_meeting(c, 'role_down', 'mid', t, G, rng, new_role=shift_role(c, sp['role'], -1, lvl), old_role=old),
                    half=state)
    return None


# 경쟁자가 사고를 쳐서 내게 기회가 온다(2026-10-18 사용자 요청: 열애설·원정 도박 같은 일을 비튼 가상 기사).
# 실존 인물·사건이 아니라 흔한 꼴만 빌렸다 — 이름은 가상 경쟁자(make_rival). (코드, 짧은 말, 기사 머리, 기사 제목, 감독 대사)
SCANDALS = (
    ('dating', '열애설', '[단독]', '{r}, 아이돌과 열애설…‘요즘 야구가 손에 안 잡힌다’', '열애설이 터진 뒤로 도무지 집중을 못 해요'),
    ('casino', '원정 도박', '[충격]', '{r}, 원정 숙소 빠져나가 카지노行 들통…잔여 시즌 출장 정지', '원정 가서 카지노를 드나든 게 들통나서 출장 정지를 받았어요'),
    ('arcade', '게임장 출입', '[논란]', '{r}, 전지훈련지 게임장 출입 영상 확산…구단 “자체 징계”', '전지훈련 때 게임장에 드나든 영상이 퍼져서 징계를 받았어요'),
    ('sns', 'SNS 설화', '[논란]', '{r}, 새벽 SNS 라이브서 ‘감독 저격’…결국 자숙', '새벽에 SNS 라이브를 켜고 사고를 쳐서 자숙 중이에요'),
    ('chat', '단톡방 유출', '[단독]', '{r}, 단톡방 ‘코치 뒷담화’ 캡처 유출…“깊이 반성”', '단톡방 캡처가 돌아서 당분간 못 써요'),
    ('mukbang', '먹방 후유증', '[화제]', '{r}, 먹방 채널 대박 났지만…체중 12kg 불어 ‘몸이 무겁다’', '먹방 채널을 시작하더니 몸이 무거워져서 못 쓰겠어요'),
)
SCANDAL_P = 0.08            # 프로 시즌마다(올스타 휴식기) 이런 일이 생길 확률 — 내가 올라갈 자리가 있을 때만
# 뜻밖의 부상 — 훈련·장비와 상관없이 황당하게 다친다(2026-10-18 사용자 요청). (일지 문장, 기사 제목, 프로에서만)
BAD_LUCK = (
    ('샤워하다 미끄러져 새끼손가락이 부러졌어요', '샤워하다 미끄러져 손가락 골절', False),
    ('자고 일어났더니 담이 와서 고개를 못 돌렸어요', '자고 일어났더니 담 걸려', False),
    ('홈런 세리머니를 하다 동료 헬멧에 코를 부딪혔어요', '세리머니 하다 동료와 충돌', False),
    ('반려견 산책을 시키다 발목을 접질렸어요', '반려견 산책 중 발목 염좌', False),
    ('택배 상자를 옮기다 허리를 삐끗했어요', '택배 상자 옮기다 허리 삐끗', False),
    ('조카 장난감 블록을 밟고 발바닥을 다쳤어요', '장난감 블록 밟고 발바닥 부상', False),
    ('수박을 자르다 손가락을 베였어요', '수박 자르다 손가락 열상', False),
    ('라면을 끓이다 냄비를 엎어 손등을 데었어요', '라면 끓이다 손등 화상', False),
    ('팬 사인회에서 사인을 천 장 넘게 하다 손목 건초염이 왔어요', '사인 천 장 하다 손목 건초염', True),
    ('구단 버스 문에 손이 끼었어요', '구단 버스 문에 손 끼어', True),
)
BAD_LUCK_P = 0.05


def _scandal(c, state, t, G, rng):
    """올라갈 자리의 경쟁자가 사고를 쳤다 — 윗리그 콜업(실력이 되면) 아니면 같은 리그 보직 승격 면담."""
    code, sp = c.league, state['splits'][-1]
    nxt = W.next_league(code)
    key, word, head, title, why = rng.choice(SCANDALS)
    if nxt and (nxt != 'mlb' or Balance.overseas_level(c, 'mlb') == 'mlb') and not (c.flags or {}).get('doghouse') and c.ovr >= W.level(nxt) - 6:
        m = _meeting(c, 'promote', 'mid', t, G, rng, to=nxt)
    elif role_tier(sp['role']) < 2:
        m = _meeting(c, 'role_up', 'mid', t, G, rng, new_role=shift_role(c, sp['role'], 1, duty_level(c)),
                     old_role=(sp['role'], sp['slot'], sp['duty']))
    else:
        return None
    r = m['rival']
    m['scandal'] = {'key': key, 'word': word, 'why': why}
    state['press'].append(press(head, title.format(r=r['name']), f"{r['league']} {r['pos']}"))
    state['news'].append(f"{r['name']} 선수의 {word} 파문으로 기회가 왔어요")
    return dict(m, half=state)


def finish_season(c, state, rng):
    """후반기 → 11월 대회 → 팀 성적·시상·연봉·성장 → 다음 시즌 이동(면담으로) → 저장·결산 화면."""
    from .models import LiteSeason
    flags = c.flags = dict(c.flags or {})
    last = state['splits'][-1]
    pin = flags.get('pin')
    moved = c.league != last['league'] or c.club != last['club']
    pinned = bool(pin and pin.get('year') == c.year and pin.get('league') == c.league
                  and (pin['role'], pin['slot']) != (last['role'], last['slot']))
    if moved or pinned:
        role, slot, duty = _duty_now(c)
        state['splits'].append({'league': c.league, 'club': c.club, 'role': role, 'slot': slot, 'duty': duty, 'from': 3,
                                'chunks': [{} for _ in range(6)]})
    _sim_chunks(c, state, 3, 6, rng)
    for k in state['go']:
        if INTL[k]['when'] == 'post':
            _intl(c, k, state, rng)
    mods = state['mods']
    code, G = c.league, GAMES.get(c.league, 120)
    pit = c.role == 'pitcher'
    pos = 'SP' if pit else c.position
    splits = state['splits']
    rows, totals, war = [], {}, 0.0
    for i, sp in enumerate(splits):
        frm, to = sp['from'], (splits[i + 1]['from'] if i + 1 < len(splits) else 6)
        t = _sum_chunks(sp['chunks'][frm:to])
        w = round(L.war(c.role, pos, t), 1) if t else 0.0
        rows.append({'league': sp['league'], 'club': sp['club'], 'role': sp['role'], 'slot': sp['slot'], 'duty': sp['duty'],
                     'from': frm, 'to': to, 'G': round(GAMES.get(sp['league'], 120) * (to - frm) / 6, 1), 'totals': t,
                     'war': w, 'chunks': sp['chunks']})
        totals = L.add(totals, t)
        war += w
    war = round(war, 1)
    fr = rows[-1]
    # 같은 일정에서 모든 구단이 맞붙는다. 내 개인 경기 점수는 실제 해당 대진에 반영한다.
    for row, sp in zip(rows, splits):
        if W.is_pro(row['league']):
            row['world'] = Universe.advance(c, c.year, row['league'], GAMES[row['league']], overrides=sp.get('scores'))
    world = fr.get('world')
    mine = world['mine'] if world else None
    w, losses = (mine['w'], mine['l']) if mine else (0, 0)
    team_n = len(world['rows']) if world else 0
    rank, champion = (mine['rank'] if mine else 0), False
    # 월별 전광판 — 옮겼으면 그 달부터 새 리그
    months, run = [], {}
    first_p = 0.5 + rng.gauss(0, 0.045)
    for j in range(6):
        row = next(r for r in rows if r['from'] <= j < r['to'])
        t = row['chunks'][j] or {}
        run = L.add(run, t)
        md = 0
        if row.get('world'):
            wt = row['world']
            month_table = Universe.table(c, c.year, row['league'], wt['games'], wt['rounds'] * (j + 1) // 6)
            mr = next(x for x in month_table['rows'] if x['club'] == row['club'])
            mw, ml, md = mr['w'], mr['l'], mr['d']
        else:
            mw, ml = 0, 0
        moved = j == row['from'] and row['from'] > 0
        note = kind = ''
        if moved:
            prev = rows[rows.index(row) - 1]
            if prev['league'] != row['league']:
                up = W.level(row['league']) > W.level(prev['league'])
                kind = 'up' if up else 'down'
                note = f"{W.short(row['league'])}{josa(W.short(row['league']), '으로/로')} {'콜업' if up else '강등'} — {row['duty']}"
            elif prev['club'] != row['club']:
                kind, note = 'trade', f"{W.club_short(row['league'], row['club'])}{josa(W.club_short(row['league'], row['club']), '으로/로')} 트레이드 — {row['duty']}"
            else:
                up = role_tier(row['role']) > role_tier(prev['role'])
                kind, note = 'role', f"보직 {'상향' if up else '변경'} — {row['duty']}"
        months.append({'label': _chunks(row['league'])[j], 'line': _short(c.role, t), 'run': _short(c.role, run),
                       'hot': _hot(c.role, t), 'w': mw, 'l': ml, 'd': md, 'lg': W.short(row['league']),
                       'moved': moved, 'move_kind': kind, 'note': note})
    season = LiteSeason(career=c, year=c.year, age=c.age, league=code, club=c.club, duty=fr['duty'], games=G,
                        totals=totals, war=war, team_w=w, team_l=losses, team_rank=rank, team_of=team_n,
                        champion=champion, months=months, ovr_start=state['ovr_start'])
    season.splits = [{k: r[k] for k in ('league', 'club', 'role', 'slot', 'duty', 'from', 'to', 'G', 'totals', 'war')}
                     | {'line': _short(c.role, r['totals']), 'table': r.get('world')} for r in rows]
    # 시상 — 리그마다 따로
    seen = list(flags.get('leagues') or [])
    awards = []
    for r in rows:
        half = _sum_chunks(r['chunks'][:3]) if r['from'] == 0 else None
        awards += awards_for(c, r['league'], r['totals'], r['war'], r['G'], r['league'] not in seen, half, rng)
    for res in state['intl']:
        if not res.get('final'):
            awards.append({'kind': 'national', 'label': f"{res['name']} {res['result']}"})
    if mods.get('national'):
        awards.append({'kind': 'national', 'label': f"국가대표 {mods['national']}"})
    moments = moments_for(c, code, rank, team_n, state, rng)
    if code in TOURNAMENTS:
        zz = (c.ovr - W.level(code)) / 5.0
        for tn in TOURNAMENTS[code]:
            p_win = 0.03 + 0.04 * max(0.0, zz) + (0.03 if W.powerhouse(code, c.club) else 0.0)
            if rng.random() >= 2 * p_win:                     # 결승에 못 올랐다
                continue
            if not any(m['kind'] == 'amateur' for m in moments):
                moments.append(make_moment(c, 'amateur', f'{tn} 결승', '', rng, key=tn))   # 그 시즌 첫 결승은 내가 승부한다
            elif rng.random() < 0.5:                          # 두 번째 결승부터는 반반
                awards.append({'kind': 'ring', 'label': f'{tn} 우승'})
                season.champion = True
    season.awards = awards
    season.salary = salary_for(c, war, mods['salary'], splits=rows)
    # 성장 — 출전 시간은 줄마다 그 리그 기준으로
    pt = 0.0
    for r in rows:
        t, share = r['totals'], (r['to'] - r['from']) / 6
        if not t or not r['G']:
            continue
        if pit:
            pt += share * min(1.0, (t.get('outs', 0) / 3) / (r['G'] * (1.2 if r['role'] == 'sp' else 0.45)))
        else:
            pt += share * min(1.0, t.get('pa', 0) / (r['G'] * 4.0))
    grown = grow(c, state['programs'], state['intensity'], min(1.0, pt), war, rng,
                 mods['train'] * Story.training_mult(c), mods.get('age', 1.0))
    season.deltas = season_deltas(c, state.get('start'), (c.flags or {}).pop('ledger', []), grown.pop('_why', {}), grown)
    season.ovr_end = c.ovr
    # 다음 시즌 이동 — 바로 옮기지 않고 면담(next_step)에서 정한다
    if W.is_pro(code) and not flags.get('army'):
        nxt, below = W.next_league(code), W.demote_below(code)
        star = fr['war'] * (1.4 if pit else 1.0) >= 4.0 * fr['G'] / 144
        mv = None
        if nxt and (nxt != 'mlb' or Balance.overseas_level(c, 'mlb') == 'mlb') and not flags.get('doghouse') and _ok(c.role, fr['totals'], fr['G']) \
                and (c.ovr >= W.level(nxt) - 1 or (star and c.ovr >= W.level(nxt) - 4)):
            mv = 'promote'
        elif below is not None and c.ovr < below - (trust(c) - TRUST_START) / 25:
            mv = 'demote'
        elif W.prev_league(code) and trust(c) < 20 and rng.random() < 0.5:
            mv = 'demote'                                     # 감독 눈 밖 — 실력이 돼도 내려보낸다
        if mv:
            flags['move'] = {'kind': mv, 'to': nxt if mv == 'promote' else W.prev_league(code)}
    if flags.get('doghouse'):
        flags['doghouse'] -= 1
        if flags['doghouse'] <= 0:
            flags.pop('doghouse')
    season.news = [n for n in state['news'] if n]
    season.press = state['press'] + season_press(c, season, rows)
    back = army_after_season(c)
    if back:
        season.news.append(back)
    season.save()
    if moments:                                                # 결정적 순간 — 고른 뒤에 시즌을 닫는다
        c.pending = {'kind': 'decision', 'what': 'moment', 'year': season.year, 'moments': moments, 'i': 0, 'done': []}
        c.save()
        return season
    wrap_season(c, season, rng)
    c.save()
    return season


def season_deltas(c, start: dict | None, ledger: list, grow_why: dict, grown: dict) -> dict:
    """시즌 능력치 변화 {능력: 시작 대비} + '_why': {능력: [[이유, 값], …]} — 이유는 떨어진 것부터."""
    out, why = {}, {}
    for k in c.stats:
        if start and k in start:
            out[k] = round(float(c.stats[k]) - float(start[k]), 1)
        else:
            out[k] = grown.get(k, 0.0)
        items = {}
        for kk, v, lab in ledger:
            if kk == k:
                items[lab] = items.get(lab, 0.0) + v
        for lab, v in grow_why.get(k, []):
            items[lab] = items.get(lab, 0.0) + v
        why[k] = [[lab, round(v, 1)] for lab, v in sorted(items.items(), key=lambda x: x[1]) if abs(v) >= 0.05]
    out['_why'] = why
    return out


def end_meeting(c, rng) -> dict | None:
    """시즌을 마치고 '다음' — 이동이 정해졌거나 다음 시즌 보직이 한 계단 바뀌면 감독실로."""
    flags = c.flags = dict(c.flags or {})
    mv = flags.pop('move', None)
    if mv and W.system_of(mv.get('to', '')) != W.system_of(c.league):
        mv = None  # 이전 저장본에 남은 해외 이적 전 승강 예약도 무시한다.
    if not W.is_pro(c.league) or flags.get('army'):
        return None
    last = c.seasons.order_by('-year').first()
    fr = (last.splits or [{}])[-1] if last else {}
    t, G = fr.get('totals') or (last.totals if last else {}) or {}, fr.get('G') or GAMES.get(c.league, 120)
    pitch_event = Pitching.offer(c, t, c.year)
    if pitch_event:
        return dict(kind='decision', what='meeting', about='pitch_role', phase='end', pitch_event=pitch_event)
    if mv:
        return _meeting(c, mv['kind'], 'end', t, G, rng, to=mv['to'])
    if not fr or fr.get('league') != c.league or not fr.get('role'):
        return None
    role, slot, duty = duty_for(c, duty_level(c))
    if role_tier(role) == role_tier(fr['role']):
        return None
    about = 'role_up' if role_tier(role) > role_tier(fr['role']) else 'role_down'
    return _meeting(c, about, 'end', t, G, rng, new_role=(role, slot, duty),
                    old_role=(fr['role'], fr.get('slot', 0), fr.get('duty', '')))


# ───────────────────────────── 시즌을 넘기며(나이·학년·결정)
def run_season(c, programs, intensity, choice, rng, intl=None):
    """비시즌 고른 것 → 전반기 → (휴식기 면담이 있으면 멈춤) → 후반기 → 결산 화면(review). 잠근 행에서 부른다.
    시즌 기록을 돌려준다(면담에서 멈췄으면 None — 면담 답(decide 'meeting') 뒤에 이어 친다).
    intl: {대회: 'go'|'skip'} — 안 주면 모두 사양."""
    if c.league == 'mlb' and Contracts.active(c) and (c.flags or {}).get('mlb_camp_season') != c.year:
        c.flags['mlb_camp_season'] = c.year
        if c.flags.get('mlb_bench_season') != c.year and rng.random() < Contracts.camp_risk(c):
            if Contracts.veto(c):
                c.pending = dict(kind='decision', what='meeting', about='demote', phase='camp',
                                 to='mlb_aaa', plan=c.pending)
                c.save()
                return None
            text = Contracts.assignment_reply(c, 'accept', rng, c.year)
            c.flags['press'] = list(c.flags.get('press') or []) + [press('[개막 로스터]', text)]
    offered = list((c.pending or {}).get('intl') or [])
    state = start_season(c, programs, intensity, choice, intl if intl is not None else {k: 'skip' for k in offered}, rng)
    meet = break_meeting(c, state, rng)
    if not meet and not (c.flags or {}).get('army') and rng.random() < .55:
        kind = rng.choice(['highlight', 'highlight', 'manager', 'interview', 'conduct', 'rival'])
        played = _sum_chunks(state['splits'][-1]['chunks'])
        if kind == 'highlight' and not (played.get('pa') or played.get('bf')):
            kind = 'conduct'
        meet = {'kind': 'decision', 'what': 'meeting', 'about': kind, 'phase': 'mid', 'half': state,
                'encounter': Story.encounter(c, kind, rng)}
    if meet:
        c.pending = meet
        c.save()
        return None
    return finish_season(c, state, rng)


def next_season(c, rng):
    """결산을 보고 '다음' — 결정이 있으면 결정, 없으면 비시즌."""
    if (c.pending or {}).get('kind') != 'review':
        raise LiteError('지금은 다음 시즌으로 넘어갈 차례가 아니에요.')
    c.pending = next_step(c, rng)
    c.save()


def wrap_season(c, season, rng):
    """시즌 기록을 저장한 뒤 — 통산·플래그 반영, 결산 화면으로."""
    code = season.league
    flags = dict(c.flags or {})
    leagues = list(flags.get('leagues') or [])
    if code not in leagues:
        leagues.append(code)
    flags['leagues'] = leagues
    if W.is_pro(code):
        flags['pro_years'] = flags.get('pro_years', 0) + 1
        c.war = round(c.war + season.war, 1)
        if W.system_of(code) == 'kbo':
            flags['kbo_years'] = flags.get('kbo_years', 0) + 1
        service = dict(flags.get('top_service') or {})
        for row in Balance.top_splits(season):
            service[row['league']] = round(service.get(row['league'], 0) + min(1, row.get('G', season.games) / GAMES[row['league']]), 3)
        flags['top_service'] = service
        Contracts.finish_lite(c, season, flags)
        deal = flags.get('contract')
        if deal:
            deal['years'] = deal.get('years', 0) - 1
            if deal['years'] <= 0:
                if deal.get('version') == 2:
                    flags['last_contract'] = dict(deal, ended='expired')
                flags.pop('contract', None)
    for lg in (code, c.league):
        if W.is_pro(lg) and (not W.is_pro(c.peak or 'hs') or W.level(lg) > W.level(c.peak)):
            c.peak = lg
    afx = award_fx(c, season, flags)
    if afx:
        flags['award_fx'] = afx
    for a in season.awards:
        if a['kind'] == 'mvp':
            c.mvp += 1
        if a['kind'] in ('mvp', 'rookie', 'gg', 'ace', 'title', 'minor'):
            c.awards += 1
        if a['kind'] == 'ring':
            c.rings += 1
    money = int(flags['cash']) if 'cash' in flags else int(c.earnings or 0)
    flags['fame'] = fame_after(flags, season)
    ad = ad_income(flags, code)
    if ad:
        season.news.append(f'광고 수입 {man(ad)}이 들어왔어요(인기 {_fame_of(flags)})')
        season.save(update_fields=['news'])
    tax = income_tax(season.salary + ad)                              # 연봉·광고 수입의 세금(종합소득세 구간)
    if tax:
        season.news.append(f'세금 {man(tax)}을 냈어요(연봉·광고 수입의 {round(100 * tax / (season.salary + ad))}%)')
        season.save(update_fields=['news'])
    flags['cash'] = money + season.salary + ad - tax
    inv = flags.pop('invest', None)                                    # 지인 사업 투자 — 시즌이 끝나면 결과
    if inv:
        mult, _w, label = rng.choices(INVEST_OUT, [x[1] for x in INVEST_OUT])[0]
        back = int(inv['amount'] * mult)
        flags['cash'] += back
        season.news.append(f"지인 사업 투자 {label} — {man(inv['amount'])}이 {man(back)}{josa(man(back), '이/가')} 됐어요")
        if label in ('대박', '쪽박'):
            season.press.append(press('', f"{c.name}, 지인 사업 투자 {'대박…‘운이 좋았다’' if label == '대박' else '쪽박…수억 날렸다'}"))
        season.save(update_fields=['news', 'press'])
    c.earnings += season.salary + ad
    c.salary = season.salary
    if c.age + 1 >= 19 and c.traits and not c.traits_seen:          # 고교를 마칠 때 스카우팅 리포트로 드러난다
        c.traits_seen = list(c.traits)
        season.news.append('스카우팅 리포트 — 숨은 특성: ' + ', '.join(TRAITS[t][0] for t in c.traits))
        season.save(update_fields=['news'])
    c.flags = flags
    Balance.income_record(c, season.salary, ad)
    Balance.workload_after(c, season.splits or [dict(league=season.league, totals=season.totals)])
    season.save(update_fields=['news'])
    assessment = perf_z(c.role, season.totals, season.games)
    promise = Story.settle_promise(c, assessment)
    if promise:
        season.news.append(promise)
        season.save(update_fields=['news'])
    Story.recover(c)
    c.year += 1
    c.age += 1
    if not W.is_pro(c.league):
        c.grade += 1
    c.pending = {'kind': 'review', 'year': season.year}


# 수상 축하 연출(2026-10-19 사용자 요청: MVP·중요한 상은 모션그래픽으로) — flags['award_fx'] 를 다음 화면이 한 번 보여 주고 지운다.
# MVP·투수 최고상·신인왕은 받을 때마다, 골든글러브·타이틀·하위 리그 MVP 는 그 리그에서 처음 받을 때만(매 시즌 뜨면 지겹다).
AWARD_HERO = ('mvp', 'ace', 'rookie', 'gg', 'title', 'minor')
AWARD_EVERY = ('mvp', 'ace', 'rookie')


def award_fx(c, season, flags: dict) -> dict | None:
    got = [a for a in season.awards if a['kind'] in AWARD_HERO]
    if not got:
        return None
    seen = set(flags.get('award_seen') or [])
    key = lambda a: f"{season.league}:{a['label']}"                       # noqa: E731
    fresh = [a for a in got if key(a) not in seen]
    flags['award_seen'] = sorted(seen | {key(a) for a in got})
    cheer = [a for a in got if a['kind'] in AWARD_EVERY] or fresh
    if not cheer:
        return None
    hero = min(cheer, key=lambda a: AWARD_HERO.index(a['kind']))
    n = 1 + sum(1 for s in c.seasons.exclude(pk=season.pk) for a in s.awards
                if s.league == season.league and a['label'] == hero['label'])
    from .rookie_card import _palette
    pal = _palette(season.league, season.club)
    return {'hero': hero['label'], 'kind': hero['kind'], 'n': n,
            'kicker': f"{cal_year(c, season.year)} 시즌 · {W.league(season.league)['name']}",
            'count': f'통산 {n}번째' if n > 1 else '첫 수상',
            'line': f"{_short(c.role, season.totals)} · WAR {season.war}",
            'others': [a['label'] for a in season.awards if a is not hero and a['kind'] in AWARD_HERO + ('allstar',)],
            'colors': [pal['primary'], pal['secondary']]}


def next_step(c, rng, skip_meeting: bool = False) -> dict:
    """다음에 올 화면 — 감독 면담 → 결정 → 비시즌 순."""
    flags = c.flags or {}
    code = c.league
    if c.age > RETIRE_AT:
        return {'kind': 'decision', 'what': 'end'}
    if code == 'hs' and c.grade > 3:
        return draft_offer(c, 'hs', rng)
    if code == 'univ' and c.grade > 4:
        return draft_offer(c, 'univ', rng)
    last = c.seasons.order_by('-year').first()
    pressure = Balance.retention(c, last)
    if pressure is not None and rng.random() < pressure:
        event = Balance.market_event(c, pressure)
        return dict(kind='decision', what='meeting', about='career_market', phase='end', market_event=event)
    expired = Contracts.expiry_market(c, rng)
    if expired:
        return dict(expired, kind='decision', what='posting')
    if Contracts.can_opt_out(c):
        return {'kind': 'decision', 'what': 'contract_optout'}
    if not skip_meeting:
        m = end_meeting(c, rng)
        if m:
            return m
        flags = c.flags or {}
    if W.is_pro(code) and not Contracts.active(c) and c.age >= 32 and c.ovr < W.level(code) - 10 and W.prev_league(code) is None:
        return {'kind': 'decision', 'what': 'released'}
    if W.is_pro(code) and c.age >= VET_CUT and not flags.get('army') and not Contracts.active(c):
        gap = W.level(W.SYSTEMS[W.system_of(code)][-1]) - c.ovr        # 그 나라 1군 수준까지 모자란 몫
        if gap >= 8 and rng.random() < min(0.9, 0.35 + 0.15 * (c.age - VET_CUT) + 0.04 * (gap - 8)):
            return {'kind': 'decision', 'what': 'released'}
    if W.system_of(code) == 'kbo' and not flags.get('served') and not flags.get('exempt') and c.age >= 23 \
            and not flags.get('army'):
        if c.age >= 28 or rng.random() < 0.5:
            return {'kind': 'decision', 'what': 'military', 'forced': c.age >= 28}
    if W.system_of(code) in ABROAD and not flags.get('army'):          # 해외에선 시즌을 마칠 때마다(2026-10-18 사용자 요청)
        return {'kind': 'decision', 'what': 'return', 'offers': return_offers(c, rng), 'system': W.system_of(code)}
    if W.system_of(code) == 'kbo' and flags.get('top_service', {}).get('kbo1', 0) >= 7 and not flags.get('posted'):
        offers = Story.posting_offers(c, rng)
        if offers:
            return {'kind': 'decision', 'what': 'posting', 'offers': offers}
    if W.system_of(code) == 'kbo' and flags.get('kbo_years', 0) >= 9 and not flags.get('fa') and code == 'kbo1':
        return {'kind': 'decision', 'what': 'fa', 'offers': fa_offers(c, rng)}
    if awaken_ready(c):
        return {'kind': 'decision', 'what': 'awaken', 'odds': awaken_odds(c)}
    if c.age >= RETIRE_FROM:
        return {'kind': 'decision', 'what': 'retire'}
    return plan_step(c, rng)


def awaken_ready(c) -> bool:
    """각성 기회 — 별이 다섯 개가 안 되고, 나이·차례가 되고, (다섯 능력이 모두 한계) 또는
    (잠재력 가까이까지 키웠고 지난 시즌 성적이 평균보다 AWAKEN_FORM 표준 이상)."""
    f = c.flags or {}
    if base_stars(c) + awakened(c) >= 5 or c.age > 31 or c.year < int(f.get('awaken_next', 0)) or f.get('army'):
        return False
    if awakened(c):
        last = c.seasons.order_by('-year').first() if c.pk else None
        elite = any(r.get('war', 0) >= 5 + awakened(c) for r in Balance.top_splits(last)) if last else False
        if not elite:
            return False
    if all(room_of(c, k) < 0.2 for k in c.stats):
        return True
    gaps = [stat_pot(c, k) - float(c.stats[k]) for k in c.stats]
    if sum(gaps) / len(gaps) > AWAKEN_NEAR:
        return False
    last = c.seasons.filter(games__gt=0).order_by('-year').first() if c.pk else None
    z = perf_z(c.role, last.totals, last.games) if last and last.totals else None
    return z is not None and z >= AWAKEN_FORM


AWAKEN_TIER = {2: 0.6, 3: 0.45, 4: 0.3, 5: 0.15}      # 목표 별 칸마다 기본 성공 확률 — 높은 별일수록 어렵다


def awaken_odds(c) -> float:
    """각성 성공 확률 — 목표 별이 높을수록 어렵고, 어릴수록·연습벌레·큰 경기 체질이면 조금 높다."""
    p = AWAKEN_TIER[min(5, base_stars(c) + awakened(c) + 1)]
    p += (0.08 if has(c, 'grinder') else 0) + (0.04 if has(c, 'clutch') else 0)
    p += 0.05 if c.age <= 24 else -0.08 if c.age >= 31 else 0
    return round(_clamp(p, 0.08, 0.7), 2)


def awaken(c, choice: str, rng) -> str:
    """각성 도전의 결과 — flags['awaken_fx'] 에 연출할 내용을 남긴다(다음 화면이 한 번 보여 주고 지운다)."""
    if choice not in ('try', 'skip'):
        raise LiteError('도전할지 정해 주세요.')
    f = c.flags = dict(c.flags or {})
    f['awaken_next'] = c.year + AWAKEN_WAIT
    if choice == 'skip':
        return '지금의 나를 다듬기로 했어요 — 두 시즌 뒤에 다시 기회가 와요'
    nm = c.name
    odds = (c.pending or {}).get('odds')                   # 화면에 보여 준 확률 그대로(0 도 0 으로)
    if rng.random() < (awaken_odds(c) if odds is None else float(odds)):
        gain = awaken_gain(c)
        f['awaken'] = awakened(c) + 1
        ups = []
        for k in STYLES[c.role][c.style]['plus']:
            old = float(c.stats[k])
            c.stats[k] = round(old + 2.0, 1)
            ups.append([dict((x, lab) for x, lab, _w in R.ROLES[c.role]['stats'])[k], 2.0])
        c.ovr = R.overall(c.role, c.stats)
        c.best_ovr = max(c.best_ovr, c.ovr)
        f['awaken_fx'] = {'ok': True, 'n': f['awaken'], 'plus': gain, 'ups': ups, 'stars': min(5, base_stars(c) + f['awaken'])}
        f['press'] = list(f.get('press') or []) + [press('[각성]', f"{nm}, 한계를 부쉈다…‘보라색 별’ {f['awaken']}개째")]
        return f"각성에 성공했어요! 별이 {min(5, base_stars(c) + f['awaken'])}개가 됐어요 — 모든 능력의 한계가 {gain:g} 올라갔어요"
    k = 'mental' if c.role == 'pitcher' else 'eye'
    c.stats[k] = round(max(25.0, float(c.stats[k]) - 1.0), 1)
    c.ovr = R.overall(c.role, c.stats)
    f['tired'] = {'injury': ((f.get('tired') or {}).get('injury', 0.0)) + 0.04, 'train': (f.get('tired') or {}).get('train', 1.0)}
    f['awaken_fx'] = {'ok': False}
    return '벽은 아직 높았어요 — 다음 시즌 부상 위험이 조금 올라가요'


BURIED = {'bench', 'mop', 'chase'}          # 이 보직으로 졸업 학년을 보내면 강호에서는 스카우트 눈에 묻힌다


def showcase(c, src: str) -> float:
    """강호의 스카우트 노출 — 고교 강호는 주전이면 +0.3, 벤치·패전조·추격조면 묻혀서 −0.5. 대학 강호는 +0.3."""
    if not W.powerhouse(src, c.club):
        return 0.0
    if src != 'hs':
        return 0.3
    return -0.5 if duty_for(c, duty_level(c))[0] in BURIED else 0.3


def draft_offer(c, src: str, rng) -> dict:
    mean, sd = DRAFT_CLASS[src]
    scout = c.potential + rng.gauss(0, 4 if src == 'hs' else 3)
    last = c.seasons.filter(league=src).order_by('-year').first()
    perf = 0.0
    if last and last.totals:
        t = last.totals
        perf = _clamp((L.pitching(t)['era'] and (3.5 - L.pitching(t)['era']) / 1.5) if t.get('outs')
                      else (L.batting(t)['ops'] - .800) / .15, -1.5, 1.5)
    w_pot = 0.35 if src == 'hs' else 0.25
    z = w_pot * (scout - POT_MEAN) / POT_SD + (1 - w_pot) * (c.ovr - mean) / sd + 0.25 * perf \
        + showcase(c, src)
    score = round(50 + 10 * z, 1)
    from .rookie_career import DRAFT_ROUNDS, draft_round
    rnd = draft_round(score)
    offer = None
    if rnd:
        top, floor_ = DRAFT_ROUNDS[0][0], DRAFT_ROUNDS[-1][0]
        want = 0.10 + 0.55 * _clamp((score - floor_) / (top - floor_), 0.0, 1.0)
        team = c.team if rng.random() < want else rng.choice([t for t, _n, _col in W.KBO_TEAMS if t != c.team])
        k = rng.randint(1, 10)
        offer = {'team': team, 'round': rnd, 'in_round': k, 'pick': (rnd - 1) * 10 + k}
    abroad = {sysname: abroad_teams(sysname, rng) for sysname, at in (('mlb', 68), ('npb', 65), ('cpbl', 60))
              if score >= at and (sysname != 'mlb' or scout >= 80)}
    if src == 'hs' and last and Development.exceptional_school(c, last.totals, last.games):
        abroad.setdefault('mlb', abroad_teams('mlb', rng))
    univs = []
    if src == 'hs':
        names = [s for _r, s in W.schools('univ')]
        strong = [s for s in names if W.powerhouse('univ', s)]
        pool = strong if score >= 55 else [s for s in names if s not in strong]
        univs = rng.sample(pool, min(3, len(pool)))
    return {'kind': 'decision', 'what': 'draft', 'from': src, 'score': score, 'offer': offer, 'abroad': abroad,
            'univs': univs}


ABROAD = ('mlb', 'npb', 'cpbl')
# 해외 제안은 나라마다 구단 셋 가운데 고른다(2026-10-19 사용자 피드백: 포스팅·해외 진출 때 뜨는 팀만 뜬다 —
# 운영 데이터는 고르게 섞였지만 나라마다 한 구단만 보여 주고 포스팅은 구단을 보여 주지도 않았다). 자격이 되는 나라는 모두 보여 준다.
ABROAD_PICKS = 3


def abroad_teams(sysname: str, rng, n: int = ABROAD_PICKS) -> list:
    pool, picks = [t for t, _n, _col in W.SYSTEM_TEAMS[sysname]], []
    while pool and len(picks) < n:                                      # random() 만 쓴다(테스트의 가짜 rng 도 되게)
        picks.append(pool.pop(int(rng.random() * len(pool)) % len(pool)))
    return picks


def _teams_of(v) -> list:
    """예전 결정 화면은 나라마다 구단 하나(문자열) — 목록으로 맞춘다."""
    return [v] if isinstance(v, str) else list(v or [])


def _split_pick(choice: str) -> tuple:
    """'mlb:nyy' → ('mlb', 'nyy'), 'mlb' → ('mlb', '')."""
    sysname, _sep, team = (choice or '').partition(':')
    return sysname, team


def return_offers(c, rng) -> list:
    """해외에서 시즌을 마칠 때마다 오는 KBO 복귀 제안 — 1군감이면 희망 구단(실력이 넘치면 돈을 더 주는 구단도),
    아니면 스스로 계약을 정리하고 희망 구단 퓨처스로 돌아오는 길(2026-10-18 사용자 요청: 본인 의지로 탈출)."""
    lvl = W.level('kbo1')
    years = 2 if c.age <= 31 else 1
    if c.ovr < lvl - 4:
        return [{'key': 'self', 'team': c.team, 'league': 'kbo2', 'years': 0, 'annual': 0}]
    w = _clamp((c.ovr - lvl) * 0.9, 0.0, 9.0)
    annual = Balance.annual(c, 'kbo1', w, 9) // 100 * 100
    out = [{'key': 'kbo', 'team': c.team, 'league': 'kbo1', 'years': years, 'annual': annual}]
    if c.ovr >= lvl + 2:
        out.append({'key': 'rich', 'team': rng.choice([t for t, _n, _col in W.KBO_TEAMS if t != c.team]), 'league': 'kbo1',
                    'years': years, 'annual': int(annual * 1.2) // 100 * 100})
    return out


def fa_offers(c, rng) -> list:
    """FA 제안 — 원소속(4년), 돈을 더 주는 다른 KBO 구단(4년), 실력이 되면 해외(2년). 연봉은 최근 3시즌 WAR 기준."""
    recent = [s.war for s in c.seasons.filter(league='kbo1').order_by('-year')[:3]]
    w = max(0.0, sum(recent) / len(recent)) if recent else 0.0
    years, base = Balance.fa_terms(c, w)
    stay = {'key': 'stay', 'team': c.club, 'years': years, 'annual': int(base)}
    rich = {'key': 'move', 'team': rng.choice([t for t, _n, _col in W.KBO_TEAMS if t != c.club]), 'years': years,
            'annual': int(base * 1.2)}
    out = [stay, rich]
    mlb_pay, npb_pay = 120000 + int(c.ovr - 65) * 30000, 20000 + int(c.ovr - 60) * 4000
    if Balance.overseas_level(c, 'mlb') == 'mlb':
        for i, t in enumerate(abroad_teams('mlb', rng, 2)):
            out.append({'key': 'mlb' if not i else f'mlb{i + 1}', 'team': t, 'years': 2 + i, 'annual': int(mlb_pay * (1 - 0.1 * i))})
        out.append({'key': 'npb', 'team': abroad_teams('npb', rng, 1)[0], 'years': 2, 'annual': npb_pay})
    elif Balance.overseas_level(c, 'npb') == 'npb1':
        for i, t in enumerate(abroad_teams('npb', rng, 2)):
            out.append({'key': 'npb' if not i else f'npb{i + 1}', 'team': t, 'years': 2 + i, 'annual': int(npb_pay * (1 - 0.1 * i))})
    return out


def decide(c, what: str, choice: str, rng, school: str = '') -> str:
    """갈림길 선택 — 고친 c 와 소식 문장. 저장은 부른 쪽."""
    pend = c.pending or {}
    if pend.get('kind') != 'decision' or pend.get('what') != what:
        raise LiteError('지금은 그 결정을 할 차례가 아니에요.')
    if what == 'negotiation':
        try:
            status, deal = Story.negotiate(c, pend['deal'], choice, rng)
        except ValueError as ex:
            raise LiteError(str(ex)) from ex
        if status == 'counter':
            c.pending = dict(pend, deal=deal)
            return '구단이 조건을 다시 제시했어요. 다음 협상에서 조율해 주세요.'
        flags = dict(c.flags or {}, posted=True)
        if status == 'signed':
            c.league = deal.get('entry_league') or ('npb1' if deal['system'] == 'npb' else 'mlb')
            c.club = deal['team']
            flags['contract'] = Contracts.signed(deal, c.year)
            flags.pop('move', None)
            flags.pop('mlb_camp_season', None)
            flags.pop('mlb_bench_season', None)
            flags.pop('pin', None)
            flags['trust'] = 65 if deal['role'] == '핵심 선수' else TRUST_START
            text = f"해외 협상에 성공했어요 — {W.PRO_TEAM[c.club]['name']}, {deal['years']}년 · 연 {man(deal['annual'])} · {deal['role']}"
        else:
            text = '해외 협상이 결렬됐어요. KBO에 남아 다음 기회를 준비해요.'
        c.flags = flags
        Story.change(c, text, confidence=8 if status == 'signed' else -6)
        c.flags['press'] = list(c.flags.get('press') or []) + [press('[협상]', text)]
        c.pending = plan_step(c, rng)
        return text
    if what == 'contract_optout':
        try:
            text = Contracts.optout_reply(c, choice)
        except ValueError as ex:
            raise LiteError(str(ex)) from ex
        if choice == 'market':
            c.league, c.club = 'kbo2', c.team
            c.flags.pop('move', None)
            c.pending = dict(kind='decision', what='posting', offers=Story.posting_offers(c, rng), origin='optout')
        else:
            c.pending = next_step(c, rng)
        return text
    if what == 'moment':
        ms, i = pend['moments'], int(pend.get('i', 0))
        m = ms[i]
        r = play_moment(c, m, choice, rng)
        Story.change(c, '결정적 순간에서 ' + ('기회를 살렸어요' if r['ok'] else '기회를 놓쳤어요'),
                     confidence=12 if r['ok'] else -9, fame=4 if r['ok'] else 0)
        won, story = moment_outcome(m, r, rng)
        label = dict((x[0], x[1]) for x in m['choices'])[choice]
        d = {'kind': m['kind'], 'key': m['key'], 'stage': m['stage'], 'when': m['when'], 'choice': label,
             'text': story, 'line': r['line'], 'ok': r['ok'], 'won': won}
        d['result'] = moment_result_text(d)
        done = list(pend.get('done') or []) + [d]
        fx = moment_fx(c, m, r, d, more=i + 1 < len(ms))
        if i + 1 < len(ms):
            c.pending = dict(pend, i=i + 1, done=done)
            c.flags = dict(c.flags or {}, moment_fx=fx)
            return f"{story} → {d['result']}"
        season = c.seasons.get(year=pend['year'])
        c.flags = dict(c.flags or {})
        resolve_moments(c, season, done, rng)
        season.save()
        wrap_season(c, season, rng)
        c.pending['moments'] = done
        c.flags = dict(c.flags or {}, moment_fx=fx)
        return f"{story} → {d['result']}"
    if what == 'awaken':
        text = awaken(c, choice, rng)
        c.pending = plan_step(c, rng)
        return text
    if what == 'meeting':
        text, items = resolve_meeting(c, pend, choice, rng)
        if c.retired_at:
            return text
        if pend.get('phase') == 'mid':
            state = pend['half']
            state['news'].append(text)
            state['press'].extend(items)
            c.pending = {}
            finish_season(c, state, rng)
        elif pend.get('phase') == 'camp':
            c.flags['press'] = list(c.flags.get('press') or []) + items
            c.pending = pend['plan']
        else:
            c.flags['press'] = list(c.flags.get('press') or []) + items
            c.ovr = R.overall(c.role, c.stats)
            c.pending = next_step(c, rng, skip_meeting=True)
            _army_tick(c, rng)
        return text
    flags = dict(c.flags or {})
    text = ''
    old_club, nm = c.club, c.name
    news = []
    if what == 'draft':
        offer, abroad = pend.get('offer'), pend.get('abroad') or {}
        college = pend.get('from') == 'univ'
        c.age = max(c.age, 23 if college else 19)
        if choice == 'sign' and offer:
            c.league = 'kbo2' if college or c.ovr >= W.level('kbo2') - 4 else 'kbo3'
            c.club = offer['team']
            text = f"{W.PRO_TEAM[offer['team']]['name']}에 입단했어요 — {offer['round']}라운드 {offer['in_round']}순위"
            news.append(press('[드래프트]', f"{W.PRO_TEAM[offer['team']]['short']}, {offer['round']}라운드 {offer['in_round']}순위로 "
                                         f"{W.club_short(pend.get('from') or 'hs', old_club)} {nm} 지명"))
        elif choice == 'develop' and not offer:
            c.league, c.club = 'kbo3', c.team
            text = f"{W.PRO_TEAM[c.team]['name']}와 육성선수 계약을 맺었어요"
            news.append(press('', f"드래프트 미지명 {nm}, {W.PRO_TEAM[c.team]['short']} 육성선수로 재도전"))
        elif _split_pick(choice)[0] in abroad:
            choice, pick = _split_pick(choice)
            teams = _teams_of(abroad[choice])
            ladder = W.SYSTEMS[choice]
            c.league = ladder[1] if college and choice == 'mlb' else ladder[0]
            c.club = pick if pick in teams else teams[0]
            Development.mark_entry(c, pend.get('from'), choice)
            flags = dict(c.flags or {})
            text = f"{W.SYSTEM_NAME[choice]}{josa(W.SYSTEM_NAME[choice], '으로/로')} 진출했어요 — {W.PRO_TEAM[c.club]['name']}"
            news.append(press('[오피셜]', f"{W.club_short(pend.get('from') or 'hs', old_club)} {nm}, {W.PRO_TEAM[c.club]['name']} 계약…{W.SYSTEM_NAME[choice]} 직행"))
        elif choice == 'univ' and not college and school in (pend.get('univs') or []):
            c.age = 19
            c.league, c.club, c.grade = 'univ', school, 1
            text = f'{school}에 진학했어요 — 4년 뒤 다시 드래프트에 나가요'
            news.append(press('', f"{nm}, 프로 대신 {school} 진학…‘4년 뒤를 보겠다’"))
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
        if W.is_pro(c.league):
            c.grade = 0
    elif what == 'military':
        if choice == 'sangmu':
            flags['army'] = {'kind': 'sangmu', 'left': 2, 'back': [c.league, c.club]}
            c.league, c.club = 'kbo2', '국군체육부대(상무)'
            text = '상무에 입대했어요 — 퓨처스리그에서 2년 동안 뛰어요'
            news.append(press('', f"{nm}, 상무 입대…‘더 강해져서 돌아오겠다’"))
        elif choice == 'active':
            flags['army'] = {'kind': 'active', 'left': 2, 'back': [c.league, c.club]}
            text = '현역으로 입대했어요 — 2년 동안 야구를 쉬어요'
            news.append(press('', f"{nm}, 현역 입대…2년간 야구공 내려놓는다"))
        elif choice == 'later' and not pend.get('forced'):
            text = '입대를 미뤘어요'
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
    elif what == 'posting':
        if 'offers' in pend:
            if choice == 'stay':
                c.flags = dict(c.flags or {}, posted=True)
                c.pending = plan_step(c, rng)
                return '이번에는 KBO에 남기로 했어요.'
            offer = next((o for o in pend['offers'] if o['key'] == choice), None)
            if not offer:
                raise LiteError('관심을 보인 세 구단 가운데 하나를 골라 주세요.')
            c.pending = {'kind': 'decision', 'what': 'negotiation', 'deal': dict(offer, round=0)}
            return f"{W.PRO_TEAM[offer['team']]['name']}와 협상을 시작해요."
        flags['posted'] = True
        choice, pick = _split_pick(choice)
        teams = _teams_of((pend.get('teams') or {}).get(choice)) or (abroad_teams(choice, rng) if choice in ('mlb', 'npb') else [])
        pick = pick if pick in teams else (teams[0] if teams else '')
        if choice == 'mlb':
            c.league = 'mlb' if c.ovr >= W.level('mlb') - 1 else 'mlb_aaa'
            c.club = pick
            text = f"포스팅으로 {W.PRO_TEAM[c.club]['name']}에 입단했어요!"
            news.append(press('[속보]', f"{nm}, 포스팅으로 {W.PRO_TEAM[c.club]['name']} 입단…‘꿈의 무대로’"))
        elif choice == 'npb':
            c.league, c.club = 'npb1', pick
            text = f"포스팅으로 {W.PRO_TEAM[c.club]['name']}에 입단했어요!"
            news.append(press('[속보]', f"{nm}, 포스팅으로 {W.PRO_TEAM[c.club]['name']} 입단…‘일본 무대 도전’"))
        elif choice == 'stay':
            text = 'KBO에 남기로 했어요'
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
    elif what == 'fa':
        flags['fa'] = True
        deal = next((o for o in pend.get('offers') or [] if o['key'] == choice), None)
        if not deal:
            raise LiteError('계약 조건을 다시 골라 주세요.')
        if deal['key'].startswith('mlb'):
            # FA 제안도 구단 선택만으로 즉시 입단하지 않고 같은 계약 협상을 거친다.
            d = Contracts.terms(dict(deal, system='mlb', role='주전 경쟁', interest=.6,
                                     budget=round(deal['annual'] * 1.15), round=0))
            c.flags = dict(flags)
            c.pending = dict(kind='decision', what='negotiation', deal=d, origin='fa')
            return f"{W.PRO_TEAM[deal['team']]['name']}의 FA 제안을 골랐어요. 연봉과 마이너 거부권을 협상해요."
        elif deal['key'].startswith('npb'):
            c.league = 'npb1'
        c.club = deal['team']
        flags['contract'] = {'years': deal['years'], 'annual': deal['annual']}
        text = f"FA 계약을 맺었어요 — {W.PRO_TEAM[c.club]['name']}, {deal['years']}년 총 {man(deal['annual'] * deal['years'])}"
        news.append(press('[오피셜]', f"{nm} FA 계약…{W.PRO_TEAM[c.club]['name']}·{deal['years']}년 총액 {man(deal['annual'] * deal['years'])}"))
    elif what == 'return':
        flags['return_offered'] = True
        offers = pend.get('offers')
        if offers is None:                                    # 예전 화면(제안 목록이 없던 때) — 희망 구단으로
            offers = [{'key': 'kbo', 'team': c.team, 'league': 'kbo1' if c.ovr >= W.level('kbo1') - 4 else 'kbo2',
                       'years': 0, 'annual': 0}]
        deal = next((o for o in offers if o['key'] == choice), None)
        if deal:
            left = (flags.pop('contract', None) or {}).get('years', 0)
            c.league, c.club = deal['league'], deal['team']
            team = W.PRO_TEAM[c.club]['name']
            if deal['years']:
                flags['contract'] = {'years': deal['years'], 'annual': deal['annual']}
            if deal['key'] == 'self':
                text = f'해외 생활을 정리하고 돌아왔어요 — {team} 퓨처스에서 다시 시작해요'
                news.append(press('[오피셜]', f"{nm}, 해외 생활 정리하고 유턴…{team} 퓨처스서 재출발"))
            elif deal['years']:
                total = man(deal['annual'] * deal['years'])
                text = f"KBO로 돌아왔어요 — {team}, {deal['years']}년 총 {total}"
                news.append(press('[오피셜]', f"{nm}, KBO 복귀…{team}와 {deal['years']}년 총액 {total}"))
            else:
                text = f'KBO로 돌아왔어요 — {team}'
                news.append(press('[오피셜]', f"{nm}, KBO 복귀…{team} 유니폼"))
            if left > 0:
                text += f'(남은 해외 계약 {left}년은 포기했어요)'
        elif choice == 'stay':
            text = '해외에 남아서 계속 도전해요'
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
    elif what == 'retire':
        if choice == 'retire':
            return retire(c)
        if choice != 'continue':
            raise LiteError('계속 뛸지 은퇴할지 골라 주세요.')
        text = '한 시즌 더 뛰어요'
    elif what in ('released', 'end'):
        return retire(c, '방출' if what == 'released' else '나이')
    if c.club != old_club:
        flags['trust'] = TRUST_START
        flags.pop('move', None)
        flags.pop('pin', None)
    if news:
        flags['press'] = list(flags.get('press') or []) + news
    c.flags = flags
    c.ovr = R.overall(c.role, c.stats)
    if what == 'return' and choice == 'stay' and c.age >= RETIRE_FROM:
        c.pending = {'kind': 'decision', 'what': 'retire'}                # 해외에 남아도 은퇴는 물어본다
    else:
        c.pending = plan_step(c, rng)
    _army_tick(c, rng)
    return text


def _army_tick(c, rng):
    """현역 복무 중이면 비시즌·시즌을 건너뛴다(2년, 능력치 조금 빠짐)."""
    from .models import LiteSeason
    army = (c.flags or {}).get('army')
    if not army or army.get('kind') != 'active':
        return
    while army['left'] > 0:
        ovr_start, lost = c.ovr, {}
        for k in c.stats:
            old = float(c.stats[k])
            c.stats[k] = round(max(25.0, old - rng.uniform(1.0, 2.5)), 1)
            lost[k] = round(c.stats[k] - old, 1)
        c.ovr = R.overall(c.role, c.stats)
        LiteSeason.objects.create(career=c, year=c.year, age=c.age, league=c.league, club=c.club, duty='현역 복무',
                                  games=0, ovr_start=ovr_start, ovr_end=c.ovr, news=['군 복무 중이에요 — 실전을 쉬어 능력치가 조금씩 빠져요'],
                                  deltas=dict(lost, _why={k: [['현역 복무(실전 공백)', v]] for k, v in lost.items()}))
        c.year += 1
        c.age += 1
        army['left'] -= 1
    c.flags['served'] = True
    c.league, c.club = army['back']
    c.flags.pop('army', None)


def army_after_season(c):
    """상무 시즌을 마치면 남은 기간을 줄이고, 끝나면 원래 팀으로."""
    army = (c.flags or {}).get('army')
    if not army or army.get('kind') != 'sangmu':
        return ''
    army['left'] -= 1
    if army['left'] <= 0:
        c.flags['served'] = True
        back_league, back_club = army['back']
        c.league = 'kbo1' if c.ovr >= W.level('kbo1') - 1 else back_league
        c.club = back_club
        c.flags.pop('army', None)
        return f"상무에서 전역했어요 — {W.club_label(c.league, c.club)}로 복귀"
    c.league = 'kbo2'
    return ''


# 스스로 은퇴 제한(2026-10-19 사용자 요청) — 만든 뒤 5시즌 전에는 '여기서 은퇴하기'를 못 하고(능력치를 보고 갈아엎는 판 막기),
# 스스로 은퇴하면 5분 동안 새 선수를 못 만든다. 게임이 권하는 은퇴(retire 결정)·방출·나이 은퇴는 그대로다.
QUIT_MIN_SEASONS = 5
QUIT_WAIT = 300             # 초


def check_quit(c):
    n = c.seasons.count()
    if n < QUIT_MIN_SEASONS:
        raise LiteError(f'선수를 만든 뒤 {QUIT_MIN_SEASONS}시즌은 뛰어야 스스로 은퇴할 수 있어요. 지금 {n}시즌을 뛰었어요.')


def quit_wait(mine) -> int:
    """스스로 은퇴한 뒤 새 선수를 만들기까지 남은 시간(초) — 0이면 바로."""
    last = mine.filter(retired_at__isnull=False).order_by('-retired_at').first()
    if not last or (last.pending or {}).get('why') != '스스로':
        return 0
    return max(0, int(math.ceil(QUIT_WAIT - (timezone.now() - last.retired_at).total_seconds())))


def wait_text(sec: int) -> str:
    m, s = divmod(sec, 60)
    return f'{m}분 {s}초' if m and s else f'{m}분' if m else f'{s}초'


def retire(c, why: str = '') -> str:
    Balance.settle_guarantee(c)
    c.retired_at = timezone.now()
    c.pending = {'kind': 'retired', 'why': why}
    return {'방출': '방출됐어요 — 유니폼을 벗었어요', '나이': '마흔둘, 유니폼을 벗었어요'}.get(why, '은퇴를 선언했어요')


# ───────────────────────────── 화면·순위용
def decision_view(c) -> dict | None:
    pend = c.pending or {}
    if pend.get('kind') != 'decision':
        return None
    if pend.get('what') == 'contract_optout':
        d = Contracts.active(c) or {}
        return dict(Contracts.optout_view(c, f'{c.pk}:{c.year}:optout:{d.get("elapsed", 0)}'),
                    what='contract_optout', contract_scene=True)
    if pend.get('what') == 'negotiation':
        return dict(Story.deal_view(c, pend['deal']), what='negotiation', kind='negotiation',
                    id=f"{c.pk}:{c.year}:{pend['deal']['team']}:{pend['deal'].get('round', 0)}")
    if pend.get('what') == 'meeting':
        view = dict(meeting_view(c, pend), what='meeting')
        if view.get('contract_scene') and not view.get('id'):
            # 기존 저장 장면도 같은 식별자를 만든다. 단순 규칙 검사와 달리
            # 실제 폼은 event_id 검증을 거치므로 선발 수업·재계약에도 필요하다.
            stamp = hashlib.sha256(json.dumps(pend, sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()[:16]
            view['id'] = f'{c.pk}:{c.year}:meeting:{stamp}'
        return view
    if pend.get('what') == 'moment':
        i = int(pend.get('i', 0))
        return dict(moment_view(c, pend['moments'][i]), what='moment', i=i + 1, n=len(pend['moments']),
                    done=pend.get('done') or [])
    v = dict(pend)
    v['who'] = DECISION_WHO.get(pend.get('what'), 'lead')
    v['who_name'], v['who_role'] = who_is(c, v['who'])
    if pend.get('what') == 'draft':
        v['team'] = W.PRO_TEAM.get((pend.get('offer') or {}).get('team', ''), {})
        v['abroad_list'] = [{'system': k, 'name': W.SYSTEM_NAME[k], 'teams': [W.PRO_TEAM[t] for t in _teams_of(ts)]}
                            for k, ts in (pend.get('abroad') or {}).items()]
    if pend.get('what') == 'posting':
        v['posting_offers'] = [dict(o, team_name=W.PRO_TEAM[o['team']]['name'], money=man(o['annual']))
                               for o in pend.get('offers') or []]
        if 'offers' in pend:
            v.update(offers=v['posting_offers'], background='negotiation-room', title='관심 구단 세 곳에서 제안이 왔어요' if v['posting_offers'] else '현재 해외 계약 제안이 없어요',
                     id=f'{c.pk}:{c.year}:posting')
        v['posting_list'] = [{'system': k, 'name': W.SYSTEM_NAME[k], 'teams': [W.PRO_TEAM[t] for t in _teams_of(ts)]}
                             for k, ts in (pend.get('teams') or {}).items()]
    if pend.get('what') == 'fa':
        v['offer_list'] = [dict(o, team_name=W.PRO_TEAM[o['team']]['name'], money=man(o['annual']),
                                total=man(o['annual'] * o['years'])) for o in pend.get('offers') or []]
    if pend.get('what') == 'awaken':
        v['odds_pct'] = int(round((awaken_odds(c) if pend.get('odds') is None else float(pend['odds'])) * 100))
        v['next_n'] = awakened(c) + 1
        v['plus'] = f'{awaken_gain(c):g}'
    if pend.get('what') == 'return':
        v['abroad_name'] = W.SYSTEM_NAME.get(pend.get('system') or W.system_of(c.league), '해외')
        v['offer_list'] = [dict(o, team_name=W.PRO_TEAM[o['team']]['name'], team_color=W.PRO_TEAM[o['team']]['color'],
                                money=man(o['annual']), total=man(o['annual'] * o['years']), want=o['team'] == c.team)
                           for o in pend.get('offers') or []]
        v['legacy'] = 'offers' not in pend
        v['contract_left'] = ((c.flags or {}).get('contract') or {}).get('years', 0)
    return v


def career_line(c) -> dict:
    """통산(프로) 줄과 리그별 줄."""
    from .rookie_legacy import _sum
    seasons = list(c.seasons.all())
    by, development = {}, []
    for season in seasons:
        for row in season.splits or [dict(league=season.league, totals=season.totals, war=season.war)]:
            if row['league'] in W.TOP_LEAGUES:
                by.setdefault(W.system_of(row['league']), []).append((season.year, row))
            elif W.is_pro(row['league']):
                development.append(row)
    pro = [r for v in by.values() for _year, r in v]
    total = _sum(r['totals'] for r in pro)
    return {'pro': L.line_view(c.role, total) if pro else None,
            'top_war': round(sum(r['war'] for r in pro), 1),
            'development': L.line_view(c.role, _sum(r['totals'] for r in development)) if development else None,
            'systems': [{'name': W.SYSTEM_NAME[k], 'seasons': len({y for y, _r in v}),
                         'war': round(sum(r['war'] for _y, r in v), 1),
                         'v': L.line_view(c.role, _sum(r['totals'] for _y, r in v))} for k, v in by.items()]}


HALL_SYSTEMS = ('kbo', 'mlb', 'npb', 'cpbl')
# 1.0 출시(2026-10-19 21:00) — 명예의 전당은 이때부터 시작한 커리어만(사용자 요청: 카드는 남기고 랭킹은 비운다).
# 그 전 커리어도 커리어 페이지·은퇴 카드·카드 보관함에는 그대로 남는다.
HALL_SINCE = timezone.make_aware(datetime(2026, 10, 19, 21, 0))


def day_bounds(days_ago: int = 0) -> tuple:
    """그날(한국 시간 0시~다음 날 0시) — 일일 랭킹."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return start, start + timedelta(days=1)


def hall(system: str = 'kbo', limit: int = 50, role: str = '', since=None, until=None) -> list:
    """은퇴한 라이트 커리어 순위 — 나라 리그(system)별로만, 킥루 순서(MVP → 최고 OVR → 수상 → WAR).
    리그를 섞은 전체 순위는 없앴다(2026-10-19 사용자 요청: 리그별로 헷갈리고 가중치가 잘 맞지 않는다).
    role('pitcher'·'batter')을 주면 투수·타자만 — 통산 줄(line)도 붙인다."""
    system = system if system in HALL_SYSTEMS else 'kbo'
    from .game_visibility import rookie_visible as visible
    from .models import LiteCareer
    qs = visible(LiteCareer.objects.filter(retired_at__isnull=False, user__isnull=False, created_at__gte=HALL_SINCE), 'user') \
        .prefetch_related('seasons')                                       # 손님 판은 로그인해 계정으로 옮겨야 오른다
    if role in ('pitcher', 'batter'):
        qs = qs.filter(role=role)
    if since:                                                              # 일일 랭킹 — 그날 은퇴한 커리어만
        qs = qs.filter(retired_at__gte=since)
    if until:
        qs = qs.filter(retired_at__lt=until)
    rows = []
    for c in qs[:2000]:
        seasons = [s for s in c.seasons.all() if s.games and any(W.system_of(r['league']) == system for r in Balance.top_splits(s))]
        if not seasons:
            continue
        mvp = sum(1 for s in seasons for a in s.awards if a['kind'] == 'mvp')
        awards = sum(1 for s in seasons for a in s.awards if a['kind'] in ('mvp', 'rookie', 'gg', 'ace', 'title', 'minor'))
        rings = sum(1 for s in seasons for a in s.awards if a['kind'] == 'ring')
        war = Balance.totals(c, system)['war']
        best = max([s.ovr_end for s in seasons] or [c.best_ovr])
        pro = [s for s in seasons if W.is_pro(s.league)]
        last = max(seasons, key=lambda s: s.year)
        rows.append({'c': c, 'mvp': mvp, 'awards': awards, 'rings': rings, 'war': war,
                     'best': round(best, 1), 'seasons': len(seasons),
                     'peak': W.short(max((s.league for s in seasons), key=W.level)),       # 이 나라에서 가장 높이 오른 곳
                     'line': L.line_view(c.role, Balance.totals(c, system)['totals']) if role and pro else None,
                     'color': W.club_color(last.league, last.club)})
    rows.sort(key=lambda r: (r['mvp'], r['best'], r['awards'], r['war']), reverse=True)
    return rows[:limit]


# 역대 베스트 라인업(2026-10-19 사용자 요청) — 자리마다 프로 WAR 1위(외야는 셋). 그라운드 그림 위 좌표(%, 홈플레이트가 아래 가운데)
LINEUP = (('CF', '중견수', 50, 13), ('LF', '좌익수', 17, 26), ('RF', '우익수', 83, 26), ('SS', '유격수', 32, 46),
          ('2B', '2루수', 68, 46), ('3B', '3루수', 16, 62), ('1B', '1루수', 84, 62), ('SP', '선발 투수', 50, 62),
          ('C', '포수', 50, 88))
BENCH = (('DH', '지명타자'), ('RP', '구원 투수'))


def best_lineup(rows) -> dict:
    """명예의 전당 줄(hall)에서 자리마다 WAR 가 가장 높은 사람 — 한 사람은 한 자리만. 비면 None."""
    pool = sorted(rows, key=lambda r: r['war'], reverse=True)
    used, pick = set(), {}

    def take(slot, test):
        r = next((r for r in pool if r['c'].pk not in used and test(r['c'])), None)
        if r:
            used.add(r['c'].pk)
        pick[slot] = r
    take('SP', lambda c: c.role == 'pitcher' and c.position == 'SP')
    take('RP', lambda c: c.role == 'pitcher' and c.position == 'RP')
    for slot in ('C', '1B', '2B', '3B', 'SS', 'DH'):
        take(slot, lambda c, s=slot: c.role == 'batter' and c.position == s)
    for slot in ('CF', 'LF', 'RF'):
        take(slot, lambda c: c.role == 'batter' and c.position == 'OF')
    return {'field': [{'slot': s, 'label': lab, 'x': x, 'y': y, 'r': pick.get(s)} for s, lab, x, y in LINEUP],
            'bench': [{'slot': s, 'label': lab, 'r': pick.get(s)} for s, lab in BENCH],
            'filled': sum(1 for v in pick.values() if v)}


def _sum_totals(seasons) -> dict:
    t = {}
    for s in seasons:
        t = L.add(t, s.totals or {})
    return t


def _full_time(role: str, p: dict) -> bool:
    """그 몫에서 제대로 뛰었나 — 타자는 경기당 2.5타석, 선발은 경기당 0.6이닝, 불펜은 0.25이닝."""
    t, G = p.get('totals') or {}, max(1.0, float(p.get('G') or 1))
    if role == 'pitcher':
        sp = p.get('role') == 'sp' or (not p.get('role') and t.get('gs', 0) >= 5)
        return t.get('outs', 0) / 3 >= G * (0.6 if sp else 0.25)
    return t.get('pa', 0) >= G * 2.5


def career_high(c, seasons=None) -> dict | None:
    """커리어 하이 — 가장 높은 무대(리그 수준)에서 제대로 뛴 몫 가운데 WAR 가 가장 좋은 것(2026-10-18 사용자 요청).
    시즌 중에 리그를 옮겼으면 리그별 몫(splits)으로 본다. 가장 높은 무대에선 잠깐만 뛰었으면 한 계단 아래 무대로."""
    seasons = list(c.seasons.all()) if seasons is None else seasons
    parts = []
    for s in seasons:
        if not s.games:
            continue
        for p in (s.splits or [{'league': s.league, 'totals': s.totals, 'war': s.war, 'G': s.games, 'role': ''}]):
            if W.is_pro(p['league']) and p.get('totals'):
                parts.append((s, p))
    if not parts:
        return None
    pick = None
    for lvl in sorted({W.level(p['league']) for _s, p in parts}, reverse=True):
        pool = [x for x in parts if W.level(x[1]['league']) == lvl and _full_time(c.role, x[1])]
        if pool:
            pick = max(pool, key=lambda x: x[1]['war'])
            break
    s, p = pick or max(parts, key=lambda x: (W.level(x[1]['league']), x[1]['war']))
    return {'year': cal_year(c, s.year), 'age': s.age, 'league': W.short(p['league']), 'line': _short(c.role, p['totals']),
            'war': p['war']}


def retire_headline(c, seasons: int) -> dict:
    """은퇴 카드 머리기사."""
    ep = EPITHET.get(c.style, '')
    why = (c.pending or {}).get('why', '')
    tail = {'방출': '…그라운드와 작별', '나이': '…마흔둘까지 뛰었다'}.get(why, '…박수 받으며 떠난다')
    return press('[은퇴]', f"‘{ep}’ {c.name}, {seasons}시즌 현역 마침표{tail}")


# ───────────────────────────── 결정적 순간(2026-10-18 사용자 요청: 한국시리즈·중요한 경기에서 구종 선택·게스 히팅·안전한 컨택)
# 결승(최종 시리즈·국가대표 결승·고교/대학 대회 결승)에 오르면 승부처 한 타석을 내가 고른다 — 결과가 우승을 가른다.
# 결승 진출 확률은 예전 우승 확률의 두 배(KBO 1위는 직행). 성공 85%·실패 15% 로 평균 절반쯤 이긴다.
SERIES_NAME = {'kbo1': '한국시리즈', 'mlb': '월드시리즈', 'npb1': '일본시리즈', 'cpbl': '대만시리즈'}
WIN_IF, WIN_ELSE = 0.85, 0.15
POST_ROUND = {'kbo1': '플레이오프', 'npb1': '클라이맥스 시리즈', 'mlb': '포스트시즌', 'cpbl': '플레이오프'}
OUT_PITCHES = ('슬라이더', '포크', '커브', '체인지업', '커터', '스플리터')
# 국제대회 결승 상대 — 대회마다 실제로 나오는 나라만(2026-10-18 사용자 지적: 아시안게임 결승에 쿠바가 나왔다).
# (나라, 무게, 이름 묶음) — 이름 묶음은 INTL_NAMES
INTL_FIELD = {
    'asian': (('일본', 6, 'jp'), ('대만', 5, 'tw'), ('중국', 1, 'cn')),
    'olympics': (('일본', 5, 'jp'), ('미국', 4, 'us'), ('도미니카공화국', 3, 'latin'), ('멕시코', 2, 'latin'), ('이스라엘', 1, 'us')),
    'wbc': (('일본', 5, 'jp'), ('미국', 5, 'us'), ('도미니카공화국', 4, 'latin'), ('베네수엘라', 3, 'latin'), ('푸에르토리코', 3, 'latin'),
            ('쿠바', 2, 'latin'), ('멕시코', 2, 'latin'), ('대만', 1, 'tw')),
    'premier12': (('일본', 5, 'jp'), ('대만', 4, 'tw'), ('미국', 3, 'us'), ('멕시코', 2, 'latin'), ('베네수엘라', 2, 'latin'),
                  ('도미니카공화국', 1, 'latin')),
}
INTL_NAMES = {
    'jp': ABROAD_NAMES['npb'], 'tw': ABROAD_NAMES['cpbl'],
    'cn': (('왕', '리', '장', '류', '천', '양', '자오'), ('웨이', '하오', '레이', '펑', '양', '친', '밍'), ''),
    'us': (('제이크', '타일러', '라이언', '브랜든', '카일', '저스틴', '오스틴', '네이선', '코디', '트래비스'),
           ('존슨', '밀러', '윌리엄스', '브라운', '데이비스', '앤더슨', '테일러', '무어', '클라크', '해리스'), ' '),
    'latin': (('호세', '루이스', '카를로스', '라파엘', '미겔', '후안', '페드로', '라몬', '엔리케', '프란시스코'),
              ('로드리게스', '마르티네스', '곤살레스', '페레스', '에르난데스', '라미레스', '디아스', '산체스', '토레스', '레예스'), ' '),
}


def intl_rival(key: str, rng) -> str:
    """'일본 다카하시 쇼타' — 그 대회에 나오는 나라와 그 나라 이름으로."""
    field = INTL_FIELD.get(key) or INTL_FIELD['premier12']
    country, _w, pool = rng.choices(field, [x[1] for x in field])[0]
    a, b, sep = INTL_NAMES[pool]
    return f'{country} {rng.choice(a)}{sep}{rng.choice(b)}'
HITTER_TYPES = {'fast': ('직구에 강하고 떨어지는 공에 약해요', {'fast': -8, 'break': 10, 'edge': 0}),
                'break': ('변화구를 잘 받아치고 빠른 공에 늦어요', {'fast': 10, 'break': -8, 'edge': 0}),
                'patient': ('공을 끝까지 보는 타자예요 — 볼넷을 잘 골라요', {'fast': 6, 'break': -6, 'edge': -6})}
OUTCOME_KO = {'HR': '홈런', '3B': '3루타', '2B': '2루타', '1B': '안타', 'BB': '볼넷', 'HBP': '몸에 맞는 공', 'SO': '삼진', 'OUT': '범타'}


def _bases_text(b) -> str:
    on = [n for n, x in zip(('1루', '2루', '3루'), b) if x]
    return '만루' if len(on) == 3 else ('·'.join(n[0] for n in on) + '루') if len(on) == 2 else on[0] if on else '주자 없음'


def make_moment(c, kind: str, stage: str, when: str, rng, key: str = '', opp_name: str = '') -> dict:
    """승부처 한 장면 — 타자는 노림수(직구·결정구·짧게), 투수는 구종(직구·유인구·코너)."""
    lvl = W.level(c.league) if kind != 'intl' else INTL_LEVEL
    nm = c.name
    if c.role == 'batter':
        walkoff = rng.random() < 0.6
        sit = ({'inning': '9회말', 'outs': 2, 'bases': [False, True, True], 'score': '3 : 4', 'need': 'hit'} if walkoff else
               {'inning': '8회초', 'outs': 1, 'bases': [False, False, True], 'score': '2 : 2', 'need': 'run'})
        fast = rng.choice((75, 65, 50, 35, 25))
        pitch = rng.choice(OUT_PITCHES)
        opp = {'name': opp_name or rival_name(c.league, rng), 'role': '마무리' if walkoff else '필승조',
               'fast': fast, 'pitch': pitch, 'lvl': round(lvl + 8, 1),
               'scout': f'직구 {fast}% · 결정구 {pitch}' + (' — 직구로 밀어붙여요' if fast >= 65 else f' — {pitch}를 즐겨 던져요' if fast <= 35 else ' — 반반, 읽기 어려워요')}
        text = (f"{sit['inning']} {sit['outs']}사 {_bases_text(sit['bases'])}, 1점 차로 지고 있어요. 주자 둘이 들어오면 끝내기예요!"
                if walkoff else f"{sit['inning']} {sit['outs']}사 3루, 동점이에요. 깊은 외야 뜬공이면 희생플라이를 노릴 수 있어요.")
        choices = [('fast', '직구 노려 치기', '게스 히팅', '직구가 오면 크게 — 아니면 헛스윙 위험'),
                   ('break', f'{pitch} 노려 치기', '게스 히팅', f'{pitch}가 오면 크게 — 직구엔 늦어요'),
                   ('short', '짧게 끊어 치기', '안전하게', '삼진은 줄고 장타는 줄어요')]
    else:
        late = c.position != 'SP' or rng.random() < 0.5
        sit = ({'inning': '9회말', 'outs': 2, 'bases': [True, True, True], 'score': '4 : 3', 'need': 'out'} if late else
               {'inning': '7회말', 'outs': 1, 'bases': [True, False, True], 'score': '2 : 2', 'need': 'hold'})
        htype = rng.choice(list(HITTER_TYPES))
        my_pitch = (M.pitch_profile(c.stats).get('pitches') or ['직구', '슬라이더'])[-1]
        if my_pitch == '직구':
            my_pitch = '슬라이더'
        opp = {'name': opp_name or rival_name(c.league, rng), 'role': '4번 타자', 'type': htype, 'pitch': my_pitch,
               'lvl': round(lvl + 8, 1), 'scout': HITTER_TYPES[htype][0]}
        text = (f"{sit['inning']} {sit['outs']}사 만루, 1점 차로 이기고 있어요. 이 타자만 잡으면 우승이에요!" if late else
                f"{sit['inning']} {sit['outs']}사 1·3루, 동점이에요. 여기서 막아야 해요.")
        choices = [('fast', '직구로 정면 승부', '힘', '구위로 누른다 — 직구에 강한 타자면 위험'),
                   ('break', f'{my_pitch}로 유인', '유인', '헛스윙을 노린다 — 손에서 빠지면 볼넷'),
                   ('edge', '스트라이크존 구석 공략', '정교', '장타를 억제해요 — 코너를 벗어나면 볼넷 위험')]
    return {'kind': kind, 'key': key, 'stage': stage, 'when': when, 'side': 'bat' if c.role == 'batter' else 'pit',
            'sit': sit, 'opp': opp, 'text': text, 'choices': [list(x) for x in choices], 'name': nm}


def moment_view(c, m: dict) -> dict:
    name, role = who_is(c, 'critic')
    sit = m['sit']
    return dict(m, who='critic', who_name=name, who_role=role, bases=sit['bases'],
                outs=[i < sit['outs'] for i in range(3)],
                choices=[{'key': k, 'label': lab, 'tone': tone, 'hint': h} for k, lab, tone, h in m['choices']])


# 고른 수가 결과 확률을 얼마나 바꾸나 — 능력치로 낸 확률에 곱한다(남는 몫은 범타). 스카우팅 리포트를 읽으면 이득.
TILT_BAT = {'hit': {'SO': .4, '1B': 1.7, '2B': 2.0, '3B': 2.0, 'HR': 2.8},          # 노림수 적중
            'miss': {'SO': 2.2, '1B': .45, '2B': .4, '3B': .4, 'HR': .25, 'BB': .8},  # 노림수 빗나감
            'short': {'SO': .6, '1B': 1.35, '2B': .9, '3B': .9, 'HR': .35, 'BB': 1.1}}  # 짧게 끊어 치기
TILT_PIT = {'good': {'SO': 1.6, '1B': .6, '2B': .55, '3B': .55, 'HR': .45},           # 약점을 찔렀다
            'bad': {'SO': .6, '1B': 1.5, '2B': 1.7, '3B': 1.7, 'HR': 2.2},             # 강점에 던졌다
            'calm': {'BB': .6, 'SO': 1.2}, 'walk': {'BB': 1.9, 'HR': .8}}             # 공 잘 보는 타자 상대


def _tilt(p: dict, mult: dict) -> dict:
    q = {k: v * mult.get(k, 1.0) for k, v in p.items() if k != 'OUT'}
    q['OUT'] = max(0.02, 1 - sum(q.values()))
    return q


def play_moment(c, m: dict, choice: str, rng) -> dict:
    """한 타석 — 고른 수가 맞으면 크게, 틀리면 손해. 결과 문장과 성공 여부."""
    keys = [x[0] for x in m['choices']]
    if choice not in keys:
        raise LiteError('어떻게 승부할지 골라 주세요.')
    lvl = m['opp']['lvl']
    sit = m['sit']
    if m['side'] == 'bat':
        opp = {k: lvl for k in M.PIT}
        thrown = 'fast' if rng.random() < m['opp']['fast'] / 100 else 'break'
        if choice == 'short':
            tilt, read = TILT_BAT['short'], '짧게 대응'
        elif choice == thrown:
            tilt, read = TILT_BAT['hit'], '노림수 적중'
        else:
            tilt, read = TILT_BAT['miss'], '노림수 빗나감'
        o = M._pick(_tilt(M.pa_probs(_game_stats(c), opp, risp=True), tilt), rng)
        pitch = '직구' if thrown == 'fast' else m['opp']['pitch']
        if sit['need'] == 'hit':
            ok = o in ('1B', '2B', '3B', 'HR') or (o in ('BB', 'HBP') and rng.random() < 0.45)
            text = {'HR': '끝내기 홈런! 담장을 넘어갔어요', '3B': '끝내기 3루타! 주자가 모두 들어와요', '2B': '끝내기 2루타!',
                    '1B': '끝내기 안타! 3루 주자에 이어 2루 주자까지 홈으로', 'SO': '헛스윙 삼진…', 'OUT': '잘 맞은 타구가 잡혔어요…'}.get(o, '')
            if o in ('BB', 'HBP'):
                reach = '몸에 맞는 공으로 출루했어요' if o == 'HBP' else '볼넷으로 출루했어요'
                text = reach + ' — ' + ('다음 타자가 끝내기 안타를 쳤어요!' if ok else '다음 타자가 물러났어요…')
        else:
            sac = o == 'OUT' and rng.random() < 0.5
            ok = o in ('1B', '2B', '3B', 'HR') or sac or (o in ('BB', 'HBP') and rng.random() < 0.4)
            text = {'HR': '앞서가는 2점 홈런!', '3B': '앞서가는 적시 3루타!', '2B': '앞서가는 적시 2루타!', '1B': '앞서가는 적시타!', 'SO': '헛스윙 삼진…'}.get(o, '')
            if o == 'OUT':
                text = '희생플라이로 앞서가는 한 점을 냈어요!' if sac else '내야 땅볼, 주자가 묶였어요…'
            if o in ('BB', 'HBP'):
                reach = '몸에 맞는 공으로 출루했어요' if o == 'HBP' else '볼넷으로 출루했어요'
                text = reach + ' — ' + ('다음 타자의 적시타로 앞서갔어요!' if ok else '다음 타자가 물러났어요…')
        line = f'{pitch} — {read}, {OUTCOME_KO.get(o, o)}'
        final = sit['need'] == 'hit'                     # 9회말 2사 — 이 타석(볼넷이면 다음 타석)이 경기를 끝낸다
    else:
        htype = m['opp']['type']
        bonus = HITTER_TYPES[htype][1][choice]
        hitter = {k: lvl for k in M.BAT}
        if htype == 'patient':
            hitter['eye'] = lvl + 8
            tilt = TILT_PIT['calm'] if bonus > 0 else TILT_PIT['walk']
        else:
            tilt = TILT_PIT['good'] if bonus > 0 else TILT_PIT['bad'] if bonus < 0 else {}
        if choice == 'break':
            tilt = dict(tilt, BB=tilt.get('BB', 1.0) * 1.3)              # 유인구 — 손에서 빠지면 볼넷
        elif choice == 'edge':
            tilt = dict(tilt, BB=tilt.get('BB', 1.0) * 1.2, HR=tilt.get('HR', 1.0) * .6)   # 코너 — 장타는 막고 볼넷은 늘고
        o = M._pick(_tilt(M.pa_probs(hitter, _game_stats(c), risp=True), tilt), rng)
        if sit['need'] == 'out':
            ok = o in ('SO', 'OUT')
            text = {'SO': '헛스윙 삼진! 우승을 확정했어요', 'OUT': '평범한 뜬공 — 경기 끝!', 'HR': '만루 홈런을 맞았어요…',
                    '1B': '역전 끝내기 안타를 맞았어요…', '2B': '싹쓸이 2루타를 맞았어요…', '3B': '싹쓸이 3루타를 맞았어요…',
                    'BB': '밀어내기 볼넷… 동점이에요', 'HBP': '몸에 맞는 공… 밀어내기 동점'}.get(o, '')
            if o in ('BB', 'HBP'):
                ok = rng.random() < 0.3
                text += ' — ' + ('연장 끝에 팀이 이겼어요!' if ok else '연장 끝에 졌어요…')
        else:
            sac = o == 'OUT' and rng.random() < 0.45
            ok = o == 'SO' or (o == 'OUT' and not sac)
            text = {'SO': '삼진으로 한숨 돌렸어요!', 'HR': '3점 홈런을 허용했어요…', '1B': '적시타를 맞았어요…',
                    '2B': '적시 2루타를 맞았어요…', '3B': '적시 3루타를 맞았어요…'}.get(o, '')
            if o == 'OUT':
                text = '희생플라이로 한 점을 줬어요…' if sac else '병살타! 위기를 넘겼어요'
            if o in ('BB', 'HBP'):
                ok = rng.random() < 0.4
                reach = '몸에 맞는 공으로 만루가 됐어요' if o == 'HBP' else '볼넷으로 만루가 됐어요'
                text = reach + ' — ' + ('다음 타자를 잡아냈어요!' if ok else '다음 타자에게 적시타를 맞았어요…')
        pick = dict((x[0], x[1]) for x in m['choices'])[choice]
        line = f'{pick} — {OUTCOME_KO.get(o, o)}'
        final = sit['need'] == 'out'                     # 9회말 2사 만루 — 마지막 아웃이냐 끝내기냐
    return {'ok': ok, 'text': text, 'line': line, 'outcome': o, 'final': final}


# 경기가 이어지는 승부(8회 결승점·7회 위기)의 뒷이야기 — 내 승부와 팀 결과가 다르면 왜 그렇게 됐는지 말해 준다
AFTER = {
    ('bat', True, True): '그 점수를 끝까지 지켜냈어요!',
    ('bat', True, False): '하지만 9회말 마무리가 무너져 역전패했어요…',
    ('bat', False, True): '찬스는 놓쳤지만 9회 동료가 결승타를 쳐 줬어요!',
    ('bat', False, False): '결국 그 점수 차를 넘지 못했어요…',
    ('pit', True, True): '그 기세로 타선이 결승점을 뽑았어요!',
    ('pit', True, False): '하지만 불펜이 9회에 결승점을 내줬어요…',
    ('pit', False, True): '실점했지만 9회 타선이 다시 뒤집어 줬어요!',
    ('pit', False, False): '그 점수가 결승점이 됐어요…',
}


def moment_outcome(m: dict, r: dict, rng) -> tuple:
    """(이겼나, 문장) — 경기를 끝내는 승부면 내 결과가 곧 승패, 이어지는 승부면 확률로 정하고 뒷이야기를 붙인다
    (2026-10-18 사용자 지적: 결정타를 쳤다고 나오는데 준우승이었다)."""
    if r.get('final'):
        return r['ok'], r['text']
    won = rng.random() < (WIN_IF if r['ok'] else WIN_ELSE)
    return won, f"{r['text']} {AFTER[(m['side'], r['ok'], won)]}"


# 결정적 순간 결과 연출(2026-10-19 사용자 요청: 각성처럼 고른 결과를 장면으로) — flags['moment_fx'] 를 다음 화면이 한 번 보여 주고 지운다.
# 장면(이펙트만 — 상황 그림은 빼 달라는 사용자 의견): 공·메달이 박히는 순간 이펙트 → 한 줄(head) → 점수판 → 우승·메달. path 는 홈런 흔들림에만.
KOREA_COLORS = ('#CD2E3A', '#0047A0')
BALL_PATH = {'HR': 'hr', '3B': 'hit', '2B': 'hit', '1B': 'hit', 'SO': 'so', 'BB': 'ball', 'HBP': 'ball'}


def moment_head(m: dict, r: dict) -> str:
    """전광판에 뜨는 짧은 한 줄 — '끝내기 홈런', '헛스윙 삼진', '밀어내기 볼넷'."""
    o, ok, need = r['outcome'], r['ok'], m['sit']['need']
    if o == 'SO':
        return '헛스윙 삼진'
    if m['side'] == 'bat':
        lead = '끝내기' if need == 'hit' else '앞서가는'
        if o in ('HR', '3B', '2B'):
            return f'{lead} {OUTCOME_KO[o]}'
        if o == '1B':
            return '끝내기 안타' if need == 'hit' else '앞서가는 적시타'
        if o == 'OUT':
            return '희생플라이' if ok else '잘 맞은 타구, 아웃' if need == 'hit' else '내야 땅볼'
        return OUTCOME_KO.get(o, o)
    if o == 'OUT':
        return '뜬공, 경기 끝' if need == 'out' else '병살타' if ok else '희생플라이'
    if need == 'out':
        return {'HR': '만루 홈런', '1B': '끝내기 안타', '2B': '싹쓸이 2루타', '3B': '싹쓸이 3루타', 'BB': '밀어내기 볼넷',
                'HBP': '밀어내기 사구'}.get(o, OUTCOME_KO.get(o, o))
    return {'HR': '3점 홈런', '1B': '적시타', '2B': '적시 2루타', '3B': '적시 3루타'}.get(o, OUTCOME_KO.get(o, o))


def moment_score(m: dict, r: dict) -> tuple:
    """(이 타석 전, 뒤) 점수 [우리, 상대] — 장면의 점수판이 넘어간다."""
    us, them = (int(x) for x in m['sit']['score'].split(':'))
    o, ok, need = r['outcome'], r['ok'], m['sit']['need']
    a, b = us, them
    if need == 'hit' and ok:                                   # 9회말 2·3루 — 홈런이면 셋, 아니면 주자 둘
        a += 3 if o == 'HR' else 2
    elif need == 'run' and ok:                                 # 8회 3루 — 투런이면 둘, 아니면 하나
        a += 2 if o == 'HR' else 1
    elif need == 'out' and (o in ('BB', 'HBP') or not ok):     # 9회말 만루 — 밀어내기는 동점, 맞으면 주자만큼
        b += 1 if o in ('BB', 'HBP') else {'HR': 4, '1B': 2}.get(o, 3)
    elif need == 'hold' and not ok:                            # 7회 1·3루
        b += {'HR': 3, '2B': 2, '3B': 2}.get(o, 1)
    return [us, them], [a, b]


def moment_fx(c, m: dict, r: dict, d: dict, more: bool) -> dict:
    o, need = r['outcome'], m['sit']['need']
    path = BALL_PATH.get(o) or ('fly' if (need in ('hit', 'out') or (need == 'run') == r['ok']) else 'ground')
    if m['kind'] == 'intl':
        colors = KOREA_COLORS
    else:
        from .rookie_card import _palette
        pal = _palette(c.league, c.club)
        colors = (pal['primary'], pal['secondary'])
    before, after = moment_score(m, r)
    sit = m['sit']
    return {'stage': m['stage'], 'when': m['when'], 'side': m['side'], 'path': path,
            'sit': f"{sit['inning']} {sit['outs']}사 {_bases_text(sit['bases'])}", 'before': before, 'after': after,
            'head': moment_head(m, r), 'line': r['line'], 'play': r['text'],
            'after_text': '' if r.get('final') else AFTER[(m['side'], r['ok'], d['won'])],
            'ok': r['ok'], 'won': d['won'], 'result': d['result'],
            'medal': 'gold' if d['result'].endswith('금메달') else 'silver' if d['result'].endswith('은메달') else '',
            'colors': list(colors), 'more': more}


def moments_for(c, code: str, rank: int, team_n: int, state: dict, rng) -> list:
    """이번 시즌 결정적 순간들 — 국가대표 결승, 최종 시리즈, 아마추어 대회 결승(시즌에 하나)."""
    out = []
    for res in state['intl']:
        if res.get('final'):
            out.append(make_moment(c, 'intl', f"{res['name']} 결승", INTL[res['key']]['month'], rng, key=res['key'],
                                   opp_name=intl_rival(res['key'], rng)))
    standings = Universe.current_table(c)
    if code == 'kbo1' and standings and standings['year'] == c.year:
        opponent, bracket = Universe.kbo_final(c, standings)
        state['news'].extend(bracket)
        if opponent:
            m = make_moment(c, 'series', '한국시리즈 최종 승부', '10월', rng,
                            opp_name=f'{opponent["name"]} {rival_name(code, rng)}')
            m['opponent_club'] = opponent['club']
            out.append(m)
        return out
    odds = POSTSEASON.get(code, ())
    if team_n and rank <= len(odds):
        reach = 1.0 if (code == 'kbo1' and rank == 1) else min(1.0, 2 * odds[rank - 1])   # KBO 1위는 한국시리즈 직행
        if rng.random() < reach:
            out.append(make_moment(c, 'series', f'{SERIES_NAME.get(code, "최종 시리즈")} 7차전', '10월', rng))
        else:
            rnd = POST_ROUND.get(code, '포스트시즌')
            team = W.club_short(code, c.club)
            state['news'].append(f'정규시즌 {rank}위로 가을야구에 나갔지만 {rnd}에서 탈락했어요')
            state['press'].append(press('', f"{team}, {rnd}서 탈락…{c.name}의 가을은 여기까지"))
    return out


def _hero(nm: str, d: dict) -> str:
    """결정적 순간 기사 뒷부분 — 내 승부와 팀 결과의 네 갈래."""
    if d['ok'] and d['won']:
        return f"‘해결사’ {nm}, 마지막 승부서 웃었다"
    if d['won']:
        return f"{nm} 아쉬움 털어 준 동료들"
    if d['ok']:
        return f"{nm} 분투에도 끝내 고개 숙여"
    return f"{nm}, 마지막 승부서 고개 숙여"


def moment_result_text(d: dict) -> str:
    """결과 한 줄 — 어느 대회인지 밝힌다(2026-10-19 사용자 요청: 고교 대회가 여럿이라 '우승!'만으로는 모른다)."""
    if d['kind'] == 'intl':
        t = INTL[d['key']]
        return f"{t['name']} {t['tiers'][0][1] if d['won'] else t['tiers'][1][1]}"
    name = d['key'] if d['kind'] == 'amateur' else d['stage'].replace(' 7차전', '').replace(' 최종 승부', '')
    return f'{name} 우승!' if d['won'] else f'{name} 준우승'


def resolve_moments(c, season, done: list, rng) -> list:
    """결정적 순간이 끝난 뒤 — 우승·메달·병역 특례·기사를 시즌 기록에 넣는다."""
    flags, nm = c.flags, c.name
    team = W.club_short(season.league, season.club)
    for d in done:
        won = d['won']
        if d['kind'] == 'series':
            stage = SERIES_NAME.get(season.league, '최종 시리즈')
            if won:
                label = f'{stage} 우승'
                season.awards.append({'kind': 'ring', 'label': label})
                season.champion = True
            season.press.insert(0, press('[우승]' if won else '', f"{team}, {stage} {'우승!' if won else '준우승'}…{_hero(nm, d)}", d['line']))
        elif d['kind'] == 'amateur':
            if won:
                season.awards.append({'kind': 'ring', 'label': f"{d['key']} 우승"})
                season.champion = True
            season.press.insert(0, press(f"[{d['key']}]", f"{team} {'우승!' if won else '준우승'}…{_hero(nm, d)}", d['line']))
        elif d['kind'] == 'intl':
            t = INTL[d['key']]
            result = t['tiers'][0][1] if won else t['tiers'][1][1]
            season.awards.append({'kind': 'national', 'label': f"{t['name']} {result}"})
            reward = national_reward(c, d['key'], 'gold' if won and t.get('exempt') else 'champ' if won else 'silver')
            if reward:
                season.news.append(reward)
            flags = c.flags
            season.press.insert(0, press(f"[{t['name']}]", f"대한민국 {result}{'!' if won else ''}…{_hero(nm, d)}", d['line']))
            if won and t.get('exempt') and not flags.get('served') and not flags.get('exempt') and not flags.get('army'):
                flags['exempt'] = True
                season.press.insert(1, press('[오피셜]', f"{nm}, {t['name']} 금메달로 병역 특례…‘꿈같은 하루’"))
                season.news.append(f"{t['name']} 금메달로 병역 특례를 받았어요")
    return done
