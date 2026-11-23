"""테크창 삼국지 — 규칙 엔진(docs/samguk-design.md 3·4장). DB 를 모르는 순수 함수.

판(board)은 samguk_board.generate() 가 날짜로 만든 그날의 천하이고 모두에게 같다.
한 사람의 판 진행(state)은 JSON 으로 저장할 수 있는 dict 이며 apply() 가 행동 하나씩 바꾼다.

- 같은 판·같은 상태·같은 행동이면 결과가 같다. 운은 state['seed'](날짜 + 사용자) 와 행동 차례로만 정해진다.
- 규칙 위반(군령 부족·이웃이 아닌 성 등)은 RuleError 를 내고 상태와 군령을 보존한다.
- 열린 판은 저장된 규칙 버전을 따른다. 2판부터 포로는 차례대로 대화해 영입한다.
- 수치는 초안이다. 하네스(scratchpad samguk_solver.py)로 조정하고, 바꾸면 RULES_VERSION 을 올린다.
"""
from __future__ import annotations

import copy
import random

from . import samguk_data as D

RULES_VERSION = 2
PARLEY_VERSION = 2

AP_BASE = 16
AP_BONUS_MAX = 5
SEASON_AP = 5
LEGACY_AP, LEGACY_FOOD, LEGACY_SEASON_AP = 10, 1000, 3

COST = {'develop': 1, 'conscript': 1, 'scout': 1, 'recruit': 1, 'scheme': 1, 'attack': 2, 'legend': 1}
SNOW_CITIES = frozenset({'beiping', 'ye', 'tianshui'})   # 대설: 이 도시가 끼는 출정은 군령 +1

START_GOLD = 1000
START_FOOD = 2400
START_TROOPS = 3000
TROOP_CAP = 15000

DEVELOP_GOLD = (200, 6)             # 200 + 정치 × 6
DEVELOP_FOOD = (300, 5)
LEGACY_DEVELOP_FOOD = (200, 4)
CONSCRIPT_COST = 300
CONSCRIPT_TROOPS = (800, 15)        # 800 + 통솔 × 15
ATTACK_FOOD_PER = 10                # 병력 10 당 군량 1
RECRUIT_STIPEND = {1: 0, 2: 0, 3: 200, 4: 400}
PARLEY_LINES = {
    '설득하기': '그대가 어떤 뜻으로 싸우는지 먼저 듣겠소.',
    '문답하기': '백성을 어떻게 돌볼 것인지 알겠소. 이제 마지막으로 한 가지만 더 묻겠소.',
    '회유하기': '나도 그 뜻에 힘을 보태겠소. 함께 가겠소.',
}

LUCK = (0.92, 1.08)
SCHEME_GAP = 20                     # 군사 지력 차가 이 이상이면 상대 전력 −10%
DUEL_GAP = 15                       # 최고 무력 차가 이 이상이면 일기토
RAID_DAMAGE = 0.15
NPC_ATTACK_PLAYER = 1.3             # NPC 가 내 성을 치는 전력비
NPC_ATTACK_NPC = 1.5
NPC_SEND = 0.6
NPC_GROW = {'normal': 300, 'key': 350, 'capital': 500}

SCORE_LORD = 150
SCORE_BOSS = 120
SCORE_YELLOW = 50
SCORE_TROOPS_PER = 100
SCORE_TROOPS_MAX = 30

ME = 'me'
NONE = 'none'
YELLOW = 'yellow'


class RuleError(ValueError):
    """화면에 그대로 보여 줄 규칙 위반. 상태는 바뀌지 않는다."""


# ── 판 시작 ──────────────────────────────────────────────────────────────
def new_run(board: dict, faction: str, start: int, seed: int) -> dict:
    """그날 판을 연다. start 는 board['starts'] 의 번호(0~2)."""
    if faction not in D.FACTIONS:
        raise RuleError('세력을 먼저 골라 주세요.')
    try:
        opt = board['starts'][start]
    except (IndexError, TypeError):
        raise RuleError('시작 도시를 다시 골라 주세요.') from None
    bonus = D.FACTION_BONUS[faction]
    cities = copy.deepcopy(board['cities'])
    home = cities[opt['city']]
    extra = opt.get('bonus') or {}                 # 시작 도시 보정(samguk_balance) — 기대 점수가 낮은 시작점에 보탠 금·병력
    home['owner'] = ME
    home['troops'] = int(START_TROOPS * (1 + bonus.get('start_troops', 0))) + int(extra.get('troops', 0))
    home['officers'] = list(opt['officers'])
    lords = copy.deepcopy(board['lords'])
    for info in lords.values():
        info.setdefault('alive', True)
        info.setdefault('feud', None)
    version = board.get('rules', 1)
    modern = version >= PARLEY_VERSION
    state = {
        'v': version, 'seed': int(seed), 'faction': faction, 'start': opt['city'],
        'event': board.get('event'), 'tutorial': bool(board.get('tutorial')),
        'ap_base': int(board.get('ap', AP_BASE if modern else LEGACY_AP)),
        'ap_bonus': 0, 'ap_spent': 0, 'turn': 0, 'seasons': 0,
        'gold': int(START_GOLD * (1 + bonus.get('start_gold', 0))) + int(extra.get('gold', 0)),
        'food': START_FOOD if modern else LEGACY_FOOD,
        'cities': cities, 'lords': lords,
        'free': copy.deepcopy(board.get('free', {})), 'captives': {},
        'scouted': [], 'seen': [], 'recruited': [],
        'destroyed': [], 'yellow_cleared': [], 'boss_beaten': False,
        'over': False,
    }
    _see(state, opt['officers'])
    _see(state, state['free'].get(opt['city'], []))
    return state


def add_bonus(state: dict, n: int) -> int:
    """사이트 활동으로 군령을 더한다(최대 AP_BONUS_MAX). 실제로 더한 양을 돌려준다."""
    room = max(0, AP_BONUS_MAX - state['ap_bonus'])
    got = max(0, min(int(n), room))
    state['ap_bonus'] += got
    if got and state['over'] and not state.get('ended'):
        state['over'] = False           # 군령이 다 떨어져 멈췄던 판은 다시 둘 수 있다(직접 끝낸 판은 그대로)
    return got


def ap_left(state: dict) -> int:
    return state['ap_base'] + state['ap_bonus'] - state['ap_spent']


def uses_parley(state: dict) -> bool:
    return state.get('v', 1) >= PARLEY_VERSION


# ── 조회 도우미 ───────────────────────────────────────────────────────────
def mine(state: dict) -> list:
    return [c for c, v in state['cities'].items() if v['owner'] == ME]


def owner(state: dict, city: str) -> str:
    return state['cities'][city]['owner']


def adjacent(a: str, b: str) -> bool:
    return b in D.CITY[a].links


def links(state: dict, city: str) -> list:
    """판에 있는 도시만 이웃으로 본다(튜토리얼 판은 도시 일부만 쓴다)."""
    return [c for c in D.CITY[city].links if c in state['cities']]


def my_officers(state: dict) -> list:
    return [o for c in mine(state) for o in state['cities'][c]['officers']]


def _g(code: str) -> D.General:
    return D.GENERAL[code]


def _see(state: dict, codes) -> None:
    for code in codes:
        if code in D.GENERAL and code not in state['seen']:
            state['seen'].append(code)


def action_cost(state: dict, action: dict) -> int:
    kind = action.get('kind')
    if kind not in COST:
        raise RuleError('알 수 없는 행동이에요.')
    cost = COST[kind]
    if kind == 'attack' and state.get('event') == 'snow':
        if action.get('from') in SNOW_CITIES or action.get('to') in SNOW_CITIES:
            cost += 1
    return cost


# ── 행동 ────────────────────────────────────────────────────────────────
def apply(board: dict, state: dict, action: dict) -> tuple:
    """행동 하나를 적용한 새 상태와 결과를 돌려준다. 원래 state 는 건드리지 않는다."""
    if state['over']:
        raise RuleError('오늘 판은 끝났어요.')
    kind = action.get('kind')
    if kind == 'end':
        new = copy.deepcopy(state)
        new['over'] = True
        new['ended'] = True
        return new, {'kind': 'end', 'ok': True, 'text': '오늘의 천하를 마쳤어요.'}
    cost = action_cost(state, action)
    if ap_left(state) < cost:
        raise RuleError(f'군령이 모자라요(필요 {cost}, 남은 군령 {ap_left(state)}).')
    new = copy.deepcopy(state)
    handler = _HANDLERS[kind]
    result = handler(board, new, action)
    new['ap_spent'] += cost
    new['turn'] += 1
    result['cost'] = cost
    result['npc'] = []
    season_ap = SEASON_AP if uses_parley(new) and not new.get('tutorial') else LEGACY_SEASON_AP
    while new['ap_spent'] >= (new['seasons'] + 1) * season_ap:
        new['seasons'] += 1
        result['npc'].extend(npc_turn(new))
    if ap_left(new) <= 0:
        new['over'] = True
    return new, result


def _need_my_city(state: dict, city: str) -> dict:
    if city not in state['cities'] or owner(state, city) != ME:
        raise RuleError('내 도시에서만 할 수 있어요.')
    return state['cities'][city]


def _officer_in(state: dict, city: str, code: str | None = None) -> D.General:
    here = state['cities'][city]['officers']
    if not here:
        raise RuleError('그 도시에 장수가 없어요.')
    if code is None:
        return _g(here[0])
    if code not in here:
        raise RuleError('그 장수는 이 도시에 없어요.')
    return _g(code)


def _best(state: dict, city: str, stat: str) -> D.General | None:
    here = [_g(o) for o in state['cities'][city]['officers']]
    return max(here, key=lambda g: (getattr(g, stat), g.code)) if here else None


def develop_yield(state: dict, g: D.General) -> tuple:
    gold = DEVELOP_GOLD[0] + DEVELOP_GOLD[1] * g.pol
    base, per_pol = DEVELOP_FOOD if uses_parley(state) else LEGACY_DEVELOP_FOOD
    food = base + per_pol * g.pol
    if g.skill == 'supply':
        gold, food = gold * 1.2, food * 1.2
    if state.get('event') == 'harvest':
        gold, food = gold * 1.2, food * 1.5
    return int(gold), int(food)


def _develop(board, state, a):
    city = a.get('city')
    _need_my_city(state, city)
    g = _best(state, city, 'pol')
    if g is None:
        raise RuleError('내정을 맡을 장수가 없어요.')
    gold, food = develop_yield(state, g)
    state['gold'] += gold
    state['food'] += food
    return {'kind': 'develop', 'ok': True, 'city': city, 'by': g.code, 'gold': gold, 'food': food,
            'text': f'{g.name}이(가) {D.CITY[city].name}을(를) 다스려 금 {gold}, 군량 {food}을 얻었어요.'}


def conscript_yield(state: dict, g: D.General) -> int:
    n = CONSCRIPT_TROOPS[0] + CONSCRIPT_TROOPS[1] * g.lead
    if g.skill == 'fame':
        n *= 1.1
    if state.get('event') == 'plague':
        n *= 0.6
    return int(n)


def _conscript(board, state, a):
    city = a.get('city')
    c = _need_my_city(state, city)
    g = _best(state, city, 'lead')
    if g is None:
        raise RuleError('징병을 맡을 장수가 없어요.')
    if state['gold'] < CONSCRIPT_COST:
        raise RuleError(f'금이 모자라요(징병에 {CONSCRIPT_COST} 필요).')
    if c['troops'] >= TROOP_CAP:
        raise RuleError('이 도시는 병력이 가득 찼어요.')
    n = min(conscript_yield(state, g), TROOP_CAP - c['troops'])
    state['gold'] -= CONSCRIPT_COST
    c['troops'] += n
    return {'kind': 'conscript', 'ok': True, 'city': city, 'by': g.code, 'troops': n,
            'text': f'{g.name}이(가) {D.CITY[city].name}에서 병사 {n}명을 모았어요.'}


def _near_mine(state: dict, target: str) -> list:
    return [c for c in mine(state) if adjacent(c, target)]


def _scout(board, state, a):
    target = a.get('city')
    if target not in state['cities'] or owner(state, target) == ME:
        raise RuleError('정찰할 다른 세력의 성을 골라 주세요.')
    if not _near_mine(state, target):
        raise RuleError('내 도시와 맞닿은 성만 정찰할 수 있어요.')
    if target not in state['scouted']:
        state['scouted'].append(target)
    here = state['cities'][target]
    _see(state, here['officers'])
    _see(state, state['free'].get(target, []))
    return {'kind': 'scout', 'ok': True, 'city': target, 'troops': here['troops'], 'officers': list(here['officers']),
            'wall': here['wall'], 'text': f'{D.CITY[target].name}을(를) 살폈어요: 병력 {here["troops"]}명.'}


def persuade(state: dict, by: D.General, target: D.General, gold: int) -> int:
    p = by.pol + gold // 50
    if target.group == state['faction']:
        p += 10
    if by.skill == 'virtue':
        p += 15
    elif by.skill == 'fame':
        p += 8
    p += D.FACTION_BONUS[state['faction']].get('persuade', 0)
    return p


def recruit_need(target: D.General, captive: bool) -> int:
    return D.RECRUIT_NEED[target.tier] - (15 if captive else 0)


def recruit_gold_needed(state: dict, by: D.General, target: D.General, captive: bool) -> int | None:
    """필요치를 맞추는 데 드는 최소 금(50 단위). 금으로도 안 되면 None — 화면이 미리 보여 준다."""
    short = recruit_need(target, captive) - persuade(state, by, target, 0)
    if short <= 0:
        return 0
    gold = short * 50
    return gold if gold <= state['gold'] else None


def recruit_offer(state: dict, target: D.General, captive: bool) -> dict:
    if captive:
        stages = ('설득하기', '회유하기') if target.tier <= 2 else ('설득하기', '문답하기', '회유하기')
        progress = state.get('parley', {}).get(target.code, 0)
        return {'label': stages[progress], 'progress': progress, 'total': len(stages), 'gold': 0,
                'reply': PARLEY_LINES[stages[progress - 1]] if progress else ''}
    # 촉의 등용 우대는 금이 필요한 재야 장수에게 적용한다.
    discount = 50 if state['faction'] == 'shu' else 0
    return {'label': '등용하기', 'gold': max(0, RECRUIT_STIPEND[target.tier] - discount)}


def _recruit(board, state, a):
    city, code, by_code = a.get('city'), a.get('target'), a.get('by')
    c = _need_my_city(state, city)
    free = state['free'].get(city, [])
    caps = state['captives'].get(city, [])
    if code in free:
        captive = False
    elif code in caps:
        captive = True
    else:
        raise RuleError('이 도시에 그 장수가 없어요.')
    target = _g(code)
    by = _officer_in(state, city, None if uses_parley(state) else by_code)
    detail = {}
    if uses_parley(state):
        offer = recruit_offer(state, target, captive)
        gold = offer['gold']
        if captive:
            progress = offer['progress'] + 1
            detail = {'progress': progress, 'total': offer['total'], 'reply': PARLEY_LINES[offer['label']]}
            if progress < offer['total']:
                state.setdefault('parley', {})[code] = progress
                return {'kind': 'parley', 'ok': True, 'city': city, 'target': code, **detail,
                        'text': f'{target.name} “{detail["reply"]}”'}
            state.get('parley', {}).pop(code, None)
    else:
        gold = int(a.get('gold') or 0)
        if gold < 0 or gold > state['gold']:
            raise RuleError('쓸 금이 모자라요.')
        p, need = persuade(state, by, target, gold), recruit_need(target, captive)
        if p < need:
            raise RuleError(f'설득력이 모자라요(설득력 {p}, 필요 {need}).')
        detail = {'persuade': p, 'need': need}
    if gold > state['gold']:
        raise RuleError(f'쓸 금이 모자라요(필요 {gold}).')
    state['gold'] -= gold
    (caps if captive else free).remove(code)
    c['officers'].append(code)
    _see(state, [code])
    if code not in state['recruited']:
        state['recruited'].append(code)
    return {'kind': 'recruit', 'ok': True, 'city': city, 'by': by.code, 'target': code, 'gold': gold,
            **detail, 'text': f'{target.name} 영입을 마쳤어요.'}


def _scheme(board, state, a):
    mode = a.get('mode', 'raid')
    by_city, by_code, target = a.get('from'), a.get('by'), a.get('city')
    _need_my_city(state, by_city)
    by = _officer_in(state, by_city, by_code)
    if target not in state['cities'] or not adjacent(by_city, target) or owner(state, target) == ME:
        raise RuleError('맞닿은 다른 세력의 성에만 계략을 쓸 수 있어요.')
    here = state['cities'][target]
    mind = by.intl + (10 if by.skill == 'divine' else 0)
    guard = _best(state, target, 'intl')
    wall_mind = (guard.intl if guard else 30) + (15 if guard and any(_g(o).skill == 'guard' for o in here['officers']) else 0)
    if mode == 'raid':
        ok = mind >= wall_mind
        dmg = 0
        if ok:
            rate = RAID_DAMAGE * (1.5 if by.skill == 'fire' else 1)
            dmg = int(here['troops'] * rate)
            here['troops'] -= dmg
        _see(state, here['officers'])
        text = (f'{by.name}의 계략으로 {D.CITY[target].name}의 병력이 {dmg}명 줄었어요.' if ok else
                f'{D.CITY[target].name}이(가) {by.name}의 계략을 알아챘어요.')
        return {'kind': 'scheme', 'mode': 'raid', 'ok': ok, 'city': target, 'by': by.code, 'damage': dmg,
                'mind': mind, 'against': wall_mind, 'text': text}
    if mode == 'sow':
        lord_a, lord_b = here['owner'], a.get('other')
        if lord_a in (NONE, YELLOW) or lord_a not in state['lords']:
            raise RuleError('군벌의 성에만 이간계를 쓸 수 있어요.')
        if lord_b not in state['lords'] or lord_b == lord_a or not state['lords'][lord_b]['alive']:
            raise RuleError('싸움을 붙일 다른 군벌을 골라 주세요.')
        if not _lords_touch(state, lord_a, lord_b):
            raise RuleError('두 군벌의 땅이 맞닿아 있어야 해요.')
        lord_g = _g(lord_a) if lord_a in D.GENERAL else None
        against = max([_g(o).intl for c in _lord_cities(state, lord_a) for o in state['cities'][c]['officers']]
                      or [lord_g.intl if lord_g else 50]) + 5
        ok = mind >= against
        if ok:
            for x, y in ((lord_a, lord_b), (lord_b, lord_a)):
                state['lords'][x]['feud'] = y
                if state['lords'][x].get('ally') == y:
                    state['lords'][x]['ally'] = None
        name_a, name_b = state['lords'][lord_a]['name'], state['lords'][lord_b]['name']
        text = f'{name_a}와(과) {name_b} 사이가 틀어졌어요.' if ok else f'{name_a} 진영이 이간계를 꿰뚫어 봤어요.'
        return {'kind': 'scheme', 'mode': 'sow', 'ok': ok, 'lords': [lord_a, lord_b], 'by': by.code,
                'mind': mind, 'against': against, 'text': text}
    raise RuleError('알 수 없는 계략이에요.')


def _lord_cities(state: dict, lord: str) -> list:
    return [c for c, v in state['cities'].items() if v['owner'] == lord]


def _lords_touch(state: dict, a: str, b: str) -> bool:
    bs = set(_lord_cities(state, b))
    return any(n in bs for c in _lord_cities(state, a) for n in links(state, c))


# ── 전투 ────────────────────────────────────────────────────────────────
def side_power(troops: int, officers: list, *, attacking: bool, terrain: str, wall: float = 1.0,
               wu_bonus: bool = False) -> float:
    lead = officers[0].lead if officers else 30
    war = sum(g.war for g in officers) / len(officers) if officers else 40
    p = troops * (0.6 + lead / 100) * (1 + (war - 50) / 200)
    skills = {g.skill for g in officers}
    if attacking:
        if 'charge' in skills:
            p *= 1.08
        if 'cavalry' in skills and terrain == 'plain':
            p *= 1.06
    else:
        if 'archery' in skills:
            p *= 1.08
        p *= wall + (0.15 if 'fortify' in skills else 0)
    if terrain == 'water':
        if 'navy' in skills:
            p *= 1.12
        if wu_bonus:
            p *= 1 + D.FACTION_BONUS['wu']['water_power']
    return p


def battle(att_troops: int, att: list, def_troops: int, dfn: list, *, city: str, wall: float, luck: float = 1.0,
           att_wu: bool = False, def_wu: bool = False, def_ambush_vs_npc: bool = False) -> dict:
    """한 번의 전투. att/dfn 은 General 목록(첫 장수가 대장). 결과 dict(화면 연출과 기보에 쓴다)."""
    terrain = D.CITY[city].terrain
    p = side_power(att_troops, att, attacking=True, terrain=terrain, wu_bonus=att_wu)
    d = side_power(def_troops, dfn, attacking=False, terrain=terrain, wall=wall, wu_bonus=def_wu)
    notes = []
    ai = max((g.intl for g in att), default=30)
    di = max((g.intl for g in dfn), default=30)
    if ai - di >= SCHEME_GAP:
        d *= 0.9
        notes.append('scheme_att')
    elif di - ai >= SCHEME_GAP:
        p *= 0.9
        notes.append('scheme_def')
    duel = None
    if att and dfn:
        aw, dw = max(att, key=lambda g: (g.war, g.code)), max(dfn, key=lambda g: (g.war, g.code))
        if abs(aw.war - dw.war) >= DUEL_GAP:
            win = aw if aw.war > dw.war else dw
            duel = {'att': aw.code, 'def': dw.code, 'winner': win.code}
            if win is aw:
                p *= 1.1
            else:
                d *= 1.1
    if def_ambush_vs_npc and any(g.skill == 'ambush' for g in dfn):
        p *= 0.9
        notes.append('ambush')
    r = (p / d if d > 0 else 99.0) * luck
    if r >= 1:
        att_loss = min(0.6, max(0.08, 0.45 / r))
        def_loss = 1.0
    else:
        att_loss = min(0.9, max(0.5, 0.5 + (1 - r) * 0.5))
        def_loss = min(0.45, max(0.05, 0.4 * r))
    return {'win': r >= 1, 'ratio': round(r, 3), 'luck': round(luck, 3), 'power': [round(p), round(d)],
            'att_left': int(att_troops * (1 - att_loss)), 'def_left': int(def_troops * (1 - def_loss)),
            'duel': duel, 'notes': notes}


def _luck(state: dict, tag: str) -> float:
    if state.get('tutorial'):
        return 1.0                      # 튜토리얼은 누가 해도 같은 결과
    return random.Random(f'{state["seed"]}:{state["turn"]}:{tag}').uniform(*LUCK)


def _attack(board, state, a):
    src, dst = a.get('from'), a.get('to')
    officers = list(a.get('officers') or [])
    troops = int(a.get('troops') or 0)
    s = _need_my_city(state, src)
    if dst not in state['cities'] or owner(state, dst) == ME:
        raise RuleError('칠 성을 골라 주세요.')
    if not adjacent(src, dst):
        raise RuleError('맞닿은 성만 칠 수 있어요.')
    if not officers or len(officers) > 3 or len(set(officers)) != len(officers):
        raise RuleError('출정할 장수를 1~3명 골라 주세요.')
    for o in officers:
        if o not in s['officers']:
            raise RuleError('출정할 장수는 출발 도시에 있어야 해요.')
    if troops <= 0 or troops > s['troops']:
        raise RuleError('보낼 병력을 다시 정해 주세요.')
    food = troops // ATTACK_FOOD_PER
    if state['food'] < food:
        raise RuleError(f'군량이 모자라요(필요 {food}).')
    t = state['cities'][dst]
    defender = t['owner']
    att = [_g(o) for o in officers]
    dfn = [_g(o) for o in t['officers']]
    res = battle(troops, att, t['troops'], dfn, city=dst, wall=t['wall'], luck=_luck(state, 'attack'),
                 att_wu=state['faction'] == 'wu')
    state['food'] -= food
    s['troops'] -= troops
    for o in officers:
        s['officers'].remove(o)
    _see(state, t['officers'])
    out = {'kind': 'attack', 'from': src, 'to': dst, 'defender': defender, 'officers': officers, 'troops': troops,
           'def_troops': t['troops'], 'def_officers': list(t['officers']), **res}
    if res['win']:
        _capture(state, dst, defender, officers, res['att_left'])
        out['ok'] = True
        out['text'] = f'{D.CITY[dst].name}을(를) 점령했어요.'
        out['captives'] = list(state['captives'].get(dst, []))
        if defender in state['destroyed'] and defender in state['lords']:
            out['destroyed'] = defender
    else:
        t['troops'] = res['def_left']
        s['troops'] += res['att_left']
        s['officers'].extend(officers)
        out['ok'] = False
        out['text'] = f'{D.CITY[dst].name} 공격이 막혔어요.'
    return out


def _capture(state: dict, city: str, defender: str, officers: list, troops: int) -> None:
    """city 를 내가 차지한다. 수비 장수는 포로, 군벌이 땅을 다 잃으면 멸망."""
    t = state['cities'][city]
    if t['officers']:
        state['captives'].setdefault(city, []).extend(t['officers'])
    t['owner'], t['officers'], t['troops'] = ME, list(officers), troops
    _see(state, state['free'].get(city, []))
    if defender == YELLOW and city not in state['yellow_cleared']:
        state['yellow_cleared'].append(city)
    if defender in state['lords'] and not _lord_cities(state, defender):
        _destroy(state, defender)


def _destroy(state: dict, lord: str) -> None:
    info = state['lords'][lord]
    if not info['alive']:
        return
    info['alive'] = False
    state['destroyed'].append(lord)
    if info.get('boss'):
        state['boss_beaten'] = True
    for other in state['lords'].values():
        if other.get('feud') == lord:
            other['feud'] = None
        if other.get('ally') == lord:
            other['ally'] = None


# ── NPC 차례(설계 4.4) ────────────────────────────────────────────────────
def npc_turn(state: dict) -> list:
    """계절이 바뀔 때 NPC 군벌이 움직인다. 같은 상태면 같은 결과(운은 내 성을 칠 때만)."""
    events = []
    for city, v in sorted(state['cities'].items()):
        if v['owner'] in state['lords'] and state['lords'][v['owner']]['alive']:
            v['troops'] = min(TROOP_CAP, v['troops'] + NPC_GROW[D.CITY[city].grade])
    order = sorted((lord for lord, info in state['lords'].items() if info['alive']),
                   key=lambda lord: (-sum(state['cities'][c]['troops'] for c in _lord_cities(state, lord)), lord))
    for lord in order:
        if not state['lords'][lord]['alive']:
            continue
        move = _npc_choose(state, lord)
        if move:
            events.append(_npc_attack(state, lord, *move))
    return events


def _npc_choose(state: dict, lord: str):
    info = state['lords'][lord]
    feud, ally = info.get('feud'), info.get('ally')
    best = None
    for src in _lord_cities(state, lord):
        s = state['cities'][src]
        if s['troops'] < 600:
            continue
        send = int(s['troops'] * NPC_SEND)
        att = _npc_party(s)
        for dst in links(state, src):
            t = state['cities'][dst]
            who = t['owner']
            if who == lord or (ally and who == ally):
                continue
            if feud:
                if who != feud:
                    continue
                need = 1.0
            elif who == ME:
                need = NPC_ATTACK_PLAYER
            else:
                need = NPC_ATTACK_NPC
            p = side_power(send, att, attacking=True, terrain=D.CITY[dst].terrain)
            d = side_power(t['troops'], [_g(o) for o in t['officers']], attacking=False,
                           terrain=D.CITY[dst].terrain, wall=t['wall'],
                           wu_bonus=(who == ME and state['faction'] == 'wu'))
            ratio = p / d if d > 0 else 99.0
            if ratio < need:
                continue
            # 내 성을 먼저, 그다음 약한 곳
            key = (0 if who == ME else 1, d, dst)
            if best is None or key < best[0]:
                best = (key, src, dst, send, [o.code for o in att])
    return best[1:] if best else None


def _npc_party(city_state: dict) -> list:
    gs = sorted((_g(o) for o in city_state['officers']), key=lambda g: (-g.war, g.code))
    return gs[:2]


def _npc_attack(state: dict, lord: str, src: str, dst: str, send: int, party: list) -> dict:
    s, t = state['cities'][src], state['cities'][dst]
    defender = t['owner']
    att = [_g(o) for o in party]
    dfn = [_g(o) for o in t['officers']]
    luck = _luck(state, f'npc:{lord}:{dst}') if defender == ME else 1.0
    res = battle(send, att, t['troops'], dfn, city=dst, wall=t['wall'], luck=luck,
                 def_wu=defender == ME and state['faction'] == 'wu', def_ambush_vs_npc=defender == ME)
    s['troops'] -= send
    out = {'kind': 'npc', 'lord': lord, 'from': src, 'to': dst, 'defender': defender, **res}
    name = state['lords'][lord]['name']
    if res['win']:
        for o in party:
            s['officers'].remove(o)
        # 내 장수는 이웃한 내 성으로 물러나고, NPC 끼리 싸움에서 진 쪽 장수는 판에서 흩어진다
        fled = _flee(state, dst) if defender == ME else []
        t['owner'], t['officers'], t['troops'] = lord, list(party), res['att_left']
        for code in state['captives'].pop(dst, []):
            state.get('parley', {}).pop(code, None)
        out['fled'] = fled
        out['text'] = f'{name}이(가) {D.CITY[dst].name}을(를) 빼앗았어요.'
        if defender in state['lords'] and not _lord_cities(state, defender):
            _destroy_by_npc(state, defender)
    else:
        t['troops'] = res['def_left']
        s['troops'] += res['att_left']
        out['text'] = f'{name}이(가) {D.CITY[dst].name}을(를) 쳤지만 막아 냈어요.'
    return out


def _flee(state: dict, city: str) -> list:
    """내 성이 떨어지면 장수는 맞닿은 내 성으로 물러난다. 갈 곳이 없으면 흩어진다."""
    t = state['cities'][city]
    escaped = []
    refuge = [c for c in links(state, city) if state['cities'][c]['owner'] == ME]
    for o in t['officers']:
        if refuge:
            state['cities'][refuge[0]]['officers'].append(o)
            escaped.append(o)
    t['officers'] = []
    return escaped


def _destroy_by_npc(state: dict, lord: str) -> None:
    info = state['lords'][lord]
    info['alive'] = False
    for other in state['lords'].values():
        if other.get('feud') == lord:
            other['feud'] = None
        if other.get('ally') == lord:
            other['ally'] = None


# ── 점수(설계 4.6) ────────────────────────────────────────────────────────
def score(state: dict) -> dict:
    owned = mine(state)
    city_pts = sum(D.CITY[c].value for c in owned) - D.CITY[state['start']].value
    lords = SCORE_LORD * len([x for x in state['destroyed'] if not state['lords'][x].get('boss')])
    boss = SCORE_BOSS if state['boss_beaten'] else 0
    recruits = sum(D.RECRUIT_SCORE[_g(c).tier] for c in state['recruited'])
    yellow = SCORE_YELLOW * len(state['yellow_cleared'])
    troops = min(SCORE_TROOPS_MAX, sum(state['cities'][c]['troops'] for c in owned) // SCORE_TROOPS_PER)
    parts = {'cities': city_pts, 'lords': lords, 'boss': boss, 'recruits': recruits, 'yellow': yellow,
             'troops': troops}
    return {'total': sum(parts.values()), **parts}


def _legend(board, state, a):
    """전설 이벤트 진행(설계 8.1) — 군령 1, 점수 없음. 시리즈 단계·장수 조건은 DB 층(samguk_legends)이 먼저 검사한다."""
    city, by = a.get('city'), a.get('by')
    events = [e for e in board.get('legends', []) if e['city'] == city]
    if not events:
        raise RuleError('오늘 그 도시에는 전설의 흔적이 없어요.')
    here = [c for c in mine(state) if c == city or adjacent(c, city)]
    holder = next((c for c in here if by in state['cities'][c]['officers']), None)
    if holder is None:
        raise RuleError('그 도시나 맞닿은 내 도시에 있는 장수를 보내 주세요.')
    state.setdefault('legend_hits', []).append({'series': a.get('series'), 'event': events[0]['event'],
                                                'city': city, 'by': by})
    g = _g(by)
    return {'kind': 'legend', 'ok': True, 'series': a.get('series'), 'event': events[0]['event'], 'city': city,
            'by': by, 'text': f'{g.name}이(가) {D.CITY[city].name}에서 전설의 흔적을 따라갔어요.'}


_HANDLERS = {
    'develop': _develop,
    'conscript': _conscript,
    'scout': _scout,
    'recruit': _recruit,
    'scheme': _scheme,
    'attack': _attack,
    'legend': _legend,
}
