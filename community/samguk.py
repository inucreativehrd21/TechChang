"""테크창 삼국지 — DB 층(docs/samguk-design.md 2·3·9장). 규칙은 samguk_rules, 판 생성은 samguk_board.

- 게임일: 06:00 에 바뀐다(KST). game_day() 가 지금이 어느 게임일인지 알려 준다.
- 하루 한 판, 다시 시작 없음. 행동 하나 = SamgukAction 한 줄(seq 로 중복 요청을 막는다).
- 추가 군령은 SamgukActivity(출석·칼럼 읽기·댓글/답변)에서 센다. 출석은 '달력 날짜 D 의 출석 = 게임일 D'(설계 3.1).
- 게임 쪽 오류가 글·댓글·출석을 막지 않게, 사이트 신호에서는 safe_credit 만 부른다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import samguk_board as B
from . import samguk_data as D
from . import samguk_rules as R
from .models import (SamgukAction, SamgukActivity, SamgukCodex, SamgukDay, SamgukMember, SamgukRun)

logger = logging.getLogger(__name__)

DAY_START = time(6, 0)
FACTION_LOCK_DAYS = 7
BONUS = {'checkin': (2, 1), 'column': (1, 2), 'comment': (1, 1)}     # source: (군령, 하루 한도)
MIN_COMMENT = 10
TOP_N = 3                                                            # 세력 점수 = 상위 3명 합 ÷ 3


class GameError(ValueError):
    """화면에 그대로 보여 줄 오류."""


def public() -> bool:
    from common.game_controls import enabled
    return enabled('SAMGUK_ENABLED')


def allowed(user) -> bool:
    """공개 전에는 운영진만 들어간다(비공개 시험, 설계 12장 8단계)."""
    return public() or bool(getattr(user, 'is_staff', False))


# ── 게임일 ──────────────────────────────────────────────────────────────
def game_day(now: datetime | None = None) -> date:
    local = timezone.localtime(now or timezone.now())
    return (local - timedelta(hours=DAY_START.hour, minutes=DAY_START.minute)).date()


def day_bounds(day: date) -> tuple:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, DAY_START), tz)
    return start, start + timedelta(days=1)


# ── 하루 ────────────────────────────────────────────────────────────────
def get_day(day: date | None = None) -> SamgukDay:
    """그날 판을 가져오거나 만든다. 어제 1위가 있으면 오늘 판의 군벌로 들어온다."""
    day = day or game_day()
    found = SamgukDay.objects.filter(date=day).first()
    if found:
        return found
    from django.conf import settings
    board = B.generate(day, boss=_boss_for(day - timedelta(days=1)))
    if getattr(settings, 'SAMGUK_BALANCE_STARTS', True):        # 시작 도시 보정(판 하나 약 3초, 하루 한 번)
        from . import samguk_balance
        board = samguk_balance.compensate(board)
    try:
        with transaction.atomic():
            return SamgukDay.objects.create(date=day, rules_version=R.RULES_VERSION, board=board)
    except IntegrityError:                                           # 다른 요청이 먼저 만들었다
        return SamgukDay.objects.get(date=day)


def _boss_for(prev: date) -> dict | None:
    """어제의 천하인 편성 — 최종 상태에서 가장 강한 장수 셋과 병력."""
    run = (SamgukRun.objects.filter(day__date=prev, rank=1).select_related('user', 'user__profile').first())
    if not run or not run.state:
        return None
    st = run.state
    officers = sorted(R.my_officers(st), key=lambda o: -(D.GENERAL[o].lead + D.GENERAL[o].war))[:3]
    if not officers:
        return None
    troops = sum(st['cities'][c]['troops'] for c in R.mine(st))
    return {'name': display_name(run.user), 'officers': officers, 'troops': troops}


def display_name(user) -> str:
    try:
        return user.profile.display_name
    except Exception:  # noqa: BLE001 — 프로필이 없는 계정
        return user.username


# ── 회원·세력 ────────────────────────────────────────────────────────────
def member(user) -> SamgukMember:
    m, _ = SamgukMember.objects.get_or_create(user=user)
    return m


def faction_change_ready(m: SamgukMember, today: date | None = None) -> date | None:
    """세력을 바꿀 수 있으면 None, 아니면 바꿀 수 있는 날."""
    if not m.faction or not m.faction_since:
        return None
    ready = m.faction_since + timedelta(days=FACTION_LOCK_DAYS)
    return None if (today or game_day()) >= ready else ready


def set_faction(user, faction: str) -> SamgukMember:
    if faction not in D.FACTIONS:
        raise GameError('세력을 다시 골라 주세요.')
    with transaction.atomic():
        m = SamgukMember.objects.select_for_update().get_or_create(user=user)[0]
        if m.faction == faction:
            return m
        ready = faction_change_ready(m)
        if ready:
            raise GameError(f'세력은 7일에 한 번 바꿀 수 있어요({ready.month}월 {ready.day}일부터).')
        m.faction, m.faction_since = faction, game_day()
        m.save(update_fields=['faction', 'faction_since', 'updated_at'])
    return m


def set_tutorial(user, value: str) -> None:
    if value not in ('done', 'skipped'):
        raise GameError('알 수 없는 선택이에요.')
    SamgukMember.objects.filter(pk=member(user).pk).update(tutorial=value)


# ── 추가 군령 ────────────────────────────────────────────────────────────
def bonus_total(user, day: date) -> int:
    rows = SamgukActivity.objects.filter(user=user, day=day).values_list('source', flat=True)
    counts: dict = {}
    for src in rows:
        counts[src] = counts.get(src, 0) + 1
    total = sum(per * min(counts.get(src, 0), cap) for src, (per, cap) in BONUS.items())
    return min(total, R.AP_BONUS_MAX)


def credit(user, source: str, ref: str = '', day: date | None = None) -> int:
    """사이트 활동 한 건을 기록하고 오늘 판에 군령을 더한다. 더한 군령을 돌려준다."""
    if source not in BONUS or not getattr(user, 'is_authenticated', False) or not allowed(user):
        return 0
    day = day or game_day()
    _, created = SamgukActivity.objects.get_or_create(user=user, day=day, source=source, ref=ref[:40])
    if not created:
        return 0
    with transaction.atomic():
        run = SamgukRun.objects.select_for_update().filter(user=user, day__date=day).first()
        if run is None:
            return 0                                                 # 판을 열 때 합산한다
        return _sync_bonus(run, day)


def _sync_bonus(run: SamgukRun, day: date) -> int:
    want = bonus_total(run.user, day)
    st = run.state
    got = R.add_bonus(st, want - st['ap_bonus']) if want > st['ap_bonus'] else 0
    if got:
        run.state, run.ap_bonus = st, st['ap_bonus']
        if not st['over'] and run.finished_at:
            run.finished_at = None
        run.save(update_fields=['state', 'ap_bonus', 'finished_at', 'updated_at'])
    return got


def safe_credit(user, source: str, ref: str = '', day: date | None = None) -> int:
    try:
        return credit(user, source, ref, day)
    except Exception:  # noqa: BLE001
        logger.warning('테크창 삼국지 군령 지급 실패: %s %s', source, ref, exc_info=True)
        return 0


# ── 판 ─────────────────────────────────────────────────────────────────
def today_run(user, day: SamgukDay | None = None) -> SamgukRun | None:
    day = day or get_day()
    return SamgukRun.objects.filter(user=user, day=day).first()


def start(user, start_index: int) -> SamgukRun:
    day = get_day()
    if day.status != 'open':
        raise GameError('오늘 판은 이미 닫혔어요.')
    m = member(user)
    if not m.faction:
        raise GameError('세력을 먼저 골라 주세요.')
    seed = B.run_seed(day.date, user.pk)
    try:
        state = R.new_run(day.board, m.faction, int(start_index), seed)
    except (R.RuleError, ValueError) as e:
        raise GameError(str(e)) from None
    try:
        with transaction.atomic():
            run = SamgukRun.objects.create(user=user, day=day, faction=m.faction, start_city=state['start'],
                                           state=state, score=R.score(state)['total'])
            _sync_bonus(run, day.date)
            _codex_update(run)
    except IntegrityError:
        raise GameError('오늘 판은 이미 시작했어요.') from None
    return run


def act(user, action: dict, seq: int | None = None) -> tuple:
    """행동 하나. seq 가 오면 그 번호일 때만 처리한다(새로 고침·두 번 누르기 막기). (run, result)"""
    day = get_day()
    with transaction.atomic():
        run = SamgukRun.objects.select_for_update().filter(user=user, day=day).first()
        if run is None:
            raise GameError('먼저 시작 도시를 골라 주세요.')
        done = run.actions.count()
        if seq is not None and int(seq) != done:
            raise GameError('화면이 오래됐어요. 새로 고친 뒤 다시 해 주세요.')
        if day.status != 'open':
            raise GameError('오늘 판은 닫혔어요.')
        from . import samguk_legends as L
        if action.get('kind') == 'legend':
            L.check_event_action(user, run, action)              # 그 사람의 지금 단계·장수 조건(군령을 쓰기 전에)
        try:
            state, result = R.apply(day.board, run.state, action)
        except R.RuleError as e:
            raise GameError(str(e)) from None
        run.state = state
        run.ap_spent = state['ap_spent']
        run.score = R.score(state)['total']
        if state['over'] and not run.finished_at:
            run.finished_at = timezone.now()
        run.save(update_fields=['state', 'ap_spent', 'score', 'finished_at', 'updated_at'])
        SamgukAction.objects.create(run=run, seq=done, kind=action.get('kind', ''), payload=action, result=result)
        _codex_update(run)
        result['legends'] = L.after_action(user, run, result)
    return run, result


def _codex_update(run: SamgukRun) -> None:
    """판에서 만난 장수는 발견, 등용한 장수는 등용으로 도감에 올린다. 튜토리얼 판은 여기 오지 않는다."""
    st = run.state
    today = run.day.date
    have = {c.general: c for c in SamgukCodex.objects.filter(user=run.user, general__in=st['seen'])}
    new = [SamgukCodex(user=run.user, general=code, first_seen=today) for code in st['seen'] if code not in have]
    if new:
        SamgukCodex.objects.bulk_create(new, ignore_conflicts=True)
        have = {c.general: c for c in SamgukCodex.objects.filter(user=run.user, general__in=st['seen'])}
    counted = set(run.state.get('codex_counted', []))
    for code in st['recruited']:
        if code in counted:
            continue
        row = have.get(code)
        if row is None:
            row = SamgukCodex.objects.create(user=run.user, general=code, first_seen=today)
        row.times_recruited += 1
        row.first_recruited = row.first_recruited or today
        row.save(update_fields=['times_recruited', 'first_recruited'])
        counted.add(code)
    if counted != set(run.state.get('codex_counted', [])):
        run.state['codex_counted'] = sorted(counted)
        SamgukRun.objects.filter(pk=run.pk).update(state=run.state)
        from . import samguk_manor as M
        M.codex_milestones(run.user)


# ── 마감 ───────────────────────────────────────────────────────────────
def close_day(day: date) -> SamgukDay | None:
    """그날 판을 닫는다: 순위 → 1위 칭호·연속 기록 → 세력 점수. 이미 닫혔으면 그대로."""
    with transaction.atomic():
        d = SamgukDay.objects.select_for_update().filter(date=day).first()
        if d is None or d.status == 'closed':
            return d
        now = timezone.now()
        runs = list(SamgukRun.objects.select_for_update().filter(day=d))
        for run in runs:
            if not run.finished_at:
                run.finished_at = now
            run.score = R.score(run.state)['total']
        runs.sort(key=lambda r: (-r.score, r.ap_spent, r.finished_at, r.pk))
        for i, run in enumerate(runs, 1):
            run.rank = i
            run.save(update_fields=['rank', 'score', 'finished_at', 'updated_at'])
        by_fac: dict = {}
        for run in runs:
            by_fac.setdefault(run.faction, []).append(run.score)
        d.faction_scores = {f: round(sum(sorted(v, reverse=True)[:TOP_N]) / TOP_N) for f, v in by_fac.items()}
        d.winner = runs[0].user if runs else None
        d.status, d.closed_at = 'closed', now
        d.save(update_fields=['faction_scores', 'winner', 'status', 'closed_at'])
        played = {r.user_id: r for r in runs}
        from . import samguk_legends as L
        for run in runs:
            L.on_close(run.user, run)                              # 누적 단계(일기토 n승 등)를 그날 기록으로
        from . import samguk_manor as M
        for m in SamgukMember.objects.select_for_update().filter(user_id__in=played):
            run = played[m.user_id]
            fields = ['best_score', 'streak', 'fame', 'updated_at']
            m.best_score = max(m.best_score, run.score)
            m.fame += M.fame_for_run(run.rank, len(runs))          # 장원 명성(설계 7.1)
            if run.rank == 1:
                m.wins += 1
                m.streak += 1
                title = f'{day.month}월 {day.day}일의 천하인'
                m.titles = (m.titles or []) + [title]
                fields += ['wins', 'titles']
                for code in R.my_officers(run.state):
                    SamgukCodex.objects.filter(user=m.user, general=code).update(unified_with=F('unified_with') + 1)
            else:
                m.streak = 0
            m.save(update_fields=fields)
        SamgukMember.objects.exclude(user_id__in=played).filter(streak__gt=0).update(streak=0)
    return d


def daily(now: datetime | None = None) -> dict:
    """cron 06:05 — 지난 게임일을 모두 닫고 오늘 판을 만든다. 화면을 열 때도 따라잡는다."""
    today = game_day(now)
    closed = []
    for d in SamgukDay.objects.filter(status='open', date__lt=today).order_by('date'):
        close_day(d.date)
        closed.append(d.date.isoformat())
    day = get_day(today)
    return {'closed': closed, 'today': day.date.isoformat()}


def catch_up() -> None:
    """화면을 열 때 — cron 이 늦어도 어제 판이 닫혀 있게."""
    today = game_day()
    if SamgukDay.objects.filter(status='open', date__lt=today).exists():
        daily()


# ── 순위 ───────────────────────────────────────────────────────────────
def ranking(day: SamgukDay, limit: int = 50) -> list:
    qs = SamgukRun.objects.filter(day=day).select_related('user', 'user__profile')
    if day.status == 'closed':
        qs = qs.order_by('rank')
    else:
        qs = qs.order_by('-score', 'ap_spent', 'finished_at', 'pk')
    return list(qs[:limit])


def faction_board(day: SamgukDay) -> dict:
    if day.status == 'closed':
        return day.faction_scores or {}
    by_fac: dict = {}
    for f, s in SamgukRun.objects.filter(day=day).values_list('faction', 'score'):
        by_fac.setdefault(f, []).append(s)
    return {f: round(sum(sorted(v, reverse=True)[:TOP_N]) / TOP_N) for f, v in by_fac.items()}
