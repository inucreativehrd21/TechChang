"""정식판 회원 맞대결. 출전이 확정된 양쪽에 같은 타석을 넣고 경기 JSON에 보관해요.

전체 팀 경기를 재현하는 모형은 아니에요. 기존 개인 경기 모형의 일부 타석을 실제 회원
능력치 승부로 대체해요. 출전·타석·이닝 한도 안에서 한 쌍당 한 타석을 배정하고,
나머지는 기존 가상 상대를 유지해요. 예전 경기나 라이트 커리어는 소급하지 않아요.
"""
from collections import Counter, defaultdict

from django.urls import reverse

from . import rookie_sim as M
from . import rookie_world as W

OUTCOME = {'1B': '안타', '2B': '2루타', '3B': '3루타', 'HR': '홈런',
           'BB': '볼넷', 'HBP': '몸에 맞는 공', 'SO': '삼진', 'OUT': '범타'}


def _fixtures(plans):
    fixtures = defaultdict(list)
    for plan in plans:
        for no, result in plan['results']:
            f = result.get('_fixture')
            if f:
                fixtures[(plan['p'].league, f['day'], f['match'])].append((plan, no, result))
    return fixtures.values()


def groups(plans):
    """대결한 선수들은 같은 저장 트랜잭션을 쓴다. 무관한 선수의 실패는 격리한다."""
    parent = {x['p'].pk: x['p'].pk for x in plans}

    def root(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    for entries in _fixtures(plans):
        if len({x[0]['p'].club for x in entries}) < 2:
            continue
        for entry in entries[1:]:
            parent[root(entry[0]['p'].pk)] = root(entries[0][0]['p'].pk)
    out = defaultdict(list)
    for plan in plans:
        out[root(plan['p'].pk)].append(plan)
    return list(out.values())


def snapshot(p):
    # 이름·계정 정보는 다른 회원의 JSON에 복제하지 않는다.
    return dict(id=p.pk, club=p.club, role=p.role)


def resolve(plans, day, rng):
    """이미 출전한 경기만 사용한다. 대타는 한 타석, 대주자·대수비는 직접 승부 없음."""
    from . import rookie_league as L
    for entries in _fixtures(plans):
        if len({x[0]['p'].club for x in entries}) < 2:
            continue
        events, remaining = defaultdict(list), {}
        for plan, no, result in entries:
            p, line = plan['p'], result['line']
            remaining[p.pk] = (min(4, line.get('pa', 0)) if p.role == 'batter'
                               else 9 if p.lineup == 'sp' else 3 * M.RELIEF[p.lineup][1])
        bats = [e for e in entries if e[0]['p'].role == 'batter']
        pits = [e for e in entries if e[0]['p'].role == 'pitcher']
        # 번갈아 먼저 배정해 인원이 많은 경기에서도 특정 선수에게만 몰리지 않게 한다.
        pairs = [(b, p) for b in bats for p in pits if b[0]['p'].club != p[0]['p'].club]
        if pairs:
            offset = (day.toordinal() + entries[0][1]) % len(pairs)
            pairs = pairs[offset:] + pairs[:offset]
        for bat, pit in pairs:
            bp, pp = bat[0]['p'], pit[0]['p']
            if not remaining[bp.pk] or not remaining[pp.pk]:
                continue
            outcome = M._pick(M.pa_probs(bat[0]['gs'], pit[0]['gs']), rng)
            event = dict(outcome=outcome, slot=bp.slot or 7)
            events[bp.pk].append(dict(event, opponent=snapshot(pp)))
            events[pp.pk].append(dict(event, opponent=snapshot(bp)))
            remaining[bp.pk] -= 1
            remaining[pp.pk] -= 1
        for plan, no, result in entries:
            p, forced = plan['p'], events[plan['p'].pk]
            if not forced:
                continue
            args = (plan['gs'], W.level(p.league), rng)
            if p.role == 'batter':
                fresh = M.batter_game(plan['gs'], p.position or 'DH', W.level(p.league), rng,
                                      role=p.lineup, slot=p.slot, member_pas=forced)
            elif p.lineup == 'sp':
                fresh = M.starter_game(*args, member_pas=forced)
            else:
                fresh = M.relief_game(*args, role=p.lineup, member_pas=forced)
            result.update(fresh)
            result['line']['member_duels'] = forced
        # 양쪽 개인 기록에서 필요한 득점을 보장하며 하나의 팀 점수를 공유한다.
        scores = defaultdict(int)
        for plan, no, result in entries:
            p, line = plan['p'], result['line']
            opp = result['_fixture']['opponent']
            scores[p.club] = max(scores[p.club], result['team_runs'], line.get('rbi', 0) if p.role == 'batter' else 0,
                                 line.get('r', 0) if p.role == 'batter' else 0)
            scores[opp] = max(scores[opp], result['opp_runs'], line.get('r', 0) if p.role == 'pitcher' else 0)
        clubs = sorted(scores)
        if scores[clubs[0]] == scores[clubs[1]]:
            scores[clubs[rng.randrange(2)]] += 1
        for plan, no, result in entries:
            p, line = plan['p'], result['line']
            result['team_runs'], result['opp_runs'] = scores[p.club], scores[result['_fixture']['opponent']]
            if p.role == 'pitcher':
                win = result['team_runs'] > result['opp_runs']
                # 개인 경기의 원래 결정이 공유 점수와 반대가 되지 않게 다시 판단한다.
                for key in ('w', 'l', 'sv', 'hld'):
                    line.pop(key, None)
                if line.get('gs'):
                    if win and line.get('outs', 0) >= 15 and result['team_runs'] > line.get('r', 0):
                        line['w'] = 1
                    elif not win and line.get('r', 0) >= result['team_runs'] and line.get('r', 0):
                        line['l'] = 1
                elif win and 0 < line.get('lead', 0) <= 3 and line.get('r', 0) < line['lead']:
                    line['sv' if p.lineup == 'closer' else 'hld'] = 1
                result['summary'] = L.pit_summary(line)
        for plan, no, result in entries:
            result['line']['member_opponents'] = [dict(snapshot(other['p']), summary=r['summary'])
                for other, _, r in entries if other['p'].club != plan['p'].club]


def view(line, allowed=None):
    """당시 소속·결과와 현재 선수 이름을 쓴다. 삭제된 선수는 표시하지 않는다."""
    members = {x['id']: dict(x, outcomes=[]) for x in line.get('member_opponents', [])}
    for duel in line.get('member_duels', []):
        other = duel['opponent']
        row = members.setdefault(other['id'], dict(other, outcomes=[]))
        row['outcomes'].append(OUTCOME.get(duel['outcome'], ''))
    if not members:
        return []
    if allowed is None:
        from .models import RookiePlayer
        from .game_visibility import rookie_visible
        allowed = dict(rookie_visible(RookiePlayer.objects.filter(pk__in=members), 'user').values_list('pk', 'name'))
    return [dict(row, name=allowed[row['id']] if isinstance(allowed, dict) else '',
                 url=reverse('community:rookie_player', args=[row['id']]))
            for row in members.values() if row['id'] in allowed]


def history(player, games=None):
    """양쪽에 저장된 실제 맞대결만 집계한다. 이적·은퇴 뒤에도 당시 리그별로 유지한다."""
    from . import rookie_league as L
    from .models import RookiePlayer
    from .game_visibility import rookie_visible
    rows = {}
    source = games if games is not None else player.games.order_by('-day', '-no').iterator()
    for game in source:
        ids = {x['id'] for x in game.line.get('member_opponents', [])}
        ids.update(x['opponent']['id'] for x in game.line.get('member_duels', []))
        for member in view(game.line, allowed=ids):
            key = game.league, member['id']
            if key not in rows:
                rows[key] = dict(member, league=W.short(game.league), games=0, wins=0, losses=0, t=Counter(), last=game.day)
            row = rows[key]
            row['games'] += 1
            row['wins'] += game.team_runs > game.opp_runs
            row['losses'] += game.team_runs < game.opp_runs
            row['last'] = max(row['last'], game.day)
        for duel in game.line.get('member_duels', []):
            t = rows[(game.league, duel['opponent']['id'])]['t']
            o = duel['outcome']
            t['pa'] += 1
            t['ab'] += o not in ('BB', 'HBP')
            t['h'] += o in ('1B', '2B', '3B', 'HR')
            t['hr'] += o == 'HR'
            t['bb'] += o == 'BB'
            t['hbp'] += o == 'HBP'
            t['so'] += o == 'SO'
    allowed = dict(rookie_visible(RookiePlayer.objects.filter(pk__in=[r['id'] for r in rows.values()]), 'user')
                   .values_list('pk', 'name'))
    out = []
    for row in rows.values():
        if row['id'] not in allowed:
            continue
        row['name'] = allowed[row['id']]
        t = row.pop('t')
        row.update(t, avg=L.rate(t['h'] / t['ab']) if t['ab'] else '—', direct=bool(t['pa']))
        # Counter 없는 0 항목도 템플릿에 명시적으로 넘긴다.
        row.update({k: t[k] for k in ('pa', 'ab', 'h', 'hr', 'bb', 'hbp', 'so')})
        out.append(row)
    return sorted(out, key=lambda r: (-r['last'].toordinal(), -r['pa'], r['id']))
