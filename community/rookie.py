"""야구선수 키우기 — 사이트 활동으로 키우는 성장 게임(2026-10-16 운영자 요청).

투수·타자 중 하나를 골라 리틀야구(초6)에서 시작 → 중학교 → 고교 → 드래프트 → 프로(KBO·미국·일본·대만).
진로·나이·잠재력·숨은 특성은 rookie_career, 리그·구단·학교는 rookie_world(2026-10-17 '선수 일생' 개편).
훈련 포인트(TP)는 사이트 활동으로만 번다: 출석 체크, 칼럼 읽기, 댓글·답변 달기(하루 한도, 같은 칼럼은 30일에 한 번).

설계 — '초반엔 빠르게, 갈수록 꾸준해야 유지'(수렴):
- 성장: 훈련 1회(10 TP)로 오르는 양이 능력치가 높을수록 준다. gain(s) = 4 × ((99 − s) / 74)^1.6
  (25→4.0, 50→2.1, 70→0.9, 80→0.46).
- 감쇠: 매일 (s − 25)의 1.5% 가 빠진다(유지비) — 높을수록 많이 빠진다. 활동이 끊기면 이틀째부터
  1.5% × 쉰 날 수(최대 12%)로 가팔라진다. 그래서 하루 활동량마다 수렴점이 생긴다
  (test_rookie.ConvergenceTests 가 지킨다): 첫날 25 → 40, 2군 문턱까지 2~8일.
  출석만 ≈ 63(2군 상위) · 출석+칼럼 1편 ≈ 68(1군) · +칼럼 2편+댓글 1개 ≈ 75(주전) · 매일 한도 ≈ 79.5(에이스).
  에이스가 일주일 쉬면 60(1군 강등 문턱), 2주 쉬면 39(육성군)까지 떨어진다.
  (수렴점은 나이 한계·잠재력이 없는 성인 기준 — 실제 선수는 rookie_career 의 한계·나이 배율이 더 붙는다.)
- 승격(프로): OVR 이 위 리그 수준 − 1 을 넘으면 콜업 테스트(청백전 3경기 중 2경기 합격, 하루 한 번).
  강등: 지금 리그 수준보다 6 아래로 떨어지면 정산 때 한 단계 내려간다. 학생은 학년이 오르며 진학한다.
- TP 보유 한도 500 — 성장 한계에 막혀 쌓아만 둔 TP 를 프로가 된 날 한꺼번에 쏟지 않게.

- 피로: 하루 훈련이 15회를 넘으면 그 뒤로는 효율이 절반 — 모아 둔 TP 를 한꺼번에 쏟기보다 매일 하게.
- 훈련 결과는 기대값 ±15% 로 흔들리고 10% 확률로 대성공(×1.5). 입단 때 고른 주특기는 성장 ×1.25.

참고한 기존 엔진(2026-10-16 조사, 코드는 가져오지 않고 구조만):
- RimWorld 숙련도: 레벨이 높을수록 하루 감쇠가 가파르고(L10 30 → L20 3,600 XP/일), 하루 학습량이
  넘치면 효율 20%(학습 포화) → 수렴점. 레벨 하락에 여유 구간(XP 0 아래 1,000) → 우리의 강등 여유 5.
  열정(passion) 배율 → 주특기.
- Banister 체력-피로 모델(스포츠과학): 훈련 효과는 시정수 τ 로 지수 감쇠, 같은 훈련량이면 정상상태로
  수렴 → 감쇠를 '바닥 위 몫의 일정 비율'로(유지비 1.5%/일 ≈ τ 67일). 단기 피로 → 하루 피로.
- ZenGM Baseball(소스 공개, 오픈소스 아님): 성장량에 무작위 배율을 곱하고, 투수·타자 OVR 을
  능력 가중 평균으로 따로 낸다 → 훈련 흔들림, ROLES 가중치.

감쇠는 '어제까지' 하루씩 정산한다(settle) — 페이지를 열 때·TP 를 벌 때 그 자리에서, 그리고 매일 밤
rookie_daily 명령이 모든 선수를 정산해 순위표가 쉬는 선수를 그대로 두지 않게 한다.
"""
from __future__ import annotations

import logging
import random
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from . import rookie_staff as S
from . import rookie_world as W

logger = logging.getLogger(__name__)

FLOOR, CAP = 25.0, 99.0           # 능력치 바닥(신인)·천장
GAIN, CURVE = 4.0, 1.6            # 훈련 1회 상승량 = GAIN × ((CAP − s)/(CAP − FLOOR))^CURVE
TRAIN_COST = 10                   # 훈련 1회 TP
BASE_DECAY, MAX_DECAY = 0.015, 0.12
WELCOME_TP = 150
SETTLE_WINDOW = 120               # 그보다 오래 쉬었으면 마지막 120일만 계산(이미 바닥 근처)
TP_MAX = 500                      # 보유 한도
REROLL_GUARD_DAYS, SHORT_CAREER_DAYS = 14, 30   # 짧게 뛰고 곧바로 다시 입단하면 타고난 자질을 이어받는다(다시 뽑기 막기)
TEST_GAMES, TEST_PASS, TEST_SPREAD = 3, 2, 7.0
FOCUS_BONUS = 1.25                # 주특기 성장 배율
FATIGUE_AT, FATIGUE_EFF = 15, 0.5  # 하루 훈련 15회를 넘으면 효율 절반
SWING = (0.85, 1.15)              # 훈련 1회 흔들림
GREAT_CHANCE, GREAT_MULT = 0.10, 1.5
EXPECTED_MULT = (SWING[0] + SWING[1]) / 2 * (1 + GREAT_CHANCE * (GREAT_MULT - 1))   # 흔들림의 기대 배율

# OVR = 다섯 능력의 평균(2026-10-18 능력치 값 균등화 — 예전 컨택·파워·구속·제구 .25, 주루·수비·체력·멘탈 .15 라
# 승격·보직·드래프트에서 뒤 능력이 당연히 밀렸다). 경기에서의 값도 rookie_sim 에서 고르게 맞췄다.
ROLES = {
    'pitcher': {'label': '투수', 'stats': [('velocity', '구속', .20), ('control', '제구', .20),
                                           ('breaking', '변화구', .20), ('stamina', '체력', .20),
                                           ('mental', '멘탈', .20)]},
    'batter': {'label': '타자', 'stats': [('contact', '컨택', .20), ('power', '파워', .20),
                                         ('eye', '선구안', .20), ('speed', '주루', .20),
                                         ('defense', '수비', .20)]},
}
# 능력치가 경기에서 하는 일 — 훈련 화면 안내
STAT_ROLE = {'contact': '삼진↓ 안타↑', 'power': '홈런·장타', 'eye': '볼넷↑ 삼진↓', 'speed': '내야안타·도루·수비 범위',
             'defense': '실점 막기(유격·포수일수록 큼)', 'velocity': '삼진↑ 장타↓', 'control': '볼넷↓',
             'breaking': '헛스윙↑ 장타↓', 'stamina': '긴 이닝·막판 구위(불펜은 연투)', 'mental': '볼넷↓·위기에 강함'}
# 희망 구단(KBO 10개 구단) — 이름은 표시용(로고 없음). 색은 카드 띠·점에만 쓴다. 해외 구단은 rookie_world.
TEAMS = W.KBO_TEAMS
TEAM = {code: W.PRO_TEAM[code] for code, _n, _c in TEAMS}
EARN = {'checkin': {'tp': 20, 'cap': 1, 'label': '출석 체크'},
        'column': {'tp': 10, 'cap': 3, 'label': '칼럼 읽기'},
        'comment': {'tp': 10, 'cap': 3, 'label': '댓글·답변'}}
DAILY_MAX = sum(e['tp'] * e['cap'] for e in EARN.values())
MIN_COMMENT = 10                  # 이보다 짧은 댓글은 TP 를 주지 않는다
REPEAT_DAYS = 30                  # 같은 칼럼을 다시 읽어 TP 를 받을 수 있는 간격


class GameError(ValueError):
    """사용자에게 그대로 보여 줄 게임 규칙 위반(TP 부족·심사 조건 등)."""


# ───────────────────────────── 수식
def gain(s: float) -> float:
    if s >= CAP:
        return 0.0
    return max(0.05, GAIN * ((CAP - s) / (CAP - FLOOR)) ** CURVE)


def decay_rate(idle_days: int) -> float:
    """그날 빠지는 비율(바닥 위 몫에 곱한다). 활동한 날·다음 날은 유지비만, 그 뒤로는 쉰 날 수만큼."""
    return BASE_DECAY if idle_days <= 1 else min(MAX_DECAY, BASE_DECAY * idle_days)


def overall(role: str, stats: dict) -> float:
    return round(sum(float(stats.get(k, FLOOR)) * w for k, _l, w in ROLES[role]['stats']), 1)


def stat_keys(role: str) -> list:
    return [k for k, _l, _w in ROLES[role]['stats']]


def mult(stat: str, focus: str, bonus: float = FOCUS_BONUS) -> float:
    return bonus if stat == focus else 1.0


def train_value(s: float, times: int, m: float = 1.0, done_today: int = 0, cap: float = CAP,
                fatigue_at: int = FATIGUE_AT) -> float:
    """기대값으로 본 훈련 결과(화면 안내·시뮬레이션용). 실제 훈련은 train() 이 흔들림을 넣는다.
    cap = 이 선수의 이 능력 한계(rookie_career.stat_cap) — 한계 6 앞부터 효과가 줄어든다."""
    from .rookie_career import room
    for i in range(times):
        eff = FATIGUE_EFF if done_today + i >= fatigue_at else 1.0
        s = min(cap, s + gain(s) * m * eff * EXPECTED_MULT * (room(s, cap) if cap < CAP else 1.0))
    return s


def upkeep_of(p) -> tuple[int, bool]:
    """이 선수가 지금 능력치를 지키는 데 하루 드는 TP — 노쇠·강철 체력·나이 배율·한계 근처 감속까지 넣어서.
    (TP, 하루 한도로도 못 지키는지)"""
    from . import rookie_career as C
    bonus, scale = C.focus_bonus(p), C.age_mult(p)
    need, lost = 0.0, False
    for k in stat_keys(p.role):
        s = float(p.stats.get(k, FLOOR))
        if s <= FLOOR:
            continue
        loss = (s - FLOOR) * C.decay_for(p, BASE_DECAY, k)
        at = s - loss                                  # 빠진 뒤의 자리에서 다시 올려야 한다
        eff = gain(at) * mult(k, p.focus, bonus) * scale * EXPECTED_MULT * C.room(at, C.stat_cap(p, k))
        if eff <= 0:
            lost = True
            continue
        need += loss / eff
    tp = int(round(need * TRAIN_COST))
    return tp, lost or tp > DAILY_MAX


def upkeep_tp(role: str, stats: dict, focus: str = '', scale: float = 1.0) -> int:
    """꾸준히 활동할 때 지금 능력치를 그대로 지키는 데 하루 드는 TP(유지비 ÷ 훈련 효율). scale = 나이 배율 등."""
    need = sum(BASE_DECAY * (float(stats[k]) - FLOOR) / (gain(float(stats[k])) * mult(k, focus) * EXPECTED_MULT * scale)
               for k in stat_keys(role) if float(stats[k]) > FLOOR)
    return int(round(need * TRAIN_COST))


def simulate(daily_tp: int, days: int, *, role: str = 'batter', start: dict | None = None,
             idle: bool = False) -> tuple[list, dict]:
    """기대값 시뮬레이션 — 매일 daily_tp 를 벌어(idle 이면 0, 활동 없음) 매 회 OVR 이 가장 많이 오르는
    능력에 훈련한다. 반환: (날마다 OVR, 마지막 능력치). 수렴점 테스트·설계 확인용."""
    w = {k: wt for k, _l, wt in ROLES[role]['stats']}
    focus = stat_keys(role)[0]
    stats = dict(start) if start else {k: FLOOR for k in stat_keys(role)}
    tp = 0 if start else WELCOME_TP
    last_active, curve = 0, []
    for d in range(1, days + 1):
        if not idle:
            tp += daily_tp
            last_active = d
        for i in range(tp // TRAIN_COST):
            k = max(stats, key=lambda k: (train_value(stats[k], 1, mult(k, focus), i) - stats[k]) * w[k])
            stats[k] = train_value(stats[k], 1, mult(k, focus), i)
        tp %= TRAIN_COST
        r = decay_rate(d - last_active)
        stats = {k: s - (s - FLOOR) * r for k, s in stats.items()}
        curve.append(overall(role, stats))
    return curve, stats


def league_kind(code: str) -> str:
    """카드·순위표 배지 색 — top(각 나라 최상위) / pro / am(아마추어)."""
    return 'top' if code in W.TOP_LEAGUES else 'pro' if W.is_pro(code) else 'am'


def title(role: str, league: str, ovr: float, age: int | None = None) -> str:
    """리그 수준과 견준 위상 — +14 에이스·간판 타자, +8 주전급. 학생은 같은 나이 동기 집단의 상위 5%·20%
    (rookie_career.CLASS) — 학생 리그 수준이 낮아 모두가 '특급'이 되지 않게."""
    d = ovr - W.level(league)
    if not W.is_pro(league):
        from .rookie_career import CLASS
        mean, sd = CLASS.get(min(max(age or 12, min(CLASS)), max(CLASS)))
        z = (ovr - mean) / sd
        return '특급 유망주' if z >= 1.65 else '유망주' if z >= 0.85 else ''
    if d >= 14:
        return '에이스' if role == 'pitcher' else '간판 타자'
    return '주전급' if d >= 8 else ''


def identity(p) -> dict:
    """카드·순위표·선수 페이지 공용 — 소속·리그·위상."""
    from .rookie_league import POS_LABEL
    return {'team': {'name': W.club_label(p.league, p.club), 'short': W.club_short(p.league, p.club),
                     'color': W.club_color(p.league, p.club)},
            'league_short': W.short(p.league), 'league_name': W.league(p.league)['name'],
            'league_kind': league_kind(p.league), 'title': title(p.role, p.league, p.ovr, p.age),
            'role_label': ROLES[p.role]['label'], 'pos_label': POS_LABEL.get(p.position, ''),
            'focus_label': dict((k, lab) for k, lab, _w in ROLES[p.role]['stats']).get(p.focus, ''),
            'want': TEAM.get(p.team, {}), 'grade_label': W.grade_label(p.league, p.grade)}


# ───────────────────────────── 상태 바꾸기(모두 행 잠금 안에서)
def _log(p, kind, text, *, tp=0, source='', ref='', day=None):
    from .models import RookieLog
    return RookieLog.objects.create(player=p, kind=kind, text=text[:200], tp=tp, source=source, ref=ref[:40],
                                    day=day or timezone.localdate())


def create(user, *, name: str, role: str, team: str, number: int = 0, focus: str = '', position: str = '',
           region: str = '', rng=None, throwing='R', batting='R'):
    """리틀야구(초6, 12세)로 입단. 잠재력·숨은 특성은 여기서 정해지고 숨겨진다."""
    from django.contrib.auth.models import User
    from .models import RookiePlayer
    from . import rookie_career as C
    from .rookie_league import PITCHER_POS, POS_LABEL
    from .rookie_versions import CURRENT
    from . import rookie_handedness as Hands
    try:
        Hands.validate(throwing, batting)
    except ValueError as ex:
        raise GameError(str(ex)) from ex
    rng = rng or random.SystemRandom()
    if role not in ROLES or team not in TEAM:
        raise GameError('포지션·희망 구단을 다시 골라 주세요.')
    if region not in W.REGIONS:
        raise GameError('리틀야구단 지역을 골라 주세요.')
    if focus not in stat_keys(role):
        focus = stat_keys(role)[0]
    position = (position if position in ('SP', 'RP') else PITCHER_POS) if role == 'pitcher' else (position if position in POS_LABEL and position not in ('SP', 'RP')
                                                      else 'OF')
    name = (name or '').strip()[:12] or user.username[:12]
    from . import rookie_names as N
    if N.blocked(name):
        raise GameError(N.MESSAGE)
    today = timezone.localdate()
    stats = {k: FLOOR for k in stat_keys(role)}
    with transaction.atomic():
        User.objects.select_for_update().filter(pk=user.pk).first()      # 같은 회원의 입단 두 번을 줄 세운다
        if RookiePlayer.objects.filter(user=user, retired_at__isnull=True).exists():
            raise GameError('이미 현역 선수가 있어요.')
        heir = inherits_from(user)
        club = W.little_club(region)
        p = RookiePlayer.objects.create(
            user=user, name=name, number=max(0, min(99, int(number or 0))), role=role, team=team, stats=stats,
            focus=focus, position=position, ovr=overall(role, stats), best_ovr=FLOOR,
            tp=WELCOME_TP, tp_earned=WELCOME_TP, last_active=today, settled_through=today - timedelta(days=1),
            lineup='mop' if role == 'pitcher' else 'bench', role_since=today,
            league='little', club=club, region=region, age=12, grade=6, grade_since=today,
            potential=heir.potential if heir else C.roll_potential(rng),
            traits=list(heir.traits or []) if heir else C.roll_traits(rng),
            traits_seen=list(heir.traits_seen or []) if heir else [],
            career={'game_version': CURRENT,
                    'path': [{'league': 'little', 'club': club, 'age': 12, 'season': 0, 'day': today.isoformat()}]})
        Hands.initialize(p, throwing, batting, rng, inherited=bool(heir))
        C.open_apply(p)
        p.save(update_fields=['pending', 'career', 'traits', 'traits_seen'])
        _log(p, 'start', f'{club} 입단 — 초등학교 6학년, 12세. 입단 보너스 +{WELCOME_TP} TP', tp=WELCOME_TP)
    return p


def inherits_from(user):
    """짧게 뛰고(30일 미만) 은퇴한 지 14일이 안 된 선수 — 새 선수가 잠재력·숨은 특성을 이어받는다.
    입단하자마자 은퇴·재입단을 되풀이해 좋은 자질만 골라 뽑지 못하게(오래 뛴 뒤의 새 출발은 새로 뽑는다)."""
    from .models import RookiePlayer
    last = RookiePlayer.objects.filter(user=user, retired_at__isnull=False).order_by('-retired_at').first()
    if last and timezone.now() - last.retired_at < timedelta(days=REROLL_GUARD_DAYS) \
            and last.retired_at - last.created_at < timedelta(days=SHORT_CAREER_DAYS):
        return last
    return None


def _decay(p, today: date) -> dict:
    start = p.settled_through + timedelta(days=1)
    if start >= today:
        return {'days': 0, 'before': p.ovr, 'after': p.ovr, 'demoted': []}
    from . import rookie_career as C
    day = max(start, today - timedelta(days=SETTLE_WINDOW))
    stats = {k: float(p.stats.get(k, FLOOR)) for k in stat_keys(p.role)}
    lost = {k: {'upkeep': 0.0, 'rest': 0.0, 'aging': 0.0} for k in stats}     # 빠진 몫을 이유별로(화면 안내)
    while day < today:
        base = decay_rate((day - p.last_active).days)
        rest_rate = C.decay_for(p, base, '')                # 쉰 날 몫까지(강철 체력이면 줄어든다), 노쇠 빼고
        for k, s in stats.items():
            r = C.decay_for(p, base, k)
            amt = (s - FLOOR) * r
            stats[k] = round(s - amt, 3)
            if r > 0:
                up = min(BASE_DECAY, rest_rate)
                lost[k]['upkeep'] += amt * up / r
                lost[k]['rest'] += amt * max(0.0, rest_rate - up) / r
                lost[k]['aging'] += amt * max(0.0, r - rest_rate) / r
        day += timedelta(days=1)
    days = (today - start).days
    before = p.ovr
    p.stats, p.ovr, p.settled_through = stats, overall(p.role, stats), today - timedelta(days=1)
    p.career = dict(p.career or {}, decay={'to': today.isoformat(), 'days': days,
                                          'by': {k: {why: round(v, 2) for why, v in d.items() if v >= 0.005}
                                                 for k, d in lost.items()}})
    demoted = []
    from . import rookie_contracts as Contracts
    import secrets
    from . import rookie_league as League
    Contracts.roll_full(p, League.season_no(today))
    while True:
        below = W.demote_below(p.league)
        if below is None or p.ovr >= below:
            break
        if p.league == 'mlb' and Contracts.veto(p):
            data = dict(p.career or {})
            if data.get('mlb_bench_season') != League.season_no(today):
                data.setdefault('assignment_pending', Contracts.assignment_view(p, secrets.token_hex(8)))
            p.career = data
            break
        p.league = W.prev_league(p.league)
        p.league_since = today
        demoted.append(W.league(p.league)['name'])
    p.save(update_fields=['stats', 'ovr', 'settled_through', 'league', 'league_since', 'career', 'updated_at'])
    idle = (today - p.last_active).days
    if before - p.ovr >= 0.05 and idle >= 2:          # 매일의 유지비는 기록하지 않는다 — 쉬어서 빠질 때만
        _log(p, 'decay', f'감각 저하({idle - 1}일 활동 없음) — OVR {before:.1f} → {p.ovr:.1f}', day=today)
        if idle >= 4 and C.reveal(p, 'iron', today):
            p.save(update_fields=['traits_seen'])
    for name in demoted:
        _log(p, 'demote', f'OVR {p.ovr:.1f} — {name}에서 다시 준비해요', day=today)
    return {'days': days, 'before': before, 'after': p.ovr, 'demoted': demoted}


def settle(p, today: date | None = None) -> dict:
    """어제까지 하루씩 감쇠를 반영하고(문턱 아래면 강등), 학년·진학·드래프트·나이를 오늘까지 진행한다."""
    from . import rookie_career as C
    today = today or timezone.localdate()
    if p.retired_at:
        return {'days': 0, 'before': p.ovr, 'after': p.ovr, 'demoted': []}
    out = _decay(p, today)
    out['career'] = C.progress(p, today)
    return out


def locked(user):
    """회원의 현역 선수(행 잠금). 은퇴한 선수는 기록으로만 남는다."""
    from .models import RookiePlayer
    return RookiePlayer.objects.select_for_update().filter(user=user, retired_at__isnull=True).first()


def settled(user, today: date | None = None):
    """정산을 먼저 따로 커밋한다 — 학년 전환·드래프트·은퇴 같은 진행이 뒤따르는 동작의 실패와 함께 되돌려져
    같은 요청을 되풀이할 때마다 다시 굴려지지 않게. (선수 또는 None, 정산 전 pending)"""
    with transaction.atomic():
        p = locked(user)
        if p is None:
            return None, None
        before = dict(p.pending or {})
        settle(p, today)
    return p, before


def gone(user) -> str:
    """현역 선수가 없을 때의 안내 — 방금 은퇴했으면 그렇게 말한다."""
    from .models import RookiePlayer
    if RookiePlayer.objects.filter(user=user, retired_at__isnull=False).exists():
        return '선수가 은퇴했어요. 새 선수로 다시 시작해 주세요.'
    return '먼저 선수를 만들어 주세요.'


def current(user_id):
    from .models import RookiePlayer
    return RookiePlayer.objects.filter(user_id=user_id, retired_at__isnull=True).first() if user_id else None


def award(user, source: str, ref: str = '') -> dict | None:
    """사이트 활동 → TP. 선수가 없거나, 오늘 한도를 채웠거나, 같은 ref 로 이미 받았으면 None.
    보유 한도(TP_MAX)에 찼으면 TP 는 0 이지만 활동은 기록한다(출전·감쇠 판정)."""
    if source not in EARN or not getattr(user, 'is_authenticated', False):
        return None
    rule = EARN[source]
    today = timezone.localdate()
    settled(user, today)
    with transaction.atomic():
        p = locked(user)
        if p is None:                                   # 선수가 없거나 정산하다 은퇴했다
            return None
        settle(p, today)                                # 이미 정산됨 — 할 일 없음
        earned = p.logs.filter(kind='earn', source=source)
        # 같은 칼럼·댓글로는 30일에 한 번 — 밀린 칼럼을 다 읽은 장기 회원도 다시 읽으면 TP 를 받는다
        if ref and earned.filter(ref=ref, day__gt=today - timedelta(days=REPEAT_DAYS)).exists():
            return None
        count = earned.filter(day=today).count()
        if count >= rule['cap']:
            return None
        got = max(0, min(rule['tp'], TP_MAX - p.tp))
        p.tp += got
        p.tp_earned += got
        p.last_active = today
        p.save(update_fields=['tp', 'tp_earned', 'last_active', 'updated_at'])
        note = '' if got == rule['tp'] else f' (보유 한도 {TP_MAX} TP)'
        _log(p, 'earn', f"{rule['label']} +{got} TP{note}", tp=got, source=source, ref=ref, day=today)
    return {'tp': got, 'label': rule['label'], 'count': count + 1, 'cap': rule['cap'], 'full': got < rule['tp']}


def safe_award(user, source: str, ref: str = '') -> dict | None:
    """신호·뷰에서 부르는 판 — 게임 쪽 오류가 글·댓글 쓰기를 막지 않게."""
    try:
        return award(user, source, ref)
    except Exception:  # noqa: BLE001
        logger.warning('야구선수 키우기 TP 지급 실패: %s %s', source, ref, exc_info=True)
        return None


def trained_today(p, today: date | None = None) -> int:
    """오늘 훈련 횟수 — 훈련 기록의 TP 차감 합 ÷ 1회 비용."""
    from django.db.models import Sum
    spent = p.logs.filter(kind='train', day=today or timezone.localdate()).aggregate(s=Sum('tp'))['s'] or 0
    return -spent // TRAIN_COST


def train(user, stat: str, times: int = 1, rng=None) -> dict:
    from . import rookie_career as C
    rng = rng or random.SystemRandom()
    times = max(1, min(10, int(times or 1)))
    today = timezone.localdate()
    settled(user, today)
    with transaction.atomic():
        p = locked(user)
        if p is None:
            raise GameError(gone(user))
        settle(p, today)
        if stat not in p.stats:
            raise GameError('훈련할 능력을 다시 골라 주세요.')
        label = dict((k, l) for k, l, _w in ROLES[p.role]['stats'])[stat]
        cap = C.stat_cap(p, stat)
        before = s = float(p.stats[stat])
        if s >= cap - 0.05:
            raise GameError(C.cap_message(p, stat, label))
        cost = TRAIN_COST * times
        if p.tp < cost:
            raise GameError(f'훈련 포인트가 모자라요(필요 {cost} TP, 보유 {p.tp} TP).')
        done = trained_today(p, today)
        fat = C.fatigue_at(p)
        from . import rookie_story as Story
        from . import rookie_development as Development
        m = mult(stat, p.focus, C.focus_bonus(p)) * C.age_mult(p) * Story.training_mult(p) * Development.multiplier(p)
        great = tired = 0
        for i in range(times):
            eff = FATIGUE_EFF if done + i >= fat else 1.0
            tired += eff < 1
            g = rng.random() < GREAT_CHANCE
            great += g
            s = min(cap, s + gain(s) * m * eff * rng.uniform(*SWING) * (GREAT_MULT if g else 1.0) * C.room(s, cap))
        after = round(s, 3)
        p.stats = dict(p.stats, **{stat: after})
        p.tp -= cost
        p.ovr = overall(p.role, p.stats)
        p.best_ovr = max(p.best_ovr, p.ovr)
        p.save(update_fields=['stats', 'tp', 'ovr', 'best_ovr', 'updated_at'])
        extra = (f' · 대성공 {great}회' if great else '') + (f' · 피로 {tired}회' if tired else '')
        _log(p, 'train', f'{label} 훈련 ×{times} — {before:.1f} → {after:.1f}{extra}', tp=-cost, day=today)
        found = (done + times > FATIGUE_AT and C.reveal(p, 'grinder', today)) | \
            (stat == p.focus and C.reveal(p, 'natural', today))
        if found:
            p.save(update_fields=['traits_seen'])
    return {'player': p, 'stat': stat, 'label': label, 'before': before, 'after': after, 'great': great,
            'tired': tired, 'capped': after >= cap - 0.05}


# 수상 축하 연출(2026-10-19 사용자 요청) — 새로 받은 상을 한 번 축하한다. 본 상은 career['award_seen'](상 pk)로.
AWARD_HERO = ('mvp', 'ace', 'rookie', 'gg', 'title', 'minor')


def award_fx(p) -> dict | None:
    """새로 받은 상 — 가장 큰 상 하나를 앞에, 나머지는 곁에. p.career 를 고치니 부른 쪽이 저장한다."""
    from .models import RookieAward
    from .rookie_card import _palette
    seen = int((p.career or {}).get('award_seen') or 0)
    new = list(RookieAward.objects.filter(player=p, pk__gt=seen).select_related('season'))
    if not new:
        return None
    p.career = dict(p.career or {}, award_seen=max(a.pk for a in new))
    hero = min(new, key=lambda a: AWARD_HERO.index(a.kind) if a.kind in AWARD_HERO else 9)
    n = RookieAward.objects.filter(player=p, league=hero.league, label=hero.label).count()
    pal = _palette(p.league, p.club)
    return {'hero': hero.label, 'kind': hero.kind, 'n': n,
            'kicker': f"시즌 {hero.season.number} · {W.league(hero.league)['name']}",
            'count': f'통산 {n}번째' if n > 1 else '첫 수상', 'line': hero.value,
            'others': [f'{W.short(a.league)} {a.label}' if a.league != hero.league else a.label for a in new if a.pk != hero.pk],
            'colors': [pal['primary'], pal['secondary']]}


def awaken(user, choice: str, rng=None) -> dict:
    """각성 도전(rookie_career.awaken_ready 일 때) — 'try' 는 TP 를 쓰고 확률로, 'skip' 은 미룬다.
    결과 연출은 career['awaken_fx'] 에 남겨 다음 화면이 한 번 보여 준다."""
    from . import rookie_career as C
    rng = rng or random.SystemRandom()
    today = timezone.localdate()
    settled(user, today)
    with transaction.atomic():
        p = locked(user)
        if p is None:
            raise GameError(gone(user))
        settle(p, today)
        if choice not in ('try', 'skip'):
            raise GameError('도전할지 정해 주세요.')
        if not C.awaken_ready(p, today):
            raise GameError('지금은 각성 조건을 채우지 못했어요. 능력치·시즌 성적·재도전 대기 기간을 확인해 주세요.')
        career = dict(p.career or {})
        career['awaken_next'] = (today + timedelta(days=C.AWAKEN_WAIT)).isoformat()
        if choice == 'skip':
            p.career = career
            p.save(update_fields=['career', 'updated_at'])
            return {'player': p, 'text': f'지금의 나를 다듬기로 했어요 — {C.AWAKEN_WAIT}일 뒤에 다시 기회가 와요'}
        if p.tp < C.AWAKEN_COST:
            raise GameError(f'각성 훈련엔 {C.AWAKEN_COST} TP가 필요해요(보유 {p.tp} TP).')
        odds = C.awaken_odds(p)
        p.tp -= C.AWAKEN_COST
        labels = dict((k, lab) for k, lab, _w in ROLES[p.role]['stats'])
        if rng.random() < odds:
            gain = C.awaken_gain(p)
            n = C.awakened(p) + 1
            career['awaken'] = n
            p.career = career
            ups = []
            for k in [p.focus or min(p.stats, key=lambda x: float(p.stats[x])), min(p.stats, key=lambda x: float(p.stats[x]))]:
                if k in p.stats and labels[k] not in [u[0] for u in ups]:
                    p.stats = dict(p.stats, **{k: round(min(C.stat_cap(p, k), float(p.stats[k]) + 1.5), 3)})
                    ups.append([labels[k], 1.5])
            total = min(5, C.base_stars(p) + n)
            career['awaken_fx'] = {'ok': True, 'n': n, 'plus': gain, 'ups': ups, 'stars': total}
            text = f'각성에 성공했어요! 별이 {total}개가 됐어요 — 잠재력 +{gain:g}'
            _log(p, 'mile', f'각성 — 별 {total}개(보라색 {n}), 잠재력 +{gain:g}', tp=-C.AWAKEN_COST, day=today)
        else:
            k = 'mental' if p.role == 'pitcher' else 'eye'
            p.stats = dict(p.stats, **{k: round(max(FLOOR, float(p.stats[k]) - 1.0), 3)})
            career['awaken_fx'] = {'ok': False, 'fail_text': f'무리한 탓에 {labels[k]}이 1 빠졌어요. '
                                                             f'{C.AWAKEN_WAIT}일 뒤에 다시 도전할 수 있어요.'}
            text = f'벽은 아직 높았어요 — {labels[k]} −1, {C.AWAKEN_WAIT}일 뒤에 다시'
            _log(p, 'train', f'각성 실패 — {labels[k]} −1', tp=-C.AWAKEN_COST, day=today)
        p.career = career
        p.ovr = overall(p.role, p.stats)
        p.best_ovr = max(p.best_ovr, p.ovr)
        p.save(update_fields=['career', 'tp', 'stats', 'ovr', 'best_ovr', 'updated_at'])
    return {'player': p, 'text': text}


BATTER_LINES = [(10, ['4타수 3안타 1홈런 3타점', '5타수 3안타 2타점 1도루']), (5, ['4타수 2안타 2타점', '4타수 2안타 1볼넷']),
                (0, ['4타수 1안타 1타점', '3타수 1안타 1볼넷']), (-5, ['4타수 1안타', '4타수 무안타 1볼넷']),
                (-99, ['4타수 무안타 2삼진', '4타수 무안타 병살 1개'])]
PITCHER_LINES = [(10, ['7이닝 무실점 9탈삼진', '8이닝 1실점 8탈삼진']), (5, ['6이닝 1실점 6탈삼진', '6이닝 2실점 7탈삼진']),
                 (0, ['5이닝 2실점 4탈삼진', '5⅓이닝 3실점 5탈삼진']), (-5, ['4이닝 3실점', '4⅔이닝 4실점']),
                 (-99, ['2⅔이닝 5실점 강판', '3이닝 6실점'])]


def box_line(role: str, margin: float, rng) -> str:
    for floor_, lines in (PITCHER_LINES if role == 'pitcher' else BATTER_LINES):
        if margin >= floor_:
            return rng.choice(lines)
    return ''


def promotion_test(user, rng=None) -> dict:
    """청백전 3경기 — 경기마다 OVR ± 흔들림(표준편차 7)이 문턱 이상이면 합격, 2경기 합격이면 같은 사다리 한 단계 위로.
    OVR 밖에 지금 리그 최소 체류와 최근 14일 성적 과제를 채워야 받을 수 있다(rookie_career.promotion_gate)."""
    from . import rookie_career as C
    rng = rng or random.SystemRandom()
    today = timezone.localdate()
    settled(user, today)
    with transaction.atomic():
        p = locked(user)
        if p is None:
            raise GameError(gone(user))
        settle(p, today)
        if not W.is_pro(p.league):
            raise GameError('학생 선수는 학년이 오르면서 진학해요. 콜업 테스트는 프로에서 받을 수 있어요.')
        nxt = W.next_league(p.league)
        if nxt is None:
            raise GameError(f"이미 {W.league(p.league)['name']} 선수예요.")
        at = W.promote_at(p.league)
        name = W.league(nxt)['name']
        if p.ovr < at:
            raise GameError(f'{name} 콜업 테스트는 OVR {at:g}부터 받을 수 있어요.')
        gate = C.promotion_gate(p, today)
        if gate['stay_left']:
            raise GameError(f"{name} 콜업 테스트는 지금 리그에서 {gate['stay_need']}일을 뛴 뒤에 받을 수 있어요"
                            f"({gate['stay_left']}일 남음).")
        if not gate['mission']['ok']:
            raise GameError(f"콜업 테스트 조건: {gate['mission']['text']}(지금 {gate['mission']['now']}).")
        if p.test_on == today:
            raise GameError('콜업 테스트는 하루 한 번이에요. 내일 다시 도전해 주세요.')
        games = []
        for i in range(TEST_GAMES):
            margin = p.ovr + rng.gauss(0, TEST_SPREAD) - at
            games.append({'no': i + 1, 'ok': margin >= 0, 'line': box_line(p.role, margin, rng)})
        passed = sum(g['ok'] for g in games) >= TEST_PASS
        p.test_on = today
        if passed:
            p.league, p.league_since = nxt, today
            p.lineup = 'mop' if p.role == 'pitcher' else 'bench'   # 새 리그에선 백업·패전조부터 다시 증명한다
            p.slot, p.role_since = 0, today
        p.save(update_fields=['test_on', 'league', 'league_since', 'lineup', 'slot', 'role_since', 'updated_at'])
        won = sum(g['ok'] for g in games)
        _log(p, 'promote' if passed else 'test',
             f"{name} 승격! {'패전조' if p.role == 'pitcher' else '백업'}부터 다시 자리를 따내야 해요" if passed
             else f'{name} 콜업 테스트 {won}/{TEST_GAMES} — 탈락', day=today)
    return {'passed': passed, 'league_name': name, 'games': games, 'won': won, 'player': p}


def retire(user, reason: str = '스스로 은퇴') -> bool:
    """현역 선수를 은퇴시킨다 — 선수와 기록은 남고(명예의 전당·기록실), 회원은 새 선수로 다시 시작할 수 있다."""
    from . import rookie_career as C
    with transaction.atomic():
        p = locked(user)
        if p is None:
            return False
        C.retire_player(p, reason)
    return True


def settle_all(today: date | None = None, *, stale_only: bool = True) -> int:
    """모든 현역 선수 정산(밤 cron·순위표). 이미 어제까지 정산된 선수는 건너뛴다."""
    from .models import RookiePlayer
    today = today or timezone.localdate()
    qs = RookiePlayer.objects.filter(retired_at__isnull=True)
    if stale_only:
        qs = qs.filter(settled_through__lt=today - timedelta(days=1))
    n = failed = 0
    for pk in list(qs.values_list('pk', flat=True)):
        try:
            with transaction.atomic():
                p = RookiePlayer.objects.select_for_update().get(pk=pk)
                settle(p, today)
            n += 1
        except Exception:  # noqa: BLE001 — 선수 한 명의 오류가 밤 정산 전체·리그 화면을 멈추지 않게
            failed += 1
            logger.exception('야구선수 키우기 정산 실패: player=%s', pk)
    if failed:
        logger.error('야구선수 키우기 정산: 성공 %s명, 실패 %s명', n, failed)
    return n


# ───────────────────────────── 화면용
def today_earned(p, today: date | None = None) -> list:
    today = today or timezone.localdate()
    counts = {}
    for src in p.logs.filter(kind='earn', day=today).values_list('source', flat=True):
        counts[src] = counts.get(src, 0) + 1
    return [{'source': s, 'label': r['label'], 'tp': r['tp'], 'cap': r['cap'], 'count': counts.get(s, 0),
             'done': counts.get(s, 0) >= r['cap']} for s, r in EARN.items()]


DECAY_WHY = {'upkeep': '기본 감각 저하', 'rest': '쉰 날 감각 저하', 'aging': '나이(노쇠)'}


def stat_drop(p, k: str, today: date | None = None) -> dict | None:
    """오늘 아침 정산에서 이 능력이 빠진 만큼과 이유 — 0.05 넘게 빠졌을 때만."""
    d = (p.career or {}).get('decay') or {}
    today = today or timezone.localdate()
    if d.get('to') != today.isoformat():
        return None
    by = (d.get('by') or {}).get(k) or {}
    total = round(sum(by.values()), 2)
    if total < 0.05:
        return None
    days = d.get('days', 1)
    return {'total': round(total, 1), 'when': '어젯밤' if days <= 1 else f'지난 {days}일',
            'parts': [{'label': DECAY_WHY[w], 'value': round(v, 1) if v >= 0.05 else round(v, 2)}
                      for w, v in sorted(by.items(), key=lambda x: -x[1]) if v >= 0.01]}


def stat_rows(p, done_today: int = 0) -> list:
    from . import rookie_career as C
    fat, scale, bonus = C.fatigue_at(p), C.age_mult(p), C.focus_bonus(p)
    rows = []
    for k, label, w in ROLES[p.role]['stats']:
        s = float(p.stats.get(k, FLOOR))
        cap = C.stat_cap(p, k)
        m = mult(k, p.focus, bonus) * scale
        rows.append({'key': k, 'label': label, 'value': s, 'shown': int(s), 'bar': round(s / CAP * 100, 1),
                     'focus': k == p.focus, 'weight': int(w * 100), 'cap': cap,
                     'cap_bar': round(cap / CAP * 100, 1) if cap < CAP else None,
                     'capped': s >= cap - 0.05, 'near': cap - s < C.TAPER,
                     'next_gain': round(train_value(s, 1, m, done_today, cap, fat) - s, 1),
                     'five_gain': round(train_value(s, 5, m, done_today, cap, fat) - s, 1),
                     'role': STAT_ROLE.get(k, ''), 'drop': stat_drop(p, k)})
    return rows


def condition(p, today: date | None = None) -> dict:
    from . import rookie_career as C
    today = today or timezone.localdate()
    idle = (today - p.last_active).days
    rate = decay_rate(idle + 1)          # 오늘도 아무것도 안 하면 오늘 밤 빠질 비율
    if idle == 0:
        state, note = 'good', '오늘 활동 완료 — 활동 공백에 따른 추가 감각 저하를 막았어요.'
    elif idle == 1:
        state, note = 'ok', f'어제 마지막 활동 — 오늘 활동하지 않으면 오늘 밤 {rate * 100:g}%가 빠져요.'
    else:
        state, note = 'bad', f'{idle}일째 활동 없음 — 하루 {rate * 100:g}%씩 빠지는 중. 오늘 활동하면 공백에 따른 추가 하락을 막을 수 있어요.'
    aging = p.age >= C.decline_start(p)
    upkeep, over = upkeep_of(p)
    return {'state': state, 'idle': idle, 'rate': rate, 'note': note, 'aging': aging, 'upkeep': upkeep,
            'upkeep_over': over}


def level_case():
    """리그 코드 → 리그 수준(순위 정렬: 높은 리그가 먼저, 같은 리그면 OVR)."""
    from django.db.models import Case, FloatField, Value, When
    return Case(*[When(league=c, then=Value(v['level'])) for c, v in W.LEAGUES.items()], default=Value(0.0),
                output_field=FloatField())


def ranked():
    """순위표 대상 — 현역만(운영자 선수도 함께 — game_visibility.ROOKIE_HIDES_ADMIN), lv(리그 수준) 주석."""
    from .game_visibility import rookie_visible
    from .models import RookiePlayer
    return rookie_visible(RookiePlayer.objects.filter(retired_at__isnull=True), 'user').annotate(lv=level_case())


def dashboard(p) -> dict:
    from . import rookie_career as C
    from . import rookie_story as Story
    from .rookie_league import player_board
    nxt = W.next_league(p.league)
    progress = None
    if nxt:
        at = W.promote_at(p.league)
        lo = W.level(p.league) - W.DEMOTE_GAP
        gate = C.promotion_gate(p)
        progress = {'name': W.league(nxt)['name'], 'short': W.short(nxt), 'at': at,
                    'left': round(max(0.0, at - p.ovr), 1),
                    'pct': round(min(100.0, max(0.0, (p.ovr - lo) / (at - lo) * 100)), 1),
                    'ovr_ok': p.ovr >= at, 'ready': p.ovr >= at and gate['ok'], 'gate': gate,
                    'tried_today': p.test_on == timezone.localdate()}
    rank = ranked().filter(league=p.league, ovr__gt=p.ovr).count() + 1      # 같은 리그 안에서
    done = trained_today(p)
    fat = C.fatigue_at(p)
    return {
        'p': p, **identity(p),
        'mind': Story.view(p), 'story': Story.daily_view(p),
        'stats': stat_rows(p, done), 'earned': today_earned(p), 'cond': condition(p), 'next': progress,
        'demote_at': W.demote_below(p.league), 'rank': rank, 'career': C.career_view(p),
        'trained': done, 'fatigue_at': fat, 'tired': done >= fat, 'tp_max': TP_MAX, 'tp_full': p.tp >= TP_MAX,
        'logs': list(p.logs.all()[:12]), 'cost': TRAIN_COST, 'cost5': TRAIN_COST * 5, 'daily_max': DAILY_MAX,
        'coach': S.staff(p.league, p.club, 'coding', p.role),       # 지금 소속의 코치(학교·나라·구단마다 다른 사람)
        'awaken': C.awaken_view(p), 'awaken_coach': S.staff(p.league, p.club, 'hrd', p.role),
        **player_board(p),
    }
