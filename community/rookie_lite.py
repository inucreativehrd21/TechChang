"""야구선수 키우기 라이트 — 한 판 30분, 고1부터 은퇴까지 분기점을 골라 가며 빠르게 진행하는 커리어 시뮬레이터
(2026-10-18 사용자 요청: '진짜 kickru 같은 가벼운 버전, FM 느낌').

정식 '야구선수 키우기'(사이트 활동 TP 로 매일 키우는 판)와 선수·기록이 따로다. 세계(리그·구단·학교)와 경기 모형·지표는
정식 판의 것을 그대로 쓴다(rookie_world · rookie_sim · rookie_league).

한 시즌 = 세 화면:
  비시즌(plan)   — 훈련 프로그램 두 개 + 강도(가볍게·보통·강하게) + 가끔 이벤트 하나를 고른다
  시즌(review)   — 월별 전광판이 넘어가고, 성적·시상·팀 순위·성장·승격이 나온다
  결정(decision) — 드래프트·병역·포스팅·FA·KBO 복귀·은퇴 같은 갈림길(때가 되면)
고1(16세)에서 시작해 34세부터 은퇴를 고를 수 있고 42세면 끝난다 — 보통 22~26시즌, 시즌당 1분 남짓.

성장(grow): 해마다 '능력별 잠재력 × 나이 곡선(CURVE)'의 차이만큼 자라고, 고른 훈련·강도·출전 시간이 그 위에 더한다.
잠재력(숨김, 스카우트 별점으로 짐작)이 끝이다. 강하게 훈련하면 더 크지만 다칠 확률이 오른다. 서른 넘으면 몸
(구속·체력·파워·주루)이 먼저 빠지고 기술(컨택·선구안·제구·변화구·멘탈·수비)은 천천히 빠진다.
경기 모형은 리그 수준과의 차이에 민감하다(+6 ≈ 6 WAR, +12 ≈ 10 WAR) — 그래서 잠재력이 '어디까지 갈 수 있나'를 정한다:
평균 잠재력(65)은 KBO 주전, 상위 25%는 KBO 올스타, 상위 10%는 KBO MVP·메이저리그 주전감, 상위 3%는 메이저리그 스타.
시상은 가상 경쟁자 기준(AWARD_BARS — 해마다 조금씩 흔들리는 문턱)으로 정한다(한 사람만 뛰는 판이라).
킥루(축구)·Football Manager 의 '고르고 넘기는' 진행 감각만 참고했다 — 코드·화면·수치는 가져오지 않았다.
"""
from __future__ import annotations

import math
import random

from django.db import transaction
from django.utils import timezone

from . import rookie as R
from . import rookie_league as L
from . import rookie_sim as M
from . import rookie_world as W

START_AGE, RETIRE_FROM, RETIRE_AT = 16, 34, 42
POT_MEAN, POT_SD, POT_RANGE = 65, 7, (50, 92)
CURVE = {16: .55, 17: .61, 18: .67, 19: .72, 20: .77, 21: .81, 22: .85, 23: .88, 24: .91, 25: .93, 26: .95,
         27: .96, 28: .96, 29: .95, 30: .94, 31: .92, 32: .89, 33: .86, 34: .82, 35: .78, 36: .73, 37: .68,
         38: .63, 39: .58, 40: .53, 41: .48, 42: .43, 43: .40}
PHYS = ('velocity', 'stamina', 'power', 'speed')
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
PIT_POSITIONS = [('SP', '선발'), ('RP', '불펜')]
PROGRAMS = {
    'batter': [('contact', '타격 기술', '컨택 +', {'contact': 3.0}),
               ('power', '웨이트', '파워 +, 주루 조금 −', {'power': 3.0, 'speed': -0.5}),
               ('eye', '영상 분석', '선구안 +', {'eye': 3.0}),
               ('speed', '스프린트·주루', '주루 +', {'speed': 3.0}),
               ('defense', '수비 펑고', '수비 +', {'defense': 3.0}),
               ('balance', '밸런스', '모든 능력 조금씩', {k: 0.9 for k in M.BAT})],
    'pitcher': [('velocity', '구속 프로그램', '구속 +, 부상 위험 +', {'velocity': 3.0}),
                ('control', '불펜 제구', '제구 +', {'control': 3.0}),
                ('breaking', '변화구 개발', '변화구 +', {'breaking': 3.0}),
                ('stamina', '러닝·체력', '체력 +', {'stamina': 3.0}),
                ('mental', '멘탈 코칭', '멘탈 +', {'mental': 3.0}),
                ('balance', '밸런스', '모든 능력 조금씩', {k: 0.9 for k in M.PIT})],
}
INTENSITY = {'light': ('가볍게', 0.6, 0.03), 'normal': ('보통', 1.0, 0.07), 'hard': ('강하게', 1.5, 0.14)}
TRAITS = {
    'early': ('조기 개화', '또래보다 1년 빨리 자라고, 2년 빨리 늙어요.'),
    'late': ('대기만성', '1년 늦게 자라고, 2년 늦게 늙어요.'),
    'iron': ('강철 체력', '잘 다치지 않고 늦게 늙어요.'),
    'glass': ('유리몸', '자주 다쳐요.'),
    'grinder': ('연습벌레', '훈련 효과가 25% 커요.'),
    'learner': ('경험파', '경기에 나갈수록 크게 자라요.'),
    'clutch': ('큰 경기 체질', '승부처에 강해요(선구안·멘탈 +5).'),
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
def stat_pot(c, k: str) -> float:
    st = STYLES[c.role][c.style]
    p = float(c.potential)
    if k in st['plus']:
        p += PLUS + (6.0 if has(c, 'natural') else 0.0)
    elif k == st['minus']:
        p -= MINUS
    return _clamp(p, 40.0, 99.0)


def frac(c, k: str, age: int) -> float:
    a = age
    if has(c, 'early'):
        a = a + 1 if a <= 24 else a + 2
    elif has(c, 'late'):
        a = a - 1 if a <= 26 else a - 2
    a = int(_clamp(a, min(CURVE), max(CURVE)))
    f = CURVE[a]
    if a > 30:
        keep = 0.6 if k not in PHYS else (0.7 if has(c, 'iron') else 1.0)    # 기술은 천천히, 몸은 빨리
        f = CURVE[30] - (CURVE[30] - f) * keep
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


def create(user, *, name, role, position, style, region, team, number=0, rng=None, guest=''):
    """고향 고교 1학년으로 시작. user 가 없으면 손님 판(guest = 세션 표식) — 로그인하면 계정으로 옮긴다(claim_guest)."""
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
    name = (name or '').strip()[:12] or (user.username[:12] if user else '새내기')
    with transaction.atomic():
        if user is not None:
            User.objects.select_for_update().filter(pk=user.pk).first()
            mine = LiteCareer.objects.filter(user=user)
        else:
            mine = LiteCareer.objects.filter(user__isnull=True, guest=guest)
        if mine.filter(retired_at__isnull=True).exists():
            raise LiteError('진행 중인 커리어가 있어요. 은퇴한 뒤에 새로 시작할 수 있어요.')
        hs = [s for r, s in W.schools('hs') if r == region] or [s for _r, s in W.schools('hs')]
        c = LiteCareer(user=user, guest='' if user else guest, name=name, number=max(0, min(99, int(number or 0))), role=role, position=position,
                       style=style, region=region, team=team, age=START_AGE, league='hs', club=rng.choice(hs), grade=1,
                       potential=int(_clamp(round(rng.gauss(POT_MEAN, POT_SD)), *POT_RANGE)), traits=roll_traits(rng))
        c.stats = {k: round(max(25.0, stat_pot(c, k) * frac(c, k, START_AGE) + rng.gauss(0, 2)), 1)
                   for k in R.stat_keys(role)}
        c.ovr = c.best_ovr = R.overall(role, c.stats)
        c.flags = {'kbo_years': 0, 'pro_years': 0, 'leagues': [], 'served': False, 'exempt': False}
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
    if pro and c.ovr >= W.level('kbo1') + 2 and c.age <= 34:
        pool.append(('national', 3 if c.league in ('kbo1', 'npb1', 'mlb') else 1))
    if last and last.games and _bad(last):
        pool.append(('slump', 4))
    if pro and last and last.duty.startswith(('백업', '패전')) and c.age >= 21:
        pool.append(('trade', 3))
    if pro and c.ovr >= W.level(c.league) + 4:
        pool.append(('media', 2))
    return pool


def _bad(s) -> bool:
    t = s.totals or {}
    if t.get('outs'):
        return L.pitching(t)['era'] >= 5.5
    return bool(t.get('pa')) and L.batting(t)['ops'] < .600


# 말하는 사람 — 테크창 연구실 사람들이 구단 프런트·코칭스태프로 나온다(그림은 media/lab/chars/<키>_idle.png)
STAFF = {'lead': ('은혜', '감독'), 'coding': ('윤성', '타격·투수 코치'), 'hrd': ('한빈', '컨디셔닝 코치'),
         'data': ('수정', '스카우트'), 'editor': ('승현', '야구 기자'), 'charter': ('재원', '에이전트'),
         'checker': ('하경', '트레이너'), 'critic': ('예원', '해설위원')}
DECISION_WHO = {'draft': 'data', 'military': 'lead', 'posting': 'charter', 'fa': 'charter', 'return': 'charter',
                'retire': 'lead', 'released': 'lead', 'end': 'lead'}
EVENTS = {
    'form': {'who': 'coding', 'title': lambda c: '투구폼 교정 제안' if c.role == 'pitcher' else '타격폼 교정 제안',
             'text': lambda c: '폼을 한번 뜯어고쳐 볼까요? 잘 맞으면 한 단계 올라서지만, 몸에 안 붙으면 한 시즌을 헤맬 수도 있어요.'
             if c.role == 'batter' else '팔 각도를 조금 바꿔 볼까요? 잘 맞으면 공이 달라지지만, 안 맞으면 한 시즌을 헤맬 수도 있어요.',
             'choices': [('accept', '교정해 볼게요', '성공하면(55%) 핵심 능력 +4, 실패하면 −2'), ('decline', '지금 폼을 지킬게요', '변화 없음')]},
    'mentor': {'who': 'hrd', 'title': lambda c: '베테랑과 비시즌 훈련',
               'text': lambda c: '팀 베테랑이 이번 비시즌 개인 훈련에 같이 가자고 해요. 경기 운영을 많이 배울 거예요.',
               'choices': [('accept', '따라갈게요', '멘탈·선구안(제구) +2'), ('decline', '혼자 준비할게요', '체력 +1')]},
    'camp': {'who': 'checker', 'title': lambda c: '해외 개인 훈련 캠프',
             'text': lambda c: '미국 트레이닝 센터에서 초청이 왔어요. 최신 장비로 몸을 만들 수 있지만, 쉴 틈은 없어요.',
             'choices': [('accept', '다녀올게요', '강점 능력 +2, 이번 시즌 부상 위험 +3%'), ('decline', '국내에서 쉴게요', '이번 시즌 부상 위험 −3%')]},
    'position': {'who': 'lead', 'title': lambda c: '포지션 변경 제안',
                 'text': lambda c: f'{L.POS_LABEL.get(c.position, c.position)} 말고 다른 자리를 맡아 보면 어때요? 수비 부담이 줄면 타격에 집중할 수 있어요.',
                 'choices': [('accept', '해 볼게요', '수비 부담이 적은 자리(1루수·지명타자 쪽)로, 컨택·파워 +1'), ('decline', '지금 자리를 지킬게요', '수비 +1')]},
    'pitch': {'who': 'coding', 'title': lambda c: '새 구종 연마',
              'text': lambda c: '구종을 하나 더 익혀 보면 어때요? 손에 붙으면 타자들이 훨씬 까다로워할 거예요.',
              'choices': [('accept', '새 구종을 익힐게요', '성공하면(60%) 변화구 +4, 실패하면 제구 −1'), ('decline', '가진 공을 다듬을게요', '제구 +1')]},
    'national': {'who': 'lead', 'title': lambda c: '국가대표 차출',
                 'text': lambda c: '국가대표팀 명단에 이름이 올랐어요. 큰 무대 경험이 되지만 비시즌에 쉴 시간은 줄어요.',
                 'choices': [('accept', '태극마크를 달게요', '멘탈 +2, 우승하면 병역 특례(KBO), 부상 위험 +3%'), ('decline', '소속팀에 집중할게요', '변화 없음')]},
    'slump': {'who': 'hrd', 'title': lambda c: '슬럼프',
              'text': lambda c: '지난 시즌은 생각만큼 안 풀렸죠. 이번 비시즌을 어떻게 보낼까요?',
              'choices': [('accept', '특타·특훈으로 이겨낼게요', '핵심 능력 +2, 부상 위험 +3%'), ('decline', '푹 쉬면서 머리를 비울게요', '멘탈 +1, 부상 위험 −3%')]},
    'trade': {'who': 'charter', 'title': lambda c: '트레이드 요청',
              'text': lambda c: '지난 시즌엔 기회가 거의 없었어요. 구단에 트레이드를 요청해 볼까요?',
              'choices': [('accept', '트레이드를 요청할게요', '같은 리그 다른 구단으로(출전 기회를 찾아)'), ('decline', '남아서 경쟁할게요', '멘탈 +1')]},
    'media': {'who': 'charter', 'title': lambda c: '예능 출연 제안',
              'text': lambda c: '인기 예능에서 출연 제안이 왔어요. 팬은 늘겠지만 훈련 시간은 줄어요.',
              'choices': [('accept', '출연할게요', '연봉 +10%, 훈련 효과 −20%'), ('decline', '야구에 집중할게요', '훈련 효과 +10%')]},
}


def plan_step(c, rng) -> dict:
    """비시즌 화면 — 이벤트는 70% 확률로 하나."""
    ev = None
    pool = _event_pool(c)
    if pool and rng.random() < 0.7:
        codes, weights = zip(*pool)
        ev = rng.choices(codes, weights)[0]
    return {'kind': 'plan', 'event': ev}


def event_view(c, code: str | None) -> dict | None:
    if not code:
        return None
    e = EVENTS[code]
    name, role = STAFF[e['who']]
    return {'code': code, 'title': e['title'](c), 'text': e['text'](c), 'who': e['who'], 'who_name': name, 'who_role': role,
            'choices': [{'key': k, 'label': lab, 'hint': h} for k, lab, h in e['choices']]}


def _core(c) -> str:
    """'핵심 능력' — 스타일의 첫 강점."""
    return STYLES[c.role][c.style]['plus'][0]


def apply_event(c, code: str, choice: str, rng, mods: dict) -> str:
    """이벤트 선택의 효과 — 능력치·플래그를 고치고 소식 문장을 돌려준다. mods: 이번 시즌 부상·훈련·연봉 보정."""
    s, core = c.stats, _core(c)

    def bump(k, v):
        if k in s:
            s[k] = round(_clamp(float(s[k]) + v, 25.0, stat_pot(c, k) + 2), 1)
    if code == 'form':
        if choice == 'accept':
            if rng.random() < 0.55:
                bump(core, 4)
                return '폼 교정에 성공했어요 — 공이 달라졌어요'
            bump(core, -2)
            return '폼 교정이 몸에 붙지 않아 애를 먹었어요'
        return '익숙한 폼을 지켰어요'
    if code == 'mentor':
        if choice == 'accept':
            bump('mental' if c.role == 'pitcher' else 'eye', 2)
            bump('control' if c.role == 'pitcher' else 'contact', 1)
            return '베테랑에게 경기 운영을 배웠어요'
        bump('stamina' if c.role == 'pitcher' else 'speed', 1)
        return '혼자 비시즌을 보냈어요'
    if code == 'camp':
        if choice == 'accept':
            for k in STYLES[c.role][c.style]['plus']:
                bump(k, 2)
            mods['injury'] += 0.03
            return '해외 캠프에서 몸을 새로 만들었어요'
        mods['injury'] -= 0.03
        return '국내에서 푹 쉬었어요'
    if code == 'position':
        if choice == 'accept':
            c.position = rng.choice(['1B', 'DH']) if c.position in ('C', '3B', '1B') else rng.choice(['OF', '1B', 'DH'])
            bump('contact', 1)
            bump('power', 1)
            return f'{L.POS_LABEL[c.position]}로 자리를 옮겼어요'
        bump('defense', 1)
        return '지금 자리를 지키기로 했어요'
    if code == 'pitch':
        if choice == 'accept':
            if rng.random() < 0.6:
                bump('breaking', 4)
                return '새 구종을 손에 넣었어요'
            bump('control', -1)
            return '새 구종이 손에 익지 않았어요'
        bump('control', 1)
        return '가진 공을 다듬었어요'
    if code == 'national':
        if choice == 'accept':
            bump('mental' if c.role == 'pitcher' else 'eye', 2)
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
            bump(core, 2)
            mods['injury'] += 0.03
            return '특타·특훈으로 비시즌을 보냈어요'
        bump('mental', 1)
        mods['injury'] -= 0.03
        return '푹 쉬면서 머리를 비웠어요'
    if code == 'trade':
        if choice == 'accept' and W.is_pro(c.league):
            sysname = W.system_of(c.league)
            if sysname in W.SYSTEM_TEAMS:
                c.club = rng.choice([t for t, _n, _col in W.SYSTEM_TEAMS[sysname] if t != c.club])
                return f'{W.club_label(c.league, c.club)}로 트레이드됐어요'
        bump('mental', 1)
        return '남아서 경쟁하기로 했어요'
    if code == 'media':
        if choice == 'accept':
            mods['train'] *= 0.8
            mods['salary'] *= 1.1
            return '예능에 나가서 팬이 늘었어요'
        mods['train'] *= 1.1
        return '야구에만 집중했어요'
    return ''


# ───────────────────────────── 성장
def grow(c, programs, intensity: str, pt: float, war: float, rng, train_mult: float = 1.0) -> dict:
    """한 해 성장 — 나이 곡선 + 훈련 + 출전 경험 + 활약. {능력: 변화}"""
    _lab, mult, _inj = INTENSITY[intensity]
    plus = {}
    for code in programs:
        for k, v in dict((p[0], p[3]) for p in PROGRAMS[c.role])[code].items():
            plus[k] = plus.get(k, 0.0) + v
    age_train = 1.2 if c.age <= 22 else 1.0 if c.age <= 28 else 0.8 if c.age <= 32 else 0.6
    deltas = {}
    for k in list(c.stats):
        s, pot = float(c.stats[k]), stat_pot(c, k)
        room = _clamp((pot - s) / 5.0, 0.0, 1.0)
        nat = pot * (frac(c, k, c.age + 1) - frac(c, k, c.age))
        tr = plus.get(k, 0.0) * mult * age_train * train_mult * (1.25 if has(c, 'grinder') else 1.0)
        exp = (0.8 if c.age <= 27 else 0.3) * pt * (2.0 if has(c, 'learner') else 1.0)
        perf = 0.8 if war >= 4 and k in ('eye', 'mental') else 0.0
        up = (max(0.0, nat) + max(0.0, tr) + exp + perf) * room
        down = min(0.0, nat) + min(0.0, tr)
        new = _clamp(s + up + down + rng.gauss(0, 0.8), 25.0, pot)
        deltas[k] = round(new - s, 1)
        c.stats[k] = round(new, 1)
    c.ovr = R.overall(c.role, c.stats)
    c.best_ovr = max(c.best_ovr, c.ovr)
    return deltas


# ───────────────────────────── 시즌
def duty_for(c, lvl: float) -> tuple[str, int, str]:
    """시즌 보직 — 타자는 백업·하위타선·상위/중심타선, 투수는 선발 또는 불펜 사다리(rookie_sim 과 같은 문턱)."""
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
    if c.position == 'SP' and st >= lvl - 3 and float(s['stamina']) >= lvl - 4:
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
    if has(c, 'clutch'):
        if c.role == 'batter':
            s['clutch'] = (float(s['contact']) + float(s['eye'])) / 2 + 5
        else:
            s['mental'] = float(s['mental']) + 5
    return s


def _chunks(code: str) -> tuple:
    return CHUNKS.get(code if code in ('hs', 'univ') else 'pro')


def play(c, programs, intensity, event_choice, rng) -> 'LiteSeason':
    """비시즌 결정 → 한 시즌 시뮬레이션 → 성장·시상·승격. 시즌 기록을 만들고 c 를 고친다(저장은 부른 쪽)."""
    from .models import LiteSeason
    pend = c.pending or {}
    mods = {'injury': 0.0, 'train': 1.0, 'salary': 1.0, 'national': ''}
    news = []
    if pend.get('event'):
        news.append(apply_event(c, pend['event'], event_choice, rng, mods))
    c.ovr = R.overall(c.role, c.stats)
    ovr_start = c.ovr
    code, lvl, G = c.league, W.level(c.league), GAMES.get(c.league, 120)
    pro = W.is_pro(code)
    role, slot, duty = duty_for(c, lvl)
    s = _game_stats(c)
    # 부상 — 강도·나이·특성·이번 비시즌 선택
    p_inj = INTENSITY[intensity][2] + max(0, c.age - 29) * 0.01 + mods['injury'] \
        + (0.03 if 'velocity' in programs else 0.0)
    p_inj *= 0.5 if has(c, 'iron') else 1.8 if has(c, 'glass') else 1.0
    out = range(0)
    if rng.random() < max(0.0, p_inj):
        size = rng.choices((0.12, 0.3, 0.6), (0.55, 0.3, 0.15))[0]
        start = rng.randrange(G)
        out = range(start, min(G, start + max(1, int(G * size))))
        news.append(f"{_chunks(code)[min(5, start * 6 // G)]}에 다쳐서 {len(out)}경기를 쉬었어요")
        if size >= 0.6:
            for k in PHYS:
                if k in c.stats:
                    c.stats[k] = round(max(25.0, float(c.stats[k]) - rng.uniform(1, 3)), 1)
    lines, per = [], [[] for _ in range(6)]
    offset = rng.randrange(5)
    for i in range(G):
        if i in out:
            continue
        r = None
        if c.role == 'batter':
            r = M.batter_game(s, c.position, lvl, rng, role=role, slot=slot)
        elif role == 'sp':
            if i % 5 == offset:
                r = M.starter_game(s, lvl, rng)
        elif rng.random() < M.RELIEF[role][0]:
            r = M.relief_game(s, lvl, rng, role)
        if r:
            lines.append(r['line'])
            per[min(5, i * 6 // G)].append(r['line'])
    totals = {}
    for ln in lines:
        totals = L.add(totals, ln)
    pos = 'SP' if c.role == 'pitcher' else c.position
    war = L.war(c.role, pos, totals) if totals else 0.0
    # 팀 성적(가상 리그)
    strength = rng.gauss(0, 0.045) + (0.03 if W.powerhouse(code, c.club) else 0.0)
    w = int(_clamp(round(G * (0.5 + strength) + rng.gauss(0, math.sqrt(G * 0.25)) + war * 0.9), 0, G))
    team_n = TEAMS_N.get(code, 0)
    rank = 0
    champion = False
    if team_n:
        rank = 1 + sum(1 for _ in range(team_n - 1) if rng.gauss(0.5, 0.06) * G > w)
        odds = POSTSEASON.get(code, ())
        champion = rank <= len(odds) and rng.random() < odds[rank - 1]
    # 월별 전광판
    months, run = [], {}
    for j, chunk in enumerate(per):
        t = {}
        for ln in chunk:
            t = L.add(t, ln)
        run = L.add(run, t)
        months.append({'label': _chunks(code)[j], 'line': _short(c.role, t), 'run': _short(c.role, run),
                       'hot': _hot(c.role, t), 'w': round(w * (j + 1) / 6), 'l': round((G - w) * (j + 1) / 6)})
    season = LiteSeason(career=c, year=c.year, age=c.age, league=code, club=c.club, duty=duty, games=G,
                        totals=totals, war=war, team_w=w, team_l=G - w, team_rank=rank, team_of=team_n,
                        champion=champion, months=months, ovr_start=ovr_start)
    # 시상
    first = code not in (c.flags.get('leagues') or [])
    season.awards = awards_for(c, code, totals, war, G, first, per, rng)
    if mods['national']:
        season.awards.append({'kind': 'national', 'label': f"국가대표 {mods['national']}"})
    if champion:
        season.awards.append({'kind': 'ring', 'label': '한국시리즈 우승' if code == 'kbo1' else '월드시리즈 우승'
                              if code == 'mlb' else '일본시리즈 우승' if code == 'npb1' else '대만시리즈 우승'})
    if code in TOURNAMENTS:
        z = (c.ovr - lvl) / 5.0
        for t in TOURNAMENTS[code]:
            if rng.random() < 0.03 + 0.04 * max(0.0, z) + (0.03 if W.powerhouse(code, c.club) else 0.0):
                season.awards.append({'kind': 'ring', 'label': f'{t} 우승'})
                season.champion = True
    # 연봉
    season.salary = salary_for(c, war, mods['salary'])
    # 성장
    pt = 0.0
    if totals:
        pt = min(1.0, (totals.get('pa', 0) / (G * 4.0)) if c.role == 'batter'
                 else (totals.get('outs', 0) / 3) / (G * (1.2 if role == 'sp' else 0.45)))
    season.deltas = grow(c, programs, intensity, pt, war, rng, mods['train'])
    season.ovr_end = c.ovr
    # 승격·강등(프로)
    if pro:
        nxt = W.next_league(code)
        below = W.demote_below(code)
        star = war * (1.4 if c.role == 'pitcher' else 1.0) >= 4.0 * G / 144      # 리그를 압도하면 조금 모자라도 올린다
        if nxt and _ok(c.role, totals, G) and (c.ovr >= W.level(nxt) - 1 or (star and c.ovr >= W.level(nxt) - 4)):
            c.league = nxt
            news.append(f'{W.league(nxt)["name"]}로 승격했어요!')
        elif below is not None and c.ovr < below:
            c.league = W.prev_league(code)
            news.append(f'{W.league(c.league)["name"]}(으)로 내려갔어요')
    news.extend(_headlines(c, season))
    season.news = [n for n in news if n]
    return season


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
        for key, unit in (('w', '승'), ('sv', '세'), ('hld', '홀'), ('so', 'K')):
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


def awards_for(c, code, t, war, G, first, per, rng) -> list:
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
        half = {}
        for chunk in per[:3]:
            for ln in chunk:
                half = L.add(half, ln)
        if half and L.war(c.role, 'SP' if pit else c.position, half) >= bar('allstar'):
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


def salary_for(c, war: float, mult: float = 1.0) -> int:
    """만원. 계약(FA·해외)이 있으면 그 연봉, 없으면 리그·지난 활약 기준."""
    code = c.league
    if not W.is_pro(code):
        return 0
    deal = (c.flags or {}).get('contract')
    if deal and deal.get('years', 0) > 0:
        return int(deal['annual'] * mult)
    last = c.seasons.filter(league__in=[x for x in W.LEAGUES if W.is_pro(x)]).order_by('-year').first() if c.pk else None
    lw = max(0.0, last.war if last else 0.0)
    service = (c.flags or {}).get('pro_years', 0)
    base = {'kbo3': 3000, 'kbo2': 3500, 'kbo1': 4000 + 1500 * lw ** 1.7 + 800 * service,
            'mlb_a': 2000, 'mlb_aa': 2500, 'mlb_aaa': 4000, 'mlb': 100000 + 150000 * lw ** 1.3,
            'npb2': 3000, 'npb1': 8000 + 15000 * lw ** 1.5, 'cpbl': 6000 + 6000 * lw ** 1.3}.get(code, 3000)
    return int(base * mult)


def _headlines(c, s) -> list:
    out = []
    t = s.totals or {}
    if t.get('hr', 0) >= 40:
        out.append(f"시즌 {t['hr']}홈런!")
    if t.get('outs') and L.pitching(t)['era'] <= 2.0 and t.get('outs', 0) / 3 >= s.games:
        out.append(f"평균자책점 {L.pitching(t)['era']:.2f} — 리그를 지배했어요")
    if sum(1 for m in s.months if m['hot']) >= 3:
        out.append('이달의 선수급 활약을 세 번 넘게 했어요')
    if s.team_rank == 1:
        out.append('팀이 정규시즌 1위를 했어요!')
    return out


# ───────────────────────────── 시즌을 넘기며(나이·학년·결정)
def run_season(c, programs, intensity, choice, rng):
    """비시즌 고른 것 → 시즌 → 저장 → 결산 화면(review). 잠근 행에서 부른다."""
    season = play(c, programs, intensity, choice, rng)
    back = army_after_season(c)
    if back:
        season.news.append(back)
    season.save()
    wrap_season(c, season, rng)
    c.save()
    return season


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
        deal = flags.get('contract')
        if deal:
            deal['years'] = deal.get('years', 0) - 1
            if deal['years'] <= 0:
                flags.pop('contract', None)
    for lg in (code, c.league):
        if W.is_pro(lg) and (not W.is_pro(c.peak or 'hs') or W.level(lg) > W.level(c.peak)):
            c.peak = lg
    for a in season.awards:
        if a['kind'] == 'mvp':
            c.mvp += 1
        if a['kind'] in ('mvp', 'rookie', 'gg', 'ace', 'title', 'minor'):
            c.awards += 1
        if a['kind'] == 'ring':
            c.rings += 1
    c.earnings += season.salary
    c.salary = season.salary
    if c.age + 1 >= 19 and c.traits and not c.traits_seen:          # 고교를 마칠 때 스카우트 리포트로 드러난다
        c.traits_seen = list(c.traits)
        season.news.append('스카우트 리포트 — 숨은 특성: ' + ', '.join(TRAITS[t][0] for t in c.traits))
        season.save(update_fields=['news'])
    c.flags = flags
    c.year += 1
    c.age += 1
    if not W.is_pro(c.league):
        c.grade += 1
    c.pending = {'kind': 'review', 'year': season.year}


def next_step(c, rng) -> dict:
    """다음에 올 화면 — 결정이 있으면 결정, 없으면 비시즌."""
    flags = c.flags or {}
    code = c.league
    if c.age > RETIRE_AT:
        return {'kind': 'decision', 'what': 'end'}
    if code == 'hs' and c.grade > 3:
        return draft_offer(c, 'hs', rng)
    if code == 'univ' and c.grade > 4:
        return draft_offer(c, 'univ', rng)
    if W.is_pro(code) and c.age >= 32 and c.ovr < W.level(code) - 10 and W.prev_league(code) is None:
        return {'kind': 'decision', 'what': 'released'}
    if W.system_of(code) == 'kbo' and not flags.get('served') and not flags.get('exempt') and c.age >= 23 \
            and not flags.get('army'):
        if c.age >= 28 or rng.random() < 0.5:
            return {'kind': 'decision', 'what': 'military', 'forced': c.age >= 28}
    if W.system_of(code) in ('mlb', 'npb') and code not in W.TOP_LEAGUES and c.age >= 27 \
            and not flags.get('return_offered'):
        return {'kind': 'decision', 'what': 'return'}
    if W.system_of(code) == 'kbo' and flags.get('kbo_years', 0) >= 7 and not flags.get('posted') \
            and c.ovr >= W.level('mlb') - 3:
        return {'kind': 'decision', 'what': 'posting'}
    if W.system_of(code) == 'kbo' and flags.get('kbo_years', 0) >= 9 and not flags.get('fa') and code == 'kbo1':
        return {'kind': 'decision', 'what': 'fa', 'offers': fa_offers(c, rng)}
    if c.age >= RETIRE_FROM:
        return {'kind': 'decision', 'what': 'retire'}
    return plan_step(c, rng)


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
        + (0.3 if W.powerhouse(src, c.club) else 0.0)
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
    abroad = {}
    for sysname, at in (('mlb', 68), ('npb', 65), ('cpbl', 60)):
        if score >= at and (sysname != 'mlb' or scout >= 80):
            abroad[sysname] = rng.choice(W.SYSTEM_TEAMS[sysname])[0]
            if len(abroad) >= (2 if rng.random() < 0.25 else 1):
                break
    univs = []
    if src == 'hs':
        names = [s for _r, s in W.schools('univ')]
        strong = [s for s in names if W.powerhouse('univ', s)]
        pool = strong if score >= 55 else [s for s in names if s not in strong]
        univs = rng.sample(pool, min(3, len(pool)))
    return {'kind': 'decision', 'what': 'draft', 'from': src, 'score': score, 'offer': offer, 'abroad': abroad,
            'univs': univs}


def fa_offers(c, rng) -> list:
    """FA 제안 — 원소속(4년), 돈을 더 주는 다른 KBO 구단(4년), 실력이 되면 해외(2년). 연봉은 최근 3시즌 WAR 기준."""
    recent = [s.war for s in c.seasons.filter(league='kbo1').order_by('-year')[:3]]
    w = max(0.0, sum(recent) / len(recent)) if recent else 0.0
    base = 10000 + 12000 * w ** 1.3
    stay = {'key': 'stay', 'team': c.club, 'years': 4, 'annual': int(base)}
    rich = {'key': 'move', 'team': rng.choice([t for t, _n, _col in W.KBO_TEAMS if t != c.club]), 'years': 4,
            'annual': int(base * 1.2)}
    out = [stay, rich]
    if c.ovr >= W.level('mlb') - 2:
        out.append({'key': 'mlb', 'team': rng.choice(W.MLB_TEAMS)[0], 'years': 2, 'annual': 120000 + int(c.ovr - 65) * 30000})
    elif c.ovr >= W.level('npb1') - 1:
        out.append({'key': 'npb', 'team': rng.choice(W.NPB_TEAMS)[0], 'years': 2, 'annual': 20000 + int(c.ovr - 60) * 4000})
    return out


def decide(c, what: str, choice: str, rng, school: str = '') -> str:
    """갈림길 선택 — 고친 c 와 소식 문장. 저장은 부른 쪽."""
    pend = c.pending or {}
    if pend.get('kind') != 'decision' or pend.get('what') != what:
        raise LiteError('지금은 그 결정을 할 차례가 아니에요.')
    flags = dict(c.flags or {})
    text = ''
    if what == 'draft':
        offer, abroad = pend.get('offer'), pend.get('abroad') or {}
        college = pend.get('from') == 'univ'
        c.age = max(c.age, 23 if college else 19)
        if choice == 'sign' and offer:
            c.league = 'kbo2' if college or c.ovr >= W.level('kbo2') - 4 else 'kbo3'
            c.club = offer['team']
            text = f"{W.PRO_TEAM[offer['team']]['name']}에 입단했어요 — {offer['round']}라운드 {offer['in_round']}순위"
        elif choice == 'develop' and not offer:
            c.league, c.club = 'kbo3', c.team
            text = f"{W.PRO_TEAM[c.team]['name']}와 육성선수 계약을 맺었어요"
        elif choice in abroad:
            ladder = W.SYSTEMS[choice]
            c.league = ladder[1] if college and choice == 'mlb' else ladder[0]
            c.club = abroad[choice]
            text = f"{W.SYSTEM_NAME[choice]}로 진출했어요 — {W.PRO_TEAM[c.club]['name']}"
        elif choice == 'univ' and not college and school in (pend.get('univs') or []):
            c.age = 19
            c.league, c.club, c.grade = 'univ', school, 1
            text = f'{school}에 진학했어요 — 4년 뒤 다시 드래프트에 나가요'
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
        if W.is_pro(c.league):
            c.grade = 0
    elif what == 'military':
        if choice == 'sangmu':
            flags['army'] = {'kind': 'sangmu', 'left': 2, 'back': [c.league, c.club]}
            c.league, c.club = 'kbo2', '국군체육부대(상무)'
            text = '상무에 입대했어요 — 퓨처스리그에서 2년 동안 뛰어요'
        elif choice == 'active':
            flags['army'] = {'kind': 'active', 'left': 2, 'back': [c.league, c.club]}
            text = '현역으로 입대했어요 — 2년 동안 야구를 쉬어요'
        elif choice == 'later' and not pend.get('forced'):
            text = '입대를 미뤘어요'
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
    elif what == 'posting':
        flags['posted'] = True
        if choice == 'mlb':
            c.league = 'mlb' if c.ovr >= W.level('mlb') - 1 else 'mlb_aaa'
            c.club = rng.choice(W.MLB_TEAMS)[0]
            text = f"포스팅으로 {W.PRO_TEAM[c.club]['name']}에 입단했어요!"
        elif choice == 'npb':
            c.league, c.club = 'npb1', rng.choice(W.NPB_TEAMS)[0]
            text = f"포스팅으로 {W.PRO_TEAM[c.club]['name']}에 입단했어요!"
        elif choice == 'stay':
            text = 'KBO에 남기로 했어요'
        else:
            raise LiteError('그 길은 지금 고를 수 없어요.')
    elif what == 'fa':
        flags['fa'] = True
        deal = next((o for o in pend.get('offers') or [] if o['key'] == choice), None)
        if not deal:
            raise LiteError('계약 조건을 다시 골라 주세요.')
        if deal['key'] == 'mlb':
            c.league = 'mlb' if c.ovr >= W.level('mlb') - 1 else 'mlb_aaa'
        elif deal['key'] == 'npb':
            c.league = 'npb1'
        c.club = deal['team']
        flags['contract'] = {'years': deal['years'], 'annual': deal['annual']}
        text = f"FA 계약을 맺었어요 — {W.PRO_TEAM[c.club]['name']}, {deal['years']}년 총 {man(deal['annual'] * deal['years'])}"
    elif what == 'return':
        flags['return_offered'] = True
        if choice == 'kbo':
            c.league = 'kbo1' if c.ovr >= W.level('kbo1') - 4 else 'kbo2'
            c.club = c.team
            text = f"KBO로 돌아왔어요 — {W.PRO_TEAM[c.team]['name']}"
        elif choice == 'stay':
            text = '해외에 남아서 다시 도전해요'
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
    c.flags = flags
    c.ovr = R.overall(c.role, c.stats)
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
        for k in c.stats:
            c.stats[k] = round(max(25.0, float(c.stats[k]) - rng.uniform(1.0, 2.5)), 1)
        c.ovr = R.overall(c.role, c.stats)
        LiteSeason.objects.create(career=c, year=c.year, age=c.age, league=c.league, club=c.club, duty='현역 복무',
                                  games=0, ovr_start=c.ovr, ovr_end=c.ovr, news=['군 복무 중이에요'])
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


def retire(c, why: str = '') -> str:
    c.retired_at = timezone.now()
    c.pending = {'kind': 'retired', 'why': why}
    return {'방출': '방출됐어요 — 유니폼을 벗었어요', '나이': '마흔둘, 유니폼을 벗었어요'}.get(why, '은퇴를 선언했어요')


# ───────────────────────────── 화면·순위용
def decision_view(c) -> dict | None:
    pend = c.pending or {}
    if pend.get('kind') != 'decision':
        return None
    v = dict(pend)
    v['who'] = DECISION_WHO.get(pend.get('what'), 'lead')
    v['who_name'], v['who_role'] = STAFF[v['who']]
    if pend.get('what') == 'draft':
        v['team'] = W.PRO_TEAM.get((pend.get('offer') or {}).get('team', ''), {})
        v['abroad_list'] = [{'system': k, 'name': W.SYSTEM_NAME[k], 'team': W.PRO_TEAM[t]} for k, t in (pend.get('abroad') or {}).items()]
    if pend.get('what') == 'fa':
        v['offer_list'] = [dict(o, team_name=W.PRO_TEAM[o['team']]['name'], money=man(o['annual']),
                                total=man(o['annual'] * o['years'])) for o in pend.get('offers') or []]
    return v


def career_line(c) -> dict:
    """통산(프로) 줄과 리그별 줄."""
    from .rookie_legacy import _sum
    seasons = list(c.seasons.all())
    by = {}
    for s in seasons:
        if s.games and W.is_pro(s.league):
            by.setdefault(W.system_of(s.league), []).append(s)
    pro = [s for s in seasons if s.games and W.is_pro(s.league)]
    total = _sum(s.totals for s in pro)
    return {'pro': L.line_view(c.role, total) if pro else None,
            'systems': [{'name': W.SYSTEM_NAME[k], 'seasons': len(v), 'war': round(sum(x.war for x in v), 1),
                         'v': L.line_view(c.role, _sum(x.totals for x in v))} for k, v in by.items()]}


MVP_WEIGHT = {'mlb': 3.0, 'npb': 1.5, 'kbo': 1.2, 'cpbl': 0.6}     # 전체 순위에서 리그 수준만큼 무게


def hall(system: str = '', limit: int = 50) -> list:
    """은퇴한 라이트 커리어 순위 — 킥루 순서(MVP → 최고 OVR → 수상 → WAR). system 을 주면 그 나라 리그 시즌만,
    전체 순위의 MVP 는 리그 수준만큼 무게를 준다(MVP_WEIGHT — 대만 MVP 와 메이저리그 MVP 를 같게 세지 않게)."""
    from .game_visibility import visible
    from .models import LiteCareer
    qs = visible(LiteCareer.objects.filter(retired_at__isnull=False, user__isnull=False), 'user') \
        .prefetch_related('seasons')                                       # 손님 판은 로그인해 계정으로 옮겨야 오른다
    rows = []
    for c in qs[:2000]:
        seasons = [s for s in c.seasons.all() if s.games and (not system or W.system_of(s.league) == system)]
        if system and not seasons:
            continue
        mvp = sum(1 for s in seasons for a in s.awards if a['kind'] == 'mvp')
        weighted = round(sum(MVP_WEIGHT.get(W.system_of(s.league), 1.0) for s in seasons for a in s.awards
                             if a['kind'] == 'mvp'), 1) if not system else mvp
        awards = sum(1 for s in seasons for a in s.awards if a['kind'] in ('mvp', 'rookie', 'gg', 'ace', 'title', 'minor'))
        rings = sum(1 for s in seasons for a in s.awards if a['kind'] == 'ring')
        war = round(sum(s.war for s in seasons if W.is_pro(s.league)), 1)
        best = max([s.ovr_end for s in seasons] or [c.best_ovr])
        rows.append({'c': c, 'mvp': mvp, 'mvp_score': weighted, 'awards': awards, 'rings': rings, 'war': war,
                     'best': round(best, 1), 'seasons': len(seasons), 'peak': W.short(c.peak or 'hs')})
    rows.sort(key=lambda r: (r['mvp_score'], r['best'], r['awards'], r['war']), reverse=True)
    return rows[:limit]
