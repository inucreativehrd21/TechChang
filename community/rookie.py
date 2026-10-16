"""야구선수 키우기 — 사이트 활동으로 키우는 성장 게임(2026-10-16 운영자 요청).

투수·타자 중 하나를 골라 KBO 10개 구단 가운데 응원 팀에 입단 → 육성군 → 2군 → 1군.
훈련 포인트(TP)는 사이트 활동으로만 번다: 출석 체크, 칼럼 읽기, 댓글·답변 달기(하루 한도, 같은 칼럼은 한 번).

설계 — '초반엔 빠르게, 갈수록 꾸준해야 유지'(수렴):
- 성장: 훈련 1회(10 TP)로 오르는 양이 능력치가 높을수록 준다. gain(s) = 4 × ((99 − s) / 74)^1.6
  (25→4.0, 50→2.1, 70→0.9, 80→0.46).
- 감쇠: 매일 (s − 25)의 1.5% 가 빠진다(유지비) — 높을수록 많이 빠진다. 활동이 끊기면 이틀째부터
  1.5% × 쉰 날 수(최대 12%)로 가팔라진다. 그래서 하루 활동량마다 수렴점이 생긴다
  (test_rookie.ConvergenceTests 가 지킨다): 첫날 25 → 40, 2군 문턱까지 2~8일.
  출석만 ≈ 63(2군 상위) · 출석+칼럼 1편 ≈ 68(1군) · +칼럼 2편+댓글 1개 ≈ 75(주전) · 매일 한도 ≈ 79.5(에이스).
  에이스가 일주일 쉬면 60(1군 강등 문턱), 2주 쉬면 39(육성군)까지 떨어진다.
- 승격: OVR 이 문턱(2군 45, 1군 65)을 넘으면 승격 심사(청백전 3경기 중 2경기 합격, 하루 한 번).
  강등: 문턱보다 5 아래로 떨어지면 정산 때 한 단계 내려간다.

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
rookie_settle 명령이 모든 선수를 정산해 순위표가 쉬는 선수를 그대로 두지 않게 한다.
"""
from __future__ import annotations

import logging
import random
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

FLOOR, CAP = 25.0, 99.0           # 능력치 바닥(신인)·천장
GAIN, CURVE = 4.0, 1.6            # 훈련 1회 상승량 = GAIN × ((CAP − s)/(CAP − FLOOR))^CURVE
TRAIN_COST = 10                   # 훈련 1회 TP
BASE_DECAY, MAX_DECAY = 0.015, 0.12
WELCOME_TP = 150
SETTLE_WINDOW = 120               # 그보다 오래 쉬었으면 마지막 120일만 계산(이미 바닥 근처)
DEMOTE_GAP = 5.0
TEST_GAMES, TEST_PASS, TEST_SPREAD = 3, 2, 7.0
FOCUS_BONUS = 1.25                # 주특기 성장 배율
FATIGUE_AT, FATIGUE_EFF = 15, 0.5  # 하루 훈련 15회를 넘으면 효율 절반
SWING = (0.85, 1.15)              # 훈련 1회 흔들림
GREAT_CHANCE, GREAT_MULT = 0.10, 1.5
EXPECTED_MULT = (SWING[0] + SWING[1]) / 2 * (1 + GREAT_CHANCE * (GREAT_MULT - 1))   # 흔들림의 기대 배율

ROLES = {
    'pitcher': {'label': '투수', 'stats': [('velocity', '구속', .25), ('control', '제구', .25),
                                           ('breaking', '변화구', .20), ('stamina', '체력', .15),
                                           ('mental', '멘탈', .15)]},
    'batter': {'label': '타자', 'stats': [('contact', '컨택', .25), ('power', '파워', .25),
                                         ('eye', '선구안', .20), ('speed', '주루', .15),
                                         ('defense', '수비', .15)]},
}
# 구단명은 응원 팀 표시용(로고 없음). 색은 카드 띠·점에만 쓴다.
TEAMS = [
    ('kia', 'KIA 타이거즈', '#EA0029'), ('kt', 'KT 위즈', '#231F20'), ('lg', 'LG 트윈스', '#C30452'),
    ('nc', 'NC 다이노스', '#315288'), ('ssg', 'SSG 랜더스', '#CE0E2D'), ('doosan', '두산 베어스', '#131230'),
    ('lotte', '롯데 자이언츠', '#041E42'), ('samsung', '삼성 라이온즈', '#074CA1'),
    ('kiwoom', '키움 히어로즈', '#820024'), ('hanwha', '한화 이글스', '#FF6600'),
]
TEAM = {code: {'code': code, 'name': name, 'short': name.split()[0], 'color': color} for code, name, color in TEAMS}
TIERS = [{'tier': 0, 'name': '육성군', 'at': 0.0}, {'tier': 1, 'name': '2군', 'at': 45.0},
         {'tier': 2, 'name': '1군', 'at': 65.0}]
EARN = {'checkin': {'tp': 20, 'cap': 1, 'label': '출석 체크'},
        'column': {'tp': 10, 'cap': 3, 'label': '칼럼 읽기'},
        'comment': {'tp': 10, 'cap': 3, 'label': '댓글·답변'}}
DAILY_MAX = sum(e['tp'] * e['cap'] for e in EARN.values())
MIN_COMMENT = 10                  # 이보다 짧은 댓글은 TP 를 주지 않는다


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


def mult(stat: str, focus: str) -> float:
    return FOCUS_BONUS if stat == focus else 1.0


def train_value(s: float, times: int, m: float = 1.0, done_today: int = 0) -> float:
    """기대값으로 본 훈련 결과(화면 안내·시뮬레이션용). 실제 훈련은 train() 이 흔들림을 넣는다."""
    for i in range(times):
        eff = FATIGUE_EFF if done_today + i >= FATIGUE_AT else 1.0
        s = min(CAP, s + gain(s) * m * eff * EXPECTED_MULT)
    return s


def upkeep_tp(role: str, stats: dict, focus: str = '') -> int:
    """꾸준히 활동할 때 지금 능력치를 그대로 지키는 데 하루 드는 TP(유지비 ÷ 훈련 효율)."""
    need = sum(BASE_DECAY * (float(stats[k]) - FLOOR) / (gain(float(stats[k])) * mult(k, focus) * EXPECTED_MULT)
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


def title(role: str, tier: int, ovr: float) -> str:
    if tier == 2:
        if ovr >= 78:
            return '에이스' if role == 'pitcher' else '간판 타자'
        return '주전' if ovr >= 72 else '엔트리'
    return '퓨처스' if tier == 1 else ''


def next_tier(tier: int) -> dict | None:
    return TIERS[tier + 1] if tier + 1 < len(TIERS) else None


# ───────────────────────────── 상태 바꾸기(모두 행 잠금 안에서)
def _log(p, kind, text, *, tp=0, source='', ref='', day=None):
    from .models import RookieLog
    return RookieLog.objects.create(player=p, kind=kind, text=text[:200], tp=tp, source=source, ref=ref[:40],
                                    day=day or timezone.localdate())


def create(user, *, name: str, role: str, team: str, number: int = 0, focus: str = '', position: str = ''):
    from .models import RookiePlayer
    from .rookie_league import PITCHER_POS, POS_LABEL
    if role not in ROLES or team not in TEAM:
        raise GameError('포지션·구단을 다시 골라 주세요.')
    if focus not in stat_keys(role):
        focus = stat_keys(role)[0]
    position = PITCHER_POS if role == 'pitcher' else (position if position in POS_LABEL and position != PITCHER_POS
                                                      else 'OF')
    name = (name or '').strip()[:12] or user.username[:12]
    today = timezone.localdate()
    stats = {k: FLOOR for k in stat_keys(role)}
    with transaction.atomic():
        p = RookiePlayer.objects.create(user=user, name=name, number=max(0, min(99, int(number or 0))), role=role,
                                        team=team, stats=stats, focus=focus, position=position,
                                        ovr=overall(role, stats), best_ovr=FLOOR,
                                        tp=WELCOME_TP, tp_earned=WELCOME_TP, last_active=today,
                                        settled_through=today - timedelta(days=1))
        _log(p, 'start', f"{TEAM[team]['name']} 육성군 입단 — 입단 보너스 +{WELCOME_TP} TP", tp=WELCOME_TP)
    return p


def settle(p, today: date | None = None) -> dict:
    """어제까지 하루씩 감쇠를 반영하고, 문턱 아래로 떨어졌으면 강등한다. 바뀐 게 있으면 저장."""
    today = today or timezone.localdate()
    start = p.settled_through + timedelta(days=1)
    if start >= today:
        return {'days': 0, 'before': p.ovr, 'after': p.ovr, 'demoted': []}
    day = max(start, today - timedelta(days=SETTLE_WINDOW))
    stats = {k: float(p.stats.get(k, FLOOR)) for k in stat_keys(p.role)}
    while day < today:
        r = decay_rate((day - p.last_active).days)
        for k, s in stats.items():
            stats[k] = round(s - (s - FLOOR) * r, 3)
        day += timedelta(days=1)
    days = (today - start).days
    before = p.ovr
    p.stats, p.ovr, p.settled_through = stats, overall(p.role, stats), today - timedelta(days=1)
    demoted = []
    while p.tier > 0 and p.ovr < TIERS[p.tier]['at'] - DEMOTE_GAP:
        demoted.append(TIERS[p.tier - 1]['name'])
        p.tier -= 1
    p.save(update_fields=['stats', 'ovr', 'settled_through', 'tier', 'updated_at'])
    if before - p.ovr >= 0.05:
        idle = (today - p.last_active).days
        why = '유지 훈련 부족' if idle <= 1 else f'{idle - 1}일 활동 없음'
        _log(p, 'decay', f'감각 저하({why}) — OVR {before:.1f} → {p.ovr:.1f}', day=today)
    for name in demoted:
        _log(p, 'demote', f'OVR {p.ovr:.1f} — {name}으로 내려갔습니다', day=today)
    return {'days': days, 'before': before, 'after': p.ovr, 'demoted': demoted}


def locked(user):
    from .models import RookiePlayer
    return RookiePlayer.objects.select_for_update().filter(user=user).first()


def award(user, source: str, ref: str = '') -> dict | None:
    """사이트 활동 → TP. 선수가 없거나, 오늘 한도를 채웠거나, 같은 ref 로 이미 받았으면 None."""
    if source not in EARN or not getattr(user, 'is_authenticated', False):
        return None
    rule = EARN[source]
    today = timezone.localdate()
    with transaction.atomic():
        p = locked(user)
        if p is None:
            return None
        settle(p, today)
        earned = p.logs.filter(kind='earn', source=source)
        if ref and earned.filter(ref=ref).exists():
            return None
        count = earned.filter(day=today).count()
        if count >= rule['cap']:
            return None
        p.tp += rule['tp']
        p.tp_earned += rule['tp']
        p.last_active = today
        p.save(update_fields=['tp', 'tp_earned', 'last_active', 'updated_at'])
        _log(p, 'earn', f"{rule['label']} +{rule['tp']} TP", tp=rule['tp'], source=source, ref=ref, day=today)
    return {'tp': rule['tp'], 'label': rule['label'], 'count': count + 1, 'cap': rule['cap']}


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
    rng = rng or random.SystemRandom()
    times = max(1, min(10, int(times or 1)))
    today = timezone.localdate()
    with transaction.atomic():
        p = locked(user)
        if p is None:
            raise GameError('먼저 선수를 만들어 주세요.')
        settle(p, today)
        if stat not in p.stats:
            raise GameError('훈련할 능력을 다시 골라 주세요.')
        cost = TRAIN_COST * times
        if p.tp < cost:
            raise GameError(f'훈련 포인트가 모자랍니다(필요 {cost} TP, 보유 {p.tp} TP).')
        done = trained_today(p, today)
        before = s = float(p.stats[stat])
        great = tired = 0
        for i in range(times):
            eff = FATIGUE_EFF if done + i >= FATIGUE_AT else 1.0
            tired += eff < 1
            g = rng.random() < GREAT_CHANCE
            great += g
            s = min(CAP, s + gain(s) * mult(stat, p.focus) * eff * rng.uniform(*SWING) * (GREAT_MULT if g else 1.0))
        after = round(s, 3)
        p.stats = dict(p.stats, **{stat: after})
        p.tp -= cost
        p.ovr = overall(p.role, p.stats)
        p.best_ovr = max(p.best_ovr, p.ovr)
        p.save(update_fields=['stats', 'tp', 'ovr', 'best_ovr', 'updated_at'])
        label = dict((k, l) for k, l, _w in ROLES[p.role]['stats'])[stat]
        extra = (f' · 대성공 {great}회' if great else '') + (f' · 피로 {tired}회' if tired else '')
        _log(p, 'train', f'{label} 훈련 ×{times} — {before:.1f} → {after:.1f}{extra}', tp=-cost, day=today)
    return {'player': p, 'stat': stat, 'label': label, 'before': before, 'after': after, 'great': great,
            'tired': tired}


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
    """청백전 3경기 — 경기마다 OVR ± 흔들림(표준편차 7)이 문턱 이상이면 합격, 2경기 합격이면 승격."""
    rng = rng or random.SystemRandom()
    today = timezone.localdate()
    with transaction.atomic():
        p = locked(user)
        if p is None:
            raise GameError('먼저 선수를 만들어 주세요.')
        settle(p, today)
        nxt = next_tier(p.tier)
        if nxt is None:
            raise GameError('이미 1군입니다.')
        if p.ovr < nxt['at']:
            raise GameError(f"{nxt['name']} 승격 심사는 OVR {nxt['at']:g}부터 받을 수 있습니다.")
        if p.test_on == today:
            raise GameError('승격 심사는 하루 한 번입니다. 내일 다시 도전하세요.')
        games = []
        for i in range(TEST_GAMES):
            margin = p.ovr + rng.gauss(0, TEST_SPREAD) - nxt['at']
            games.append({'no': i + 1, 'ok': margin >= 0, 'line': box_line(p.role, margin, rng)})
        passed = sum(g['ok'] for g in games) >= TEST_PASS
        p.test_on = today
        if passed:
            p.tier = nxt['tier']
        p.save(update_fields=['test_on', 'tier', 'updated_at'])
        won = sum(g['ok'] for g in games)
        _log(p, 'promote' if passed else 'test',
             f"{nxt['name']} 승격!" if passed else f"{nxt['name']} 승격 심사 {won}/{TEST_GAMES} — 탈락", day=today)
    return {'passed': passed, 'tier_name': nxt['name'], 'games': games, 'won': won, 'player': p}


def retire(user) -> bool:
    from .models import RookiePlayer
    return RookiePlayer.objects.filter(user=user).delete()[0] > 0


def settle_all(today: date | None = None, *, stale_only: bool = True) -> int:
    """모든 선수 정산(밤 cron·순위표). 이미 어제까지 정산된 선수는 건너뛴다."""
    from .models import RookiePlayer
    today = today or timezone.localdate()
    qs = RookiePlayer.objects.all()
    if stale_only:
        qs = qs.filter(settled_through__lt=today - timedelta(days=1))
    n = 0
    for pk in qs.values_list('pk', flat=True):
        with transaction.atomic():
            p = RookiePlayer.objects.select_for_update().get(pk=pk)
            settle(p, today)
            n += 1
    return n


# ───────────────────────────── 화면용
def today_earned(p, today: date | None = None) -> list:
    today = today or timezone.localdate()
    counts = {}
    for src in p.logs.filter(kind='earn', day=today).values_list('source', flat=True):
        counts[src] = counts.get(src, 0) + 1
    return [{'source': s, 'label': r['label'], 'tp': r['tp'], 'cap': r['cap'], 'count': counts.get(s, 0),
             'done': counts.get(s, 0) >= r['cap']} for s, r in EARN.items()]


def stat_rows(p, done_today: int = 0) -> list:
    rows = []
    for k, label, w in ROLES[p.role]['stats']:
        s = float(p.stats.get(k, FLOOR))
        m = mult(k, p.focus)
        rows.append({'key': k, 'label': label, 'value': s, 'shown': int(s), 'bar': round(s / CAP * 100, 1),
                     'focus': k == p.focus, 'weight': int(w * 100),
                     'next_gain': round(train_value(s, 1, m, done_today) - s, 1),
                     'five_gain': round(train_value(s, 5, m, done_today) - s, 1)})
    return rows


def condition(p, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    idle = (today - p.last_active).days
    rate = decay_rate(idle + 1)          # 오늘도 아무것도 안 하면 오늘 밤 빠질 비율
    if idle == 0:
        state, note = 'good', '오늘 활동 완료 — 오늘 밤엔 유지비만 빠집니다.'
    elif idle == 1:
        state, note = 'ok', f'어제 마지막 활동 — 오늘 활동하지 않으면 오늘 밤 {rate * 100:g}%가 빠집니다.'
    else:
        state, note = 'bad', f'{idle}일째 활동 없음 — 하루 {rate * 100:g}%씩 빠지는 중. 출석 체크 한 번이면 멈춥니다.'
    return {'state': state, 'idle': idle, 'rate': rate, 'note': note, 'upkeep': upkeep_tp(p.role, p.stats, p.focus)}


def dashboard(p) -> dict:
    from .models import RookiePlayer
    from .rookie_league import player_board
    from .game_visibility import visible
    nxt = next_tier(p.tier)
    cur_at = TIERS[p.tier]['at']
    progress = None
    if nxt:
        span = nxt['at'] - cur_at
        progress = {'name': nxt['name'], 'at': nxt['at'], 'left': round(max(0.0, nxt['at'] - p.ovr), 1),
                    'pct': round(min(100.0, max(0.0, (p.ovr - cur_at) / span * 100)), 1),
                    'ready': p.ovr >= nxt['at'], 'tried_today': p.test_on == timezone.localdate()}
    rank = visible(RookiePlayer.objects.filter(ovr__gt=p.ovr), 'user').count() + 1
    done = trained_today(p)
    focus_label = dict((k, l) for k, l, _w in ROLES[p.role]['stats']).get(p.focus, '')
    return {
        'p': p, 'team': TEAM.get(p.team, {}), 'role_label': ROLES[p.role]['label'], 'focus_label': focus_label,
        'tier_name': TIERS[p.tier]['name'], 'title': title(p.role, p.tier, p.ovr),
        'stats': stat_rows(p, done), 'earned': today_earned(p), 'cond': condition(p), 'next': progress,
        'demote_at': cur_at - DEMOTE_GAP if p.tier else None, 'rank': rank,
        'trained': done, 'fatigue_at': FATIGUE_AT, 'tired': done >= FATIGUE_AT,
        'logs': list(p.logs.all()[:12]), 'cost': TRAIN_COST, 'cost5': TRAIN_COST * 5, 'daily_max': DAILY_MAX,
        **player_board(p),
    }
