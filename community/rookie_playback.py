"""정식 판 경기 재생 — 저장된 박스스코어(RookieGame) 한 판을 이닝마다 한 줄씩 넘어가는 중계로 만든다
(2026-10-25 사용자 요청: 라이트·익스트림 시즌 전광판처럼 매 경기 재생).

경기 엔진·난수 순서는 건드리지 않는다. 결과는 이미 정해져 있고, 이 모듈은 그 결과에 맞는 흐름만 만든다
(rookie_series 와 같은 원칙). 경기마다 파생 난수(경기 pk)를 써서 언제 다시 봐도 같은 중계다.
지키는 것:
- 이닝 점수 합 = 팀 점수. 홈 팀이 이기면 9회말이 없거나(X) 끝내기(rookie_series.linescore).
- 타자: 타석 결과 수 = 박스스코어(안타·2루타·3루타·홈런·볼넷·사구·삼진·범타·희생플라이), 회원 맞대결 타석은 실제 결과 그대로.
  타점·득점을 낸 이닝엔 우리 점수가 그만큼 있다(모자라면 다른 이닝 점수를 옮긴다).
- 투수: 내가 던진 이닝의 상대 점수 = 내 실점, 나머지 상대 점수는 내가 내려간 뒤 이닝에.
"""
from __future__ import annotations

import random

from . import rookie_league as L
from . import rookie_series as Series
from . import rookie_world as W
from .rookie_text import josa

BAT_TEXT = {
    '1B': ('좌전 안타', '중전 안타', '우전 안타', '내야 안타', '유격수 키를 넘기는 안타'),
    '2B': ('좌중간 2루타', '우중간 2루타', '좌익선상 2루타', '우익선상 2루타'),
    '3B': ('우중간 3루타', '좌중간을 가르는 3루타'),
    'HR': ('좌월 홈런', '중월 홈런', '우월 홈런', '담장을 훌쩍 넘기는 홈런'),
    'BB': ('볼넷', '풀카운트 끝에 볼넷'), 'HBP': ('몸에 맞는 공',),
    'SO': ('헛스윙 삼진', '루킹 삼진', '파울 끝에 헛스윙 삼진'),
    'OUT': ('유격수 땅볼', '2루수 땅볼', '중견수 뜬공', '좌익수 뜬공', '우익수 뜬공', '3루수 직선타', '1루수 파울 뜬공'),
    'SF': ('희생플라이',),
}
ORDINAL = ('첫', '두 번째', '세 번째', '네 번째', '다섯 번째', '여섯 번째')
PA_PER_INNING = 4.2                   # 한 이닝에 타석에 서는 타자 수(평균) — 타순으로 몇 회에 나오는지 잡는다


def _n(x) -> int:
    return x if isinstance(x, int) else 0


def _move(line: list, need: dict, fixed: set, rng) -> list:
    """이닝마다 최소 점수(need)를 맞춘다 — 합은 그대로, 모자란 이닝엔 다른 이닝 점수를 옮긴다(fixed 이닝은 손대지 않음)."""
    line = list(line)
    for i, want in sorted(need.items()):
        while _n(line[i]) < want:
            donors = [j for j, v in enumerate(line) if j not in fixed and j != i and _n(v) > need.get(j, 0)]
            if not donors:
                break
            j = rng.choice(donors)
            line[j] -= 1
            line[i] = _n(line[i]) + 1
    return line


def _innings_of(n: int, bslot: int, last: int, rng) -> list:
    """타순 bslot 타자의 k번째 타석이 몇 회(0부터)였나 — 같은 이닝 두 번은 드물게."""
    out = []
    for k in range(n):
        at = int(((bslot - 1) + 9 * k + rng.random() * 2) / PA_PER_INNING)
        at = max(at, out[-1] + 1 if out and rng.random() < .9 else (out[-1] if out else 0))
        out.append(min(last, at))
    return out


def _batter_events(g, line: dict, us_line: list, home_us: bool, rng, names: dict) -> tuple:
    """타자 — {이닝: [문장]}, 이닝별 필요 득점, 하이라이트 이닝."""
    last = 7 if (home_us and us_line[8] == 'X') else 8
    events, need, hot = {}, {}, set()
    if line.get('ph') or line.get('pr') or line.get('dr'):
        at = rng.choice([6, 7, last]) if last >= 7 else last
        if line.get('ph'):
            o = next((k for k in ('HR', '3B', '2B', '1B', 'BB', 'HBP', 'SO') if _count(line, k)), 'OUT')
            text = f"대타 — {rng.choice(BAT_TEXT[o])}" + (f", {line['rbi']}타점" if line.get('rbi') else '')
            hot |= {at} if o in ('HR', '3B', '2B', '1B') else set()
        elif line.get('pr'):
            text = '대주자 투입' + (' — 도루 성공' if line.get('sb') else '') + (', 홈을 밟았어요' if line.get('r') else '')
        else:
            text = '대수비로 들어갔어요' + (' — 실책 1' if line.get('e') else '')
        events[at] = [text]
        if line.get('rbi') or line.get('r'):
            need[at] = max(line.get('rbi', 0), line.get('r', 0))
        return events, need, hot
    pool = []
    for k in ('HR', '3B', '2B', '1B', 'BB', 'HBP', 'SO', 'SF', 'OUT'):
        pool += [k] * _count(line, k)
    duels = []
    for d in line.get('member_duels') or []:                  # 회원 맞대결 타석 — 앞 타석부터, 실제 결과 그대로
        o = d.get('outcome')
        if o in pool:
            pool.remove(o)
            duels.append((o, names.get((d.get('opponent') or {}).get('id'))))
    rng.shuffle(pool)
    seq = duels + [(o, None) for o in pool]
    innings = _innings_of(len(seq), int(line.get('bslot') or 7), last, rng)
    rbi_left, runs_left, sb_left = line.get('rbi', 0), max(0, line.get('r', 0) - line.get('hr', 0)), line.get('sb', 0)
    rbis = [0] * len(seq)
    for i, (o, _w) in enumerate(seq):                         # 홈런은 자기 자신 1타점부터, 희생플라이는 1타점
        if o in ('HR', 'SF') and rbi_left:
            rbis[i] += 1
            rbi_left -= 1
    order = [i for i, (o, _w) in enumerate(seq) if o in ('HR', '3B', '2B', '1B')] or \
            [i for i, (o, _w) in enumerate(seq) if o in ('BB', 'HBP', 'OUT')]
    while rbi_left and order:
        i = rng.choice(order)
        if rbis[i] < (4 if seq[i][0] == 'HR' else 3):
            rbis[i] += 1
            rbi_left -= 1
        elif all(rbis[j] >= (4 if seq[j][0] == 'HR' else 3) for j in order):
            break
    on_base = [i for i, (o, _w) in enumerate(seq) if o in ('1B', '2B', '3B', 'BB', 'HBP')]
    scored = set(rng.sample(on_base, min(runs_left, len(on_base))))
    stole = set(i for i in on_base if seq[i][0] in ('1B', 'BB', 'HBP'))
    stole = set(sorted(stole, key=lambda _x: rng.random())[:sb_left])
    for i, (o, who) in enumerate(seq):
        inn = innings[i]
        text = f"{ORDINAL[min(i, len(ORDINAL) - 1)]} 타석 — {rng.choice(BAT_TEXT[o])}"
        if who:
            text = f"{who} 선수와 맞대결 — {rng.choice(BAT_TEXT[o])}"
        if rbis[i] and o != 'HR':
            text += f", {rbis[i]}타점"
        elif o == 'HR':
            text += {1: ' (솔로)', 2: ' (투런)', 3: ' (스리런)', 4: ' (만루 홈런)'}.get(rbis[i] or 1, '')
        if i in stole:
            text += ' · 도루 성공'
        if i in scored:
            text += ' · 홈인'
        events.setdefault(inn, []).append(text)
        need[inn] = need.get(inn, 0) + rbis[i] + (1 if i in scored else 0)
        if o in ('HR', '3B', '2B') or rbis[i] >= 2:
            hot.add(inn)
    return events, need, hot


def _count(line: dict, k: str) -> int:
    h, d, t, hr = (line.get(x, 0) for x in ('h', 'd', 't', 'hr'))
    return {'HR': hr, '3B': t, '2B': d, '1B': max(0, h - d - t - hr), 'BB': line.get('bb', 0),
            'HBP': line.get('hbp', 0), 'SO': line.get('so', 0), 'SF': line.get('sf', 0),
            'OUT': max(0, line.get('ab', 0) - h - line.get('so', 0))}.get(k, 0)


def _spread_counts(total: int, slots: list, rng, weights=None) -> dict:
    out = {i: 0 for i in slots}
    for _ in range(max(0, total)):
        if not slots:
            break
        out[rng.choices(slots, weights)[0] if weights else rng.choice(slots)] += 1
    return out


def _pitcher_events(g, line: dict, them_line: list, home_us: bool, rng) -> tuple:
    """투수 — 내가 던진 이닝과 그 이닝의 상대 점수(= 내 실점). {이닝: [문장]}, 바뀐 상대 이닝 점수, 하이라이트."""
    outs = int(line.get('outs', 0))
    full, part = divmod(outs, 3)
    span = max(1, full + (1 if part else 0))
    first = 0 if line.get('gs') else max(0, 9 - span)
    mine = list(range(first, min(9, first + span)))
    runs = int(line.get('r', 0))
    them = sum(_n(v) for v in them_line)
    ninth_fixed = 8 if (not home_us and them_line[8] == 'X' and 8 not in mine) else None
    per = _spread_counts(runs, mine, rng)
    # 나머지 상대 점수는 내가 온전히 던진 이닝 밖에(선발이면 내려간 뒤, 구원이면 올라오기 전) — 마지막 걸친 이닝은 함께 써도 된다
    rest_slots = [i for i in range(9) if i not in mine[:full] and i != ninth_fixed]
    if not rest_slots and them - runs > 0 and ninth_fixed is not None:
        ninth_fixed, rest_slots = None, [8]             # 8이닝을 다 던졌는데 상대 점수가 남았다 — 9회말 끝내기로
    if not rest_slots:
        rest_slots = [mine[-1]]
    rest = _spread_counts(them - runs, rest_slots, rng)
    new = [0] * 9
    for i in range(9):
        new[i] = per.get(i, 0) + rest.get(i, 0)
    if ninth_fixed is not None:
        new[8] = 'X'
    hrs = _spread_counts(int(line.get('hr', 0)), [i for i in mine if per[i]] or mine, rng)
    hits = _spread_counts(max(0, int(line.get('h', 0)) - int(line.get('hr', 0))), mine, rng, [1 + 2 * per[i] for i in mine])
    walks = _spread_counts(int(line.get('bb', 0)) + int(line.get('hbp', 0)), mine, rng)
    ks = _spread_counts(int(line.get('so', 0)), mine, rng)
    events, hot = {}, set()
    for k, i in enumerate(mine):
        h, b, so, r = hits[i] + hrs.get(i, 0), walks[i], ks[i], per[i]
        if not (h or b or r):
            text = '삼자범퇴' + (f', {so}탈삼진' if so else '')
        else:
            parts = [f'{h}피안타' if h else '', f'{b}볼넷' if b else '', f'{so}탈삼진' if so else '']
            text = ' '.join(x for x in parts if x) + (f' · 피홈런 {hrs[i]}' if hrs.get(i) else '') + (f' · {r}실점' if r else ' · 무실점')
        if k == len(mine) - 1 and part:
            text += f' — {part}아웃 잡고 교체'
        elif k == 0 and not line.get('gs'):
            text = '마운드에 올랐어요 · ' + text
        events[i] = [text]
        if so >= 2 and not r:
            hot.add(i)
    if line.get('gs') and full >= 6 and runs <= 3:
        hot.add(mine[-1])
    return events, new, hot


def build(g, role: str, names: dict | None = None) -> dict:
    """경기 한 판의 중계 — rows(이닝마다 한 줄)·머리말·마무리 문장."""
    rng = random.Random(f'replay:{g.pk}')
    line = g.line or {}
    home_us = bool(g.home)
    us, them = int(g.team_runs), int(g.opp_runs)
    ls = Series.linescore(us, them, 'us' if home_us else 'them', rng)
    us_line, them_line = list(ls['us']), list(ls['them'])
    if role == 'batter':
        events, need, hot = _batter_events(g, line, us_line, home_us, rng, names or {})
        total_need = sum(need.values())
        while total_need > us and need:                     # 득점 표시가 팀 점수를 넘으면 큰 이닝부터 줄인다
            k = max(need, key=need.get)
            need[k] -= 1
            total_need -= 1
        us_line = _move(us_line, need, {8} if home_us else set(), rng)     # 홈 9회말(끝내기·X)은 그대로
    else:
        events, them_line, hot = _pitcher_events(g, line, them_line, home_us, rng)
    rows, a, b = [], 0, 0
    ours, theirs = ('말', '초') if home_us else ('초', '말')     # 우리 공격은 홈이면 말, 원정이면 초
    for i in range(9):
        a += _n(us_line[i])
        b += _n(them_line[i])
        mine = events.get(i)
        if mine:
            half = ours if role == 'batter' else theirs
            text = ' / '.join(mine)
        else:
            half = ''
            gain = [f'우리 {_n(us_line[i])}점' if _n(us_line[i]) else '', f'상대 {_n(them_line[i])}점' if _n(them_line[i]) else '']
            text = ' · '.join(x for x in gain if x) or ('9회말 공격 없이 경기 끝' if 'X' in (us_line[i], them_line[i]) else '득점 없이 넘어갔어요')
        rows.append({'label': f'{i + 1}회{half}', 'text': text, 'score': f'{a} : {b}', 'mine': bool(mine), 'hot': i in hot})
    won = us > them
    opp = W.club_label(g.league, g.opponent) if g.opponent else '상대'
    walkoff = ls.get('walkoff') and won and home_us
    result = ('끝내기 승리' if walkoff else '승리') if won else ('패배' if us < them else '무승부')
    summary = L.bat_summary(line) if role == 'batter' else (g.summary or L.pit_summary(line))
    return {
        'id': g.pk, 'at': line.get('at', ''), 'day': g.day, 'no': g.no, 'home': home_us,
        'opponent': opp, 'vs': f"{opp}{josa(opp, '와/과')} {'홈' if home_us else '원정'} 경기",
        'us_line': [x if x == 'X' else _n(x) for x in us_line], 'them_line': [x if x == 'X' else _n(x) for x in them_line],
        'us': us, 'them': them, 'score': f'{us} : {them}', 'won': won, 'result': result, 'summary': summary, 'rows': rows,
        'final': f"{opp}에 {us} : {them} {result} · {summary}",
    }


def names_for(games) -> dict:
    """재생에 쓸 회원 맞대결 상대 이름 — 지금 공개된 선수만(rookie_matchups.view 와 같은 규칙)."""
    from .game_visibility import rookie_visible
    from .models import RookiePlayer
    ids = {(d.get('opponent') or {}).get('id') for g in games for d in (g.line or {}).get('member_duels') or []}
    ids.discard(None)
    if not ids:
        return {}
    return dict(rookie_visible(RookiePlayer.objects.filter(pk__in=ids), 'user').values_list('pk', 'name'))


def day_games(p, day=None) -> list:
    """그날(없으면 가장 최근 경기일) 내 경기들 — 시각 순."""
    qs = p.games.all()
    if day is None:
        last = qs.order_by('-day').values_list('day', flat=True).first()
        if last is None:
            return []
        day = last
    return list(qs.filter(day=day).order_by('no'))


# ───────────────────────────── 경기장 칸(내 선수 화면 맨 위)
RACE_ROWS = 6                         # 순위 레이스는 위에서 몇 구단 + 내 구단 둘레만(MLB 30구단)


def _race(p, now=None) -> dict | None:
    """내 구단 순위·게임차·남은 경기 — 개인 세계 순위표(rookie_universe). 전·후기 리그면 지금 반기 순위."""
    from . import rookie_universe as Universe
    from . import rookie_matchday_presentation as UI
    from .rookie_clock import HALF_LABEL
    from django.utils import timezone
    from . import rookie_clock as Clock
    halves = Universe.half_tables(p)
    half = (Clock.half_of(timezone.localdate(now)) or halves['half']) if halves else None
    if halves:
        table = halves['second'] if half == 2 else halves['first']
        games = halves['per']
    else:
        table = Universe.current_table(p)
        games = table['games'] if table else 0
    if not table or not table.get('rows'):
        return None
    rows, top = table['rows'], table['rows'][0]
    for r in rows:
        gb = ((top['w'] - r['w']) + (r['l'] - top['l'])) / 2
        r['gb'] = '—' if gb <= 0 else (f'{gb:.1f}'.rstrip('0').rstrip('.'))
        r['left'] = max(0, games - r['g'])
    mine = table.get('mine')
    show = rows[:RACE_ROWS]
    if mine and mine not in show:
        i = rows.index(mine)
        show = rows[:RACE_ROWS - 3] + rows[max(RACE_ROWS - 3, i - 1):i + 2]
    return dict(label=f"{table['label']} · {HALF_LABEL[half]}" if half else table['label'], rows=show, mine=mine,
                teams=len(rows), played=mine['g'] if mine else 0, games=games, half=half,
                final=halves['final'] if halves else '',
                first_champ=halves['first_champ'] if halves else None,
                second_champ=halves['second_champ'] if halves else None,
                views=UI.race_views(halves, Universe.current_table(p)))


def _today_plan(p, now) -> list:
    """오늘 내 구단 경기 — 시각·상태(끝남/예정)·점수. 투수 선발이면 선발 경기 표시."""
    from django.utils import timezone
    from . import rookie_clock as Clock
    today = timezone.localdate(now)
    played = {g.no: g for g in p.games.filter(day=today)}
    plan = Clock.club_games_on(p.league, p.club, today)
    start = Clock.start_no(p.pk, p.league, p.club, today) if p.role == 'pitcher' and p.lineup == 'sp' else None
    out = []
    for slot, no, fixture in plan:
        g = played.get(no)
        at = Clock.slot_at(today, slot)
        opp = W.club_label(p.league, fixture['opponent']) if fixture else ''
        out.append({'label': Clock.label(slot), 'no': no, 'opp': opp, 'home': fixture['home'] if fixture else None,
                    'done': at <= now, 'game': g.pk if g else None,
                    'score': f'{g.team_runs} : {g.opp_runs}' if g else '',
                    'won': bool(g and g.team_runs > g.opp_runs), 'start': no == start})
    return out


def stadium(p, now=None) -> dict | None:
    """경기장 칸 — 경기 재생(오늘 또는 가장 최근 경기일) · 오늘 경기 · 다음 경기 · 순위 레이스.
    스위치(ROOKIE_FULL_SLOTS)가 꺼져 있으면 None — 화면은 예전 그대로."""
    from django.utils import timezone
    from . import rookie_clock as Clock
    if not Clock.enabled() or p.retired_at:
        return None
    now = now or timezone.now()
    today = timezone.localdate(now)
    slots = Clock.active_on(today)
    games = day_games(p)
    names = names_for(games)
    replays = [build(g, p.role, names) for g in games]
    seen = int((p.career or {}).get('replay_seen') or 0)
    fresh = [r for r in replays if r['id'] > seen]
    nxt = Clock.next_game(p.league, p.club, now) if slots else None
    if nxt:
        f = nxt['fixture']
        nxt['opp'] = W.club_label(p.league, f['opponent']) if f else ''
        nxt['home'] = f['home'] if f else None
        nxt['today'] = nxt['day'] == today
        if p.role == 'pitcher' and p.lineup == 'sp':
            start = Clock.start_no(p.pk, p.league, p.club, nxt['day'])
            nxt['start_at'] = next((Clock.label(s) for s, n, _f in Clock.club_games_on(p.league, p.club, nxt['day'])
                                    if n == start), '')
    from .rookie_halves import post_view
    from . import rookie_matchday_presentation as UI
    cal = UI.calendar(now)
    post = UI.post(post_view(p, now), now)         # 공개된 기록에 표시용 상태만 더해요.
    if post and post['featured'] and post['next']:
        at = post['next']['at']
        nxt = dict(post['next'], day=timezone.localdate(at), today=timezone.localdate(at) == today,
                   label=timezone.localtime(at).strftime('%H:%M'), home=None,
                   opp=post['opponent']['name'] if post['mine'] else f"{post['team']['short']} 대 {post['opponent']['short']}", postseason=True)
    refresh = int(nxt['at'].timestamp() * 1000) + 90_000 if nxt and nxt['today'] else None
    if post and post['refresh_at'] and (refresh is None or post['refresh_at'] < refresh):
        refresh = post['refresh_at']
    return {
        'post': post,
        'calendar': cal, 'sky': UI.sky(now, cal), 'now_ms': int(now.timestamp()*1000),
        'slots': slots, 'replays': replays, 'games_day': games[0].day if games else None,
        'is_today': bool(games and games[0].day == today),
        'auto': fresh[-1]['id'] if fresh else None, 'shown': (fresh[-1] if fresh else replays[-1])['id'] if replays else None,
        'today': _today_plan(p, now) if slots else [], 'next': nxt, 'race': _race(p, now),
        'refresh_at': refresh,
        'slot_labels': [Clock.label(i) for i in range(len(Clock.SLOTS))],
    }


def mark_seen(p, view: dict | None) -> bool:
    """가장 최근 재생을 본 것으로 — 새로고침하면 처음부터 다시 돌지 않게(다른 경기는 눌러서 다시 볼 수 있다).
    잠근 최신 행에 이 키 하나만 쓴다 — 그사이 시간대 경기가 저장한 career(순위표 등)를 덮지 않게."""
    from django.db import transaction
    from .models import RookiePlayer
    if not view or not view['replays']:
        return False
    top = max(r['id'] for r in view['replays'])
    if top <= int((p.career or {}).get('replay_seen') or 0):
        return False
    with transaction.atomic():
        q = RookiePlayer.objects.select_for_update().get(pk=p.pk)
        q.career = dict(q.career or {}, replay_seen=top)
        q.save(update_fields=['career'])
    p.career = q.career
    return True
