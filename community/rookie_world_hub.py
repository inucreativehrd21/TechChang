"""선수 소속과 무관하게 진행되는 커리어 세계. 가상 선수 기록과 회원 DB 기록을 구분해요.

시계·시드·저장된 구단 점수로 재생하므로 조회가 경기 진행이나 기존 선수 상태를 바꾸지 않아요.
구단 박스스코어는 같은 점수에서 배분해 타자 득점 합계·상대 투수 실점 합계를 맞춰요.
"""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import random
from types import SimpleNamespace

from django.urls import reverse
from django.utils import timezone

from . import rookie_league as L
from . import rookie_sim as M
from . import rookie_universe as U
from . import rookie_world as W

SURNAMES = ('김', '이', '박', '최', '정', '강', '조', '윤', '장', '임', '한', '오', '서', '신', '권', '황')
GIVEN = ('민준', '서진', '지훈', '도윤', '현우', '정우', '시윤', '준서', '건우', '지호', '우진', '태윤', '재현', '승민', '도현', '유찬', '하준', '수현', '예준', '재윤')
POSITIONS = ('C', '1B', '2B', '3B', 'SS', 'OF', 'OF', 'OF', 'DH', 'OF', '2B', 'C')


def clock(player=None):
    """(시즌, 진행 비율, 설명). 모드·선수별 시계는 섞지 않아요."""
    if player is not None and hasattr(player, 'flags'):
        pending = player.pending or {}
        if pending.get('kind') == 'review':
            return pending.get('year', max(1, player.year - 1)), 1.0, '시즌 종료'
        if pending.get('half'):
            return player.year, .5, '전반기 종료'
        if pending.get('what') == 'moment' and pending.get('year'):
            return pending['year'], 1.0, '정규시즌 종료'
        world = (player.flags or {}).get('career_universe') or {}
        if world.get('year') == player.year and world.get('leagues'):
            fractions = [len(s['scores']) / max(1, len(U.schedule(code, s['games'])[1])) for code, s in world['leagues'].items()]
            return player.year, min(1, max(fractions)), '시즌 진행 중'
        return player.year, 0.0, '개막 준비'
    yesterday = timezone.localdate() - timedelta(days=1)
    season = L.season_no(yesterday)
    return max(1, season), L.games_through(yesterday) / L.SEASON_GAMES if season else 0, '어제 경기까지'


def world(player, league, year=None):
    current_year, fraction, label = clock(player)
    year = year if year and 1 <= year <= current_year else current_year
    if year < current_year:
        fraction, label = 1.0, '종료 시즌'
    lite = player is not None and hasattr(player, 'flags')
    from .rookie_lite import GAMES
    games = GAMES.get(league, 28) if lite else (L.SEASON_GAMES if W.is_pro(league) else L.SEASON_DAYS)
    clubs, schedule = U.schedule(league, games)
    if not clubs:
        return None
    clone = deepcopy(player) if player is not None else SimpleNamespace(pk=0, club='', league='', career={})
    source = clone.flags if lite else clone.career
    saved = source.get('career_universe') or {}
    if saved.get('year') != year:
        source['career_universe'] = {'year': year, 'leagues': {}}
    # 조회를 먼저 해도 미래의 내 경기 결과는 만들지 않고, 같은 시점까지만 보여 줘요.
    through = min(len(schedule), round(len(schedule) * fraction))
    table = U.advance(clone, year, league, games, through)
    state = (clone.flags if lite else clone.career)['career_universe']['leagues'][league]
    scores = state['scores'][:through]
    fixtures = []
    for day, row in enumerate(scores):
        for match, ((home, away), (h, a)) in enumerate(zip(schedule[day], row)):
            fixtures.append(dict(round=day + 1, match=match, home=clubs[home], away=clubs[away],
                                 home_name=W.club_short(league, clubs[home]), away_name=W.club_short(league, clubs[away]),
                                 h=h, a=a, key=f'{getattr(clone, "pk", 0)}:{year}:{league}:{day}:{match}'))
    return dict(table=table, fixtures=fixtures, clubs=clubs, league=league, year=year, current_year=current_year,
                label=label, played=through, fraction=fraction)


def _allocate(n, capacities, rng):
    slots = [i for i, capacity in enumerate(capacities) for _ in range(max(0, int(capacity)))]
    return Counter(rng.sample(slots, min(max(0, int(n)), len(slots))))


@lru_cache(maxsize=2048)
def _offense(key, runs):
    rng = random.Random('box:' + key)
    hits = max(runs, M._poisson(8, rng))
    bb = M._poisson(3, rng)
    # 타수를 타순대로 나누고, 모든 개인 기록은 같은 팀 점수에서 배분해요.
    abs_ = [0] * 9
    for i in range(27 + hits):
        abs_[i % 9] += 1
    hs = _allocate(hits, abs_, rng)
    hrs = _allocate(min(runs, M._poisson(.9, rng)), [hs[i] for i in range(9)], rng)
    doubles = _allocate(M._poisson(1.8, rng), [hs[i] - hrs[i] for i in range(9)], rng)
    triples = _allocate(int(rng.random() < .15), [hs[i] - hrs[i] - doubles[i] for i in range(9)], rng)
    walks = Counter(rng.randrange(9) for _ in range(bb))
    ks = _allocate(M._poisson(7, rng), [abs_[i] - hs[i] for i in range(9)], rng)
    rs = _allocate(runs, [hs[i] + walks[i] for i in range(9)], rng)
    rbis = _allocate(runs, abs_, rng)
    rows = [dict(g=1, ab=abs_[i], pa=abs_[i] + walks[i], h=hs[i], hr=hrs[i], d=doubles[i], t=triples[i],
                 bb=walks[i], so=ks[i], r=rs[i], rbi=rbis[i], sb=0, hbp=0, sf=0) for i in range(9)]
    return rows


def roster(league, club, year=1):
    rng = random.Random(f'roster:{league}:{club}')
    all_names = [a + b for a in SURNAMES for b in GIVEN]
    names = rng.sample(all_names, 20)
    age_base = 12 if league == 'little' else 14 if league == 'middle' else 17 if league == 'hs' else 21 if league == 'univ' else 26
    out, used = [], set()
    for i, name in enumerate(names):
        raw_age = age_base + rng.randint(-5, 8) if W.is_pro(league) else age_base + rng.randint(-1, 1)
        talent = W.level(league) + rng.gauss(0, 4)
        age = raw_age + year - 1 if W.is_pro(league) else max(12, raw_age)
        generation = max(0, (age - 22) // 19) if age > 40 else 0
        if generation:
            age = 22 + (age - 22) % 19
        if generation or not W.is_pro(league):
            replacement = random.Random(f'regen:{league}:{club}:{i}:{generation if W.is_pro(league) else year}')
            name = replacement.choice([item for item in all_names if item not in used])
        while name in used:
            name = rng.choice(all_names)
        used.add(name)
        out.append(dict(id=f'{i}:{generation}', name=name, role='batter' if i < 12 else 'pitcher',
                        position=POSITIONS[i] if i < 12 else 'SP' if i < 17 else 'RP', age=age,
                        ovr=round(max(25, min(99, talent + min(3, max(-8, (28 - age) * .3)))), 1), totals={}))
    return out


def team_stats(data, club):
    """팀 득점=타자 득점 합계, 상대 득점=투수 실점 합계를 유지하는 가상 선수 기록."""
    players = roster(data['league'], club, data['year'])
    for fixture in data['fixtures']:
        if club not in (fixture['home'], fixture['away']):
            continue
        home = club == fixture['home']
        my_runs, their_runs = (fixture['h'], fixture['a']) if home else (fixture['a'], fixture['h'])
        own = _offense(fixture['key'] + (':h' if home else ':a'), my_runs)
        opp = _offense(fixture['key'] + (':a' if home else ':h'), their_runs)
        n = fixture['round']
        batting_order = list(range(9))
        if n % 4 == 0:
            batting_order[n % 9] = 9 + n % 3
        for slot, line in enumerate(own):
            player = players[batting_order[slot]]
            player['totals'] = L.add(player['totals'], line)
        op = {}
        for line in opp:
            op = L.add(op, line)
        rng = random.Random('pitch:' + fixture['key'] + club)
        outs = [rng.randint(12, 22)]
        outs += [(27 - outs[0]) // 2, 27 - outs[0] - (27 - outs[0]) // 2]
        pitcher_ids = [12 + (n - 1) % 5, 17 + n % 3, 17 + (n + 1) % 3]
        allocations = {key: _allocate(op.get(key, 0), [out * 20 for out in outs], rng)
                       for key in ('h', 'bb', 'hr')}
        allocations['so'] = _allocate(op.get('so', 0), outs, rng)
        # 피홈런은 반드시 피안타 이하가 되게 같은 피안타 슬롯에 배분해요.
        allocations['hr'] = _allocate(op.get('hr', 0), [allocations['h'][i] for i in range(3)], rng)
        run_parts = _allocate(their_runs, [out * 20 for out in outs], rng)
        for i, player_id in enumerate(pitcher_ids):
            bf = outs[i] + allocations['h'][i] + allocations['bb'][i]
            line = dict(g=1, gs=int(i == 0), gr=int(i != 0), outs=outs[i], r=run_parts[i], er=run_parts[i],
                        w=int(my_runs > their_runs and i == (0 if outs[0] >= 15 else 1)),
                        l=int(my_runs < their_runs and i == 0),
                        sv=int(my_runs > their_runs and my_runs - their_runs <= 3 and i == 2),
                        bf=bf, np=bf * rng.randint(3, 5),
                        **{key: allocations[key][i] for key in ('h', 'bb', 'so', 'hr')})
            players[player_id]['totals'] = L.add(players[player_id]['totals'], line)
    for player in players:
        player['v'] = L.line_view(player['role'], player['totals'])
        player['war'] = L.war(player['role'], player['position'], player['totals'])
        player['pos'] = L.POS_LABEL.get(player['position'], '투수')
    return players


def member_stats(league, club, year, *, mode='daily'):
    from .game_visibility import rookie_visible
    from .models import LiteSeason, RookieSeasonStat
    if mode == 'daily':
        rows = rookie_visible(RookieSeasonStat.objects.filter(league=league, team=club, season__number=year,
                    player__isnull=False, user__is_active=True), 'user').select_related('player').order_by('-war')[:50]
        return [dict(name=s.name, role=s.role, line=L.pit_summary(s.totals) if s.role == 'pitcher' else L.bat_summary(s.totals),
                     war=s.war, url=reverse('community:rookie_player', args=[s.player_id])) for s in rows]
    rows = rookie_visible(LiteSeason.objects.filter(league=league, club=club, year=year, career__mode=mode,
                   career__user__is_active=True), 'career__user').select_related('career').order_by('-war')[:50]
    route = 'extreme_career' if mode == 'extreme' else 'lite_career'
    return [dict(name=s.career.name, role=s.career.role,
                 line=L.pit_summary(s.totals) if s.career.role == 'pitcher' else L.bat_summary(s.totals),
                 war=s.war, url=reverse('community:' + route, args=[s.career_id])) for s in rows]
