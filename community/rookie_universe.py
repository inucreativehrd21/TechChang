"""개인 커리어 세계: 이어지는 경쟁자와 모든 구단이 함께 치르는 대진·승패.

대진은 재현 가능한 원형 편성, 결과는 현재 시즌만 JSON에 보관한다.
과거 시즌의 순위표는 LiteSeason.splits에 남기고 라이벌은 최대 9명을 기억한다.
"""
import random
from functools import lru_cache

from . import rookie_world as W


def year_of(p):
    return getattr(p, 'year', None) or getattr(p, 'age_season', 1) or 1


def coach(p):
    styles = [('development', '육성 중심', '함께 훈련하고 준비하는 답을 높이 평가해요.'),
              ('results', '성적 중심', '역할을 요구할 때 실력과 최근 결과를 더 엄격하게 봐요.'),
              ('team', '팀워크 중심', '공개 비난은 신뢰를 크게 잃고 동료를 돕는 행동을 반겨요.')]
    seed = sum(ord(c) for c in str(getattr(p, 'club', '')))
    k, label, text = styles[seed % len(styles)]
    return dict(kind=k, label=label, text=text)


def rivals(p, year=None):
    from . import rookie_story as S
    from . import rookie_lite as X
    year = year or year_of(p)
    data = S.state(p)
    pool = list(data.get('rivals') or [])
    if not pool:
        rng = random.Random(f'rivals:{getattr(p, "pk", 0)}:{getattr(p, "name", "선수")}')
        for i in range(3):
            name = X.rival_name(p.league, rng)
            while name in [r['name'] for r in pool] or name == getattr(p, 'name', ''):
                name = X.rival_name(p.league, rng)
            pool.append(dict(id=f'peer-{i}', name=name, league=p.league, club=p.club, age=getattr(p, 'age', 18) + i - 1,
                             ovr=round(p.ovr + rng.gauss(0, 3), 1), potential=rng.randint(63, 86), relation=50,
                             year=year, history=[f'시즌 {year}: 같은 무대에서 경쟁을 시작했어요.']))
    for r in pool:
        for turn in range(r['year'] + 1, year + 1):
            rng = random.Random(f'rival:{getattr(p, "pk", 0)}:{r["id"]}:{turn}')
            r['age'] += 1
            r['ovr'] = round(max(30, min(r['potential'], r['ovr'] + (1.5 if r['age'] <= 27 else -.7) + rng.gauss(0, 1.1))), 1)
            r['injured'] = rng.random() < .08
            if r['league'] in ('hs', 'univ') and r['age'] >= (19 if r['league'] == 'hs' else 23):
                r['league'] = 'kbo2' if r['ovr'] >= 52 else 'kbo3'
                r['club'] = rng.choice(W.KBO_TEAMS)[0]
                r['history'].append(f'시즌 {turn}: {W.club_label(r["league"], r["club"])}에 입단했어요.')
            elif W.is_pro(r['league']):
                nxt = W.next_league(r['league'])
                if nxt and r['ovr'] >= W.level(nxt) - 2 and not r['injured']:
                    r['league'] = nxt
                    r['history'].append(f'시즌 {turn}: {W.short(nxt)}로 올라갔어요.')
                if rng.random() < .07:
                    r['club'] = rng.choice(W.SYSTEM_TEAMS[W.system_of(r['league'])])[0]
                    r['history'].append(f'시즌 {turn}: {W.club_label(r["league"], r["club"])}로 이적했어요.')
            if r['injured']:
                r['history'].append(f'시즌 {turn}: 부상으로 기회를 놓쳤어요.')
        r['year'] = max(r['year'], year)
        r['history'] = r['history'][-6:]
    data['rivals'] = pool[-9:]
    S.put(p, data)
    return pool


def rival_report(p, league, kind):
    from . import rookie_story as S
    from . import rookie_lite as X
    from . import rookie_league as L
    pool = rivals(p)
    candidates = [r for r in pool if r['league'] == league and r['club'] == p.club]
    if not candidates:
        key = f'roster:{league}:{p.club}:{p.position}'
        found = next((r for r in pool if r['id'] == key), None)
        if found:
            candidates = [found]
        else:
            rng = random.Random(key)
            found = dict(id=key, name=X.rival_name(league, rng), league=league, club=p.club,
                         age=getattr(p, 'age', 24) + 2, ovr=round(W.level(league) + rng.gauss(1, 2), 1),
                         potential=84, relation=50, year=year_of(p), history=['같은 포지션의 출전 기회를 놓고 경쟁해요.'])
            data = S.state(p)
            data['rivals'] = (pool + [found])[-9:]
            S.put(p, data)
            candidates = [found]
    r = candidates[0 if kind == 'up' else -1]
    z = max(-2, min(2, (r['ovr'] - W.level(league)) / 7)) - (.9 if r.get('injured') else 0)
    pos = L.POS_LABEL.get(p.position, '야수') if p.role == 'batter' else '투수'
    line = (f'타율 {L.rate(max(.160, min(.370, .252 + z * .027)))} · OPS {L.rate(.720 + z * .075)}'
            if p.role == 'batter' else f'평균자책점 {max(.8, 4.40 - z * .9):.2f}')
    return dict(id=r['id'], name=r['name'], pos=pos, line=line, z=round(z, 2), league=W.short(league),
                relation=r['relation'], history=r['history'][-2:])


def remember(p, rival_id, choice, text):
    from . import rookie_story as S
    data = S.state(p)
    for r in data.get('rivals') or []:
        if r['id'] == rival_id:
            shift = 8 if choice in ('accept', 'modest', 'together') else -7 if choice in ('argue', 'trade', 'blame') else -2
            r['relation'] = max(0, min(100, r['relation'] + shift))
            r['history'] = (r['history'] + [f'시즌 {year_of(p)}: {text[:90]}'])[-6:]
            break
    S.put(p, data)


def view(p):
    if not getattr(p, 'pk', None) or not hasattr(p, 'club'):
        return None
    pool = rivals(p)
    return dict(coach=coach(p), rivals=[dict(r, club_label=W.club_label(r['league'], r['club']),
                   league_label=W.short(r['league']), ahead=r['ovr'] > p.ovr) for r in pool[-5:]])


def teams(league):
    out = [c for c, _name, _col in W.SYSTEM_TEAMS.get(W.system_of(league), [])]
    if league == 'kbo2':
        out.append('국군체육부대(상무)')
    return out


@lru_cache(maxsize=48)
def schedule(league, games):
    """각 팀 G경기. 홀수 팀도 휴식일을 포함하며 홈/원정과 대진을 공유한다."""
    clubs = teams(league)
    n = len(clubs)
    if n < 2:
        return (), ()
    ring = list(range(n)) + ([None] if n % 2 else [])
    base = []
    for day in range(len(ring) - 1):
        pairs = [(ring[i], ring[-i - 1]) if day % 2 == 0 else (ring[-i - 1], ring[i]) for i in range(len(ring) // 2)]
        base.append(tuple((a, b) for a, b in pairs if a is not None and b is not None))
        ring = [ring[0], ring[-1]] + ring[1:-1]
    rounds = []
    cycles, rest = divmod(games, n - 1)
    for cycle in range(cycles):
        rounds.extend(tuple((b, a) if cycle % 2 else (a, b) for a, b in pairs) for pairs in base)
    if n % 2 == 0:
        rounds.extend(base[:rest])
    elif rest:
        if rest % 2:
            raise ValueError('홀수 구단 리그는 짝수 경기 수가 필요해요.')
        # 원형 간격 k마다 모든 팀이 두 경기씩: 부분 시즌도 모든 팀 경기 수를 맞춘다.
        for stride in range(1, rest // 2 + 1):
            pending = [(i, (i + stride) % n) for i in range(n)]
            while pending:
                used, day, left = set(), [], []
                for a, b in pending:
                    if a in used or b in used:
                        left.append((a, b))
                    else:
                        used.update((a, b))
                        day.append((a, b))
                rounds.append(tuple(day))
                pending = left
    return tuple(clubs), tuple(rounds)


@lru_cache(maxsize=120)
def club_fixtures(league, games, club):
    clubs, rounds = schedule(league, games)
    if club not in clubs:
        return ()
    idx = clubs.index(club)
    return tuple(dict(day=d, match=m, opponent=clubs[b if a == idx else a], home=a == idx)
                 for d, pairs in enumerate(rounds) for m, (a, b) in enumerate(pairs) if idx in (a, b))


def world_state(p, year):
    from . import rookie_story as S
    data = S.state(p)
    world = data.get('career_universe') or {}
    if world.get('year') != year:
        world = {'year': year, 'leagues': {}}
    data['career_universe'] = world
    S.put(p, data)
    return world


def advance(p, year, league, games, through=None, overrides=None):
    """한 경기 결과는 상대 승패와 같은 점수를 쓴다. 개인 경기 결과도 해당 대진에 넣는다."""
    from . import rookie_sim as M
    clubs, rounds = schedule(league, games)
    if not clubs:
        return None
    world = world_state(p, year)
    state = world['leagues'].setdefault(league, {'games': games, 'scores': []})
    scores = state['scores']
    through = min(len(rounds), through if through is not None else len(rounds))
    own = overrides or {}
    # 구단 전력은 커리어 내에서 이어지고, 시즌 변동은 작게 둔다.
    powers = {c: random.Random(f'club:{getattr(p, "pk", 0)}:{c}').gauss(0, .16)
              + random.Random(f'form:{c}:{year}').gauss(0, .035) for c in clubs}
    for day in range(through):
        if day >= len(scores):
            rng = random.Random(f'league:{getattr(p, "pk", 0)}:{year}:{league}:{day}')
            row = []
            for a, b in rounds[day]:
                h = M._poisson(4.1 * max(.65, 1 + powers[clubs[a]] - powers[clubs[b]] + .035), rng)
                v = M._poisson(4.1 * max(.65, 1 + powers[clubs[b]] - powers[clubs[a]]), rng)
                if h == v and (W.system_of(league) not in ('kbo', 'npb') or rng.random() > .18):
                    if rng.random() < .5:
                        h += 1
                    else:
                        v += 1
                row.append([h, v])
            scores.append(row)
        patch = own.get(str(day)) or own.get(day)
        if patch and patch['club'] in clubs:
            idx = clubs.index(patch['club'])
            for match, (a, b) in enumerate(rounds[day]):
                if idx in (a, b):
                    scores[day][match] = ([patch['for'], patch['against']] if a == idx
                                           else [patch['against'], patch['for']])
    return table(p, year, league, games, through)


def table(p, year, league, games, through=None):
    clubs, rounds = schedule(league, games)
    world = world_state(p, year)
    state = world['leagues'].get(league)
    if not state:
        return None
    scores = state['scores'][:through]
    rows = [dict(club=c, name=W.club_label(league, c), w=0, l=0, d=0, rf=0, ra=0, g=0) for c in clubs]
    for day, results in enumerate(scores):
        for (a, b), (h, v) in zip(rounds[day], results):
            home, away = rows[a], rows[b]
            home['g'] += 1
            away['g'] += 1
            home['rf'] += h
            home['ra'] += v
            away['rf'] += v
            away['ra'] += h
            home['w'] += h > v
            home['l'] += h < v
            away['w'] += v > h
            away['l'] += v < h
            home['d'] += h == v
            away['d'] += h == v
    for r in rows:
        r['pct'] = r['w'] / max(1, r['w'] + r['l'])
    rows.sort(key=lambda r: (-r['pct'], -(r['rf'] - r['ra']), r['club']))
    for i, r in enumerate(rows):
        r['rank'] = i + 1
        r['pct_text'] = f'{r["pct"]:.3f}'
        r['mine'] = r['club'] == p.club and p.league == league
    return dict(league=league, label=W.league(league)['name'], year=year, rows=rows,
                played=len(scores), rounds=len(rounds), games=games,
                mine=next((r for r in rows if r['club'] == p.club), None))


def current_table(p):
    from . import rookie_story as S
    world = S.state(p).get('career_universe') or {}
    league = (world.get('leagues') or {}).get(p.league)
    return table(p, world['year'], p.league, league['games']) if league else None


def kbo_final(p, standings):
    """4위 1승 우위 WC → 준PO/PO 3선승. 1위는 한국시리즈 직행."""
    if not standings or standings['league'] != 'kbo1':
        return None, []
    top = standings['rows'][:5]
    rng = random.Random(f'kbo-post:{p.pk}:{standings["year"]}')
    news = []
    def series(a, b, need, first=0, label=''):
        wins = [first, 0]
        chance = max(.3, min(.7, .53 + (a['pct'] - b['pct']) * .8))
        while max(wins) < need:
            wins[0 if rng.random() < chance else 1] += 1
        winner = a if wins[0] == need else b
        news.append(f'{label}: {a["name"]} {wins[0]}:{wins[1]} {b["name"]} — {winner["name"]} 진출')
        return winner
    wc = series(top[3], top[4], 2, 1, '와일드카드')
    semi = series(top[2], wc, 3, label='준플레이오프')
    final = series(top[1], semi, 3, label='플레이오프')
    if p.club in (top[0]['club'], final['club']):
        return (final if p.club == top[0]['club'] else top[0]), news
    return None, news
