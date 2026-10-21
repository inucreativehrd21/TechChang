"""야구선수 키우기 — 유산: 통산 성적·이정표·오늘의 베스트 9·리그별 통산 순위·명예의 전당(2026-10-17 사용자 요청).

- 통산 성적: 리그마다 따로(리그 수준이 달라서), 그리고 프로 통산·평생 통산(아마추어 포함)을 따로 더한다.
- 이정표: 프로 통산(모든 프로 리그 합) 기록이 문턱을 넘는 날, 그리고 리그 데뷔전. 선수 기록(kind='mile')에 남는다.
- 오늘의 베스트 9: 경기일마다 리그별로 위치마다 그날 가장 잘한 선수(투수·포수·내야 넷·외야 셋·지명타자).
- 리그별 통산 순위·명예의 전당: 킥루(축구 선수 키우기) 공개 가이드의 은퇴 랭킹 순서를 빌렸다 —
  MVP 수 → 그 리그에서의 최고 OVR → 수상 수 → 통산 WAR. 명예의 전당은 은퇴한 선수 가운데 그 리그에서
  반 시즌(프로 72경기) 이상 뛰었거나 상을 받은 선수.
"""
from __future__ import annotations

from datetime import date

from . import rookie_world as W

MILESTONES = {
    'batter': [('g', (1, 500, 1000, 1500, 2000), '경기'), ('h', (1, 100, 500, 1000, 1500, 2000, 2500, 3000), '안타'),
               ('hr', (1, 50, 100, 200, 300, 400, 500), '홈런'), ('rbi', (500, 1000, 1500), '타점'),
               ('sb', (100, 200, 300), '도루')],
    'pitcher': [('g', (1, 300, 500, 700), '경기'), ('w', (1, 50, 100, 150, 200), '승'), ('sv', (1, 100, 200, 300, 400), '세이브'),
                ('hld', (100, 200, 300), '홀드'), ('so', (1000, 2000, 3000), '탈삼진')],
}
FIRST = {'g': '프로 데뷔전', 'h': '프로 첫 안타', 'hr': '프로 첫 홈런', 'w': '프로 첫 승', 'sv': '프로 첫 세이브'}
NINE = [('SP', '투수'), ('C', '포수'), ('1B', '1루수'), ('2B', '2루수'), ('3B', '3루수'), ('SS', '유격수'),
        ('OF', '외야수'), ('DH', '지명타자')]
HOF_GAMES = 72


def _sum(rows) -> dict:
    from .rookie_league import add
    t = {}
    for totals in rows:
        t = add(t, totals or {})
    return t


def pro_totals(p) -> dict:
    from .models import RookieSeasonStat
    pro = [c for c in W.LEAGUES if W.is_pro(c)]
    return _sum(RookieSeasonStat.objects.filter(player=p, league__in=pro).values_list('totals', flat=True))


def milestones(p, league: str, day: date, before: dict | None, lines: list, debut: bool) -> list:
    """그날 경기로 넘은 문턱을 기록한다(프로 통산). 기록 문장 목록."""
    from . import rookie as R
    from .rookie_league import add
    before = before or {}
    after = before
    for line in lines:
        after = add(after, line)
    texts = []
    if debut and before.get('g', 0) > 0:            # 프로 데뷔는 아래 '경기 1' 이 맡는다 — 여기는 새 리그 데뷔
        texts.append(f"{W.league(league)['name']} 데뷔전")
    for key, marks, unit in MILESTONES[p.role]:
        lo, hi = before.get(key, 0), after.get(key, 0)
        for m in marks:
            if lo < m <= hi:
                texts.append(FIRST[key] if m == 1 and key in FIRST else f'프로 통산 {m:,}{unit}')
    for t in texts:
        R._log(p, 'mile', f"{t} — {W.club_label(league, p.club)}", day=day)
    return texts


def lifetime(player) -> dict:
    """선수 페이지 '통산 성적' — 리그별 합계(높은 리그 먼저)·프로 통산·평생 통산."""
    from .models import RookieSeasonStat
    from .rookie_league import line_view
    rows = list(RookieSeasonStat.objects.filter(player=player).select_related('season'))
    by = {}
    for r in rows:
        by.setdefault(r.league, []).append(r)
    out = []
    for code in sorted(by, key=lambda c: -W.level(c)):
        t = _sum(r.totals for r in by[code])
        out.append({'league': code, 'label': W.short(code), 'name': W.league(code)['name'],
                    'seasons': len({r.season_id for r in by[code]}), 'v': line_view(player.role, t),
                    'war': round(sum(r.war for r in by[code]), 1), 'pro': W.is_pro(code)})
    pro_rows = [r for r in rows if W.is_pro(r.league)]
    pro = _sum(r.totals for r in pro_rows)
    every = _sum(r.totals for r in rows)
    return {'leagues': out,
            'pro': {'v': line_view(player.role, pro), 'war': round(sum(r.war for r in pro_rows), 1),
                    'seasons': len({r.season_id for r in pro_rows})} if pro_rows else None,
            'all': {'v': line_view(player.role, every), 'war': round(sum(r.war for r in rows), 1),
                    'seasons': len({r.season_id for r in rows})} if rows else None}


# ───────────────────────────── 오늘의 베스트 9
def _bat_score(t: dict) -> float:
    from .rookie_league import batting
    b = batting(t)
    return (b['tb'] + t.get('bb', 0) + t.get('hbp', 0) + 1.5 * t.get('sb', 0) + t.get('rbi', 0) + t.get('r', 0)
            - 0.3 * t.get('so', 0) - t.get('cs', 0))


def game_score(t: dict) -> float:
    """빌 제임스 게임 스코어 — 50 + 아웃 + 5회 뒤 이닝마다 2 + 삼진 − 안타 2 − 자책 4 − 비자책 2 − 볼넷."""
    outs = t.get('outs', 0)
    return (50 + outs + 2 * max(0, outs // 3 - 4) + t.get('so', 0) - 2 * t.get('h', 0) - 4 * t.get('er', 0)
            - 2 * (t.get('r', 0) - t.get('er', 0)) - t.get('bb', 0))


def best_nine(day: date, league: str, *, hidden: bool = True) -> list:
    """[{pos, label, slot, p, value, score, rivals}] — 위치마다 그날 가장 잘한 선수(외야 셋). 없으면 빈 칸.
    rivals = 그 자리를 두고 겨룬 선수 수(혼자였으면 기록에 남기지 않는다)."""
    from .game_visibility import rookie_visible as visible
    from .models import RookieGame
    from .rookie_league import add, bat_summary, pit_summary
    qs = RookieGame.objects.filter(day=day, league=league).select_related('player', 'player__user')
    if hidden:
        qs = visible(qs, 'player__user')
    day_lines, best_pit = {}, {}
    for g in qs:
        p = g.player
        if p.role == 'pitcher':
            sc = game_score(g.line)
            if p.pk not in best_pit or sc > best_pit[p.pk][0]:
                best_pit[p.pk] = (sc, p, g)
        else:
            cur = day_lines.setdefault(p.pk, [p, {}])
            cur[1] = add(cur[1], g.line)
    out = []
    pit = sorted(best_pit.values(), key=lambda x: -x[0])
    if pit:
        sc, p, g = pit[0]
        out.append({'pos': 'SP', 'label': '투수', 'slot': '', 'p': p, 'score': round(sc, 1),
                    'value': pit_summary(g.line), 'team': g.line.get('club') or p.club, 'rivals': len(pit)})
    else:
        out.append({'pos': 'SP', 'label': '투수', 'slot': '', 'p': None})
    bats = [(round(_bat_score(t), 1), p, t) for p, t in day_lines.values() if t.get('pa', 0)]
    for pos, label in NINE[1:]:
        pool = sorted([x for x in bats if x[1].position == pos], key=lambda x: -x[0])
        n = 3 if pos == 'OF' else 1
        for i in range(n):
            if i < len(pool):
                sc, p, t = pool[i]
                out.append({'pos': pos, 'label': label, 'slot': str(i + 1) if pos == 'OF' else '', 'p': p, 'score': sc,
                            'value': bat_summary(t), 'team': p.club, 'rivals': len(pool) - (n - 1)})
            elif pos != 'OF' or i == 0:
                out.append({'pos': pos, 'label': label, 'slot': '2' if pos == 'OF' else '', 'p': None})
    return out


def latest_day(league: str) -> date | None:
    from .models import RookieGame
    return RookieGame.objects.filter(league=league).order_by('-day').values_list('day', flat=True).first()


def after_day(season, day: date) -> int:
    """경기일 정산 뒤 — 리그마다 오늘의 베스트 9 에 든 선수에게 기록을 남긴다(운영자 제외).
    그 자리를 두고 겨룬 선수가 없었으면(혼자 뛴 자리) 남기지 않는다 — 회원이 적은 리그에서 매일 쌓이지 않게."""
    from . import rookie as R
    from .models import RookieGame
    n = 0
    for code in set(RookieGame.objects.filter(day=day).values_list('league', flat=True)):
        for x in best_nine(day, code):
            if x.get('p') and x['rivals'] >= 2:
                R._log(x['p'], 'mile', f"{day.month}월 {day.day}일 오늘의 베스트 9 — {W.short(code)} {x['label']} ({x['value']})",
                       day=day)
                n += 1
    return n


# ───────────────────────────── 리그별 통산 순위·명예의 전당
def league_career(league: str, *, retired_only: bool = False, limit: int = 30, version=None) -> list:
    """그 리그에서 쌓은 통산(선수별) — MVP 수 → 최고 OVR → 수상 수 → 통산 WAR 순."""
    from .game_visibility import rookie_visible as visible
    from .models import RookieAward, RookieSeasonStat
    from .rookie_league import line_view, season_games
    qs = visible(RookieSeasonStat.objects.filter(league=league, player__isnull=False), 'user') \
        .select_related('player')
    if retired_only:
        qs = qs.filter(player__retired_at__isnull=False)
    if version is not None:
        from .rookie_versions import filter_by_version
        qs = filter_by_version(qs, version, 'player__career')
    acc = {}
    for r in qs:
        a = acc.setdefault(r.player_id, {'p': r.player, 'rows': [], 'war': 0.0, 'best': 0.0, 'seasons': set()})
        a['rows'].append(r.totals)
        a['war'] += r.war
        a['best'] = max(a['best'], r.best_ovr or 0.0)
        a['seasons'].add(r.season_id)
    if not acc:
        return []
    awards = {}
    for pid, kind in RookieAward.objects.filter(league=league, player_id__in=list(acc)).values_list('player_id', 'kind'):
        a = awards.setdefault(pid, {'mvp': 0, 'n': 0})
        a['n'] += 1
        a['mvp'] += kind == 'mvp' or kind == 'minor'
    out = []
    half = season_games(league) // 2 if W.is_pro(league) else 10
    for pid, a in acc.items():
        t = _sum(a['rows'])
        aw = awards.get(pid, {'mvp': 0, 'n': 0})
        if retired_only and t.get('g', 0) < (HOF_GAMES if W.is_pro(league) else half) and not aw['n']:
            continue
        p = a['p']
        out.append({'p': p, 'v': line_view(p.role, t), 'war': round(a['war'], 1), 'best': round(a['best'], 1),
                    'mvp': aw['mvp'], 'awards': aw['n'], 'seasons': len(a['seasons']), 'team': p.club,
                    'age': (p.career or {}).get('retired', {}).get('age') or p.age})
    out.sort(key=lambda x: (x['mvp'], x['best'], x['awards'], x['war']), reverse=True)
    return out[:limit]


def recent_milestones(limit: int = 12) -> list:
    from .game_visibility import rookie_visible as visible
    from .models import RookieLog
    qs = visible(RookieLog.objects.filter(kind='mile').exclude(text__contains='베스트 9'), 'player__user')
    return list(qs.select_related('player')[:limit])
