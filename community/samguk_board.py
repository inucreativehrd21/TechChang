"""테크창 삼국지 — 오늘의 천하 생성기(docs/samguk-design.md 2·6.2장).

같은 날짜면 같은 판이 나온다. DB 층은 처음 만든 판을 SamgukDay.board 에 저장해 두고 다시 만들지 않는다.

- 등장 순환표: 전체 장수를 주마다 섞어 7묶음으로 나누고, 그 주의 요일 묶음은 반드시 판에 올린다.
  그래서 모든 장수가 7일에 한 번은 나온다(설계 기준은 14일).
- 군벌 6~8명이 본거지를 차지하고, 남은 도시는 빈 성이다. 시작 후보 3곳은 서로 떨어진 빈 성에서 고른다.
- 정세 하나(풍년·황건 봉기·역병·명장 출현·동맹·대설)가 그날 판을 바꾼다.
- 어제의 천하인(boss)이 있으면 그 편성이 군벌 하나로 들어온다.
"""
from __future__ import annotations

import hashlib
import random
from collections import deque
from datetime import date

from . import samguk_data as D
from . import samguk_rules as R

BOARD_VERSION = 1
EPOCH = date(2026, 11, 16)          # 순환표 기준 월요일

EVENTS = {
    'harvest': ('풍년', '내정으로 얻는 금과 군량이 늘어요.'),
    'yellow': ('황건 봉기', '황건 무리가 성 하나를 차지했어요. 토벌하면 점수를 더 받아요.'),
    'plague': ('역병', '징병으로 모이는 병사가 줄어요.'),
    'legend': ('명장 출현', '이름난 장수가 재야에 나타났어요.'),
    'alliance': ('동맹', '두 군벌이 손을 잡았어요. 이간계로 갈라놓을 수 있어요.'),
    'snow': ('대설', '북쪽 도시가 끼는 출정은 군령이 하나 더 들어요.'),
}
MAJORS = ('caocao', 'liubei', 'sunquan')
WALL = {'normal': 1.2, 'key': 1.35, 'capital': 1.5}
GARRISON_BONUS = {'normal': 0, 'key': 400, 'capital': 800}
OFFICER_SLOTS = {'normal': 2, 'key': 3, 'capital': 3}


def day_seed(day: date) -> int:
    return int.from_bytes(hashlib.sha256(f'samguk:{day.isoformat()}'.encode()).digest()[:8], 'big')


def run_seed(day: date, user_id: int) -> int:
    return int.from_bytes(hashlib.sha256(f'samguk-run:{day.isoformat()}:{user_id}'.encode()).digest()[:8], 'big')


def required_today(day: date) -> list:
    """그 주의 요일 묶음 — 오늘 판에 반드시 오를 장수."""
    idx = (day - EPOCH).days
    week, slot = divmod(idx, 7)
    codes = [g.code for g in D.GENERALS]
    random.Random(f'samguk-rot:{week}').shuffle(codes)
    return codes[slot::7]


def distance(a: str, b: str) -> int:
    seen, q = {a: 0}, deque([a])
    while q:
        c = q.popleft()
        if c == b:
            return seen[c]
        for n in D.CITY[c].links:
            if n not in seen:
                seen[n] = seen[c] + 1
                q.append(n)
    return 99


def generate(day: date, boss: dict | None = None) -> dict:
    """boss: {'name': 닉네임, 'officers': [코드 ≤3], 'troops': int} — 어제의 천하인 편성."""
    rng = random.Random(day_seed(day))
    event = rng.choice(sorted(EVENTS))
    required = required_today(day)
    used: set = set()
    cities = {c.code: {'owner': R.NONE, 'troops': rng.randint(400, 800), 'wall': 1.1, 'officers': []}
              for c in D.CITIES}
    lords: dict = {}

    # 1) 군벌 고르기: 큰 세 세력 중 2~3, 나머지에서 채워 6~8명
    majors = rng.sample(MAJORS, rng.randint(2, 3))
    others = rng.sample(sorted(set(D.LORDS) - set(MAJORS)), rng.randint(6, 8) - len(majors))
    chosen = majors + others
    rng.shuffle(chosen)
    free_cities = [c.code for c in D.CITIES]

    def take(city: str, who: str) -> None:
        free_cities.remove(city)
        cities[city]['owner'] = who

    # 어제의 천하인이 먼저 자리를 잡는다(본거지가 없으니 남은 도시 중 하나)
    if boss and boss.get('officers'):
        officers = [o for o in boss['officers'] if o in D.GENERAL][:3]
        if officers:
            city = rng.choice(sorted(free_cities))
            take(city, 'boss')
            cities[city]['troops'] = max(2500, min(int(boss.get('troops') or 4000), 9000))
            cities[city]['wall'] = WALL[D.CITY[city].grade]
            cities[city]['officers'] = officers
            used.update(officers)
            lords['boss'] = {'name': f'어제의 천하인 {boss.get("name") or ""}'.strip(), 'ally': None, 'boss': True}

    for lord in chosen:
        info = D.LORDS[lord]
        want = 2 if lord in MAJORS else rng.randint(1, 2)
        homes = [h for h in info['home'] if h in free_cities]
        if not homes:
            near = sorted(free_cities, key=lambda c: (min(distance(c, h) for h in info['home']), c))
            homes = near[:1]
        got = homes[:want]
        if not got:
            continue
        for city in got:
            take(city, lord)
        lords[lord] = {'name': D.GENERAL[lord].name, 'ally': None, 'boss': False}
        used.add(lord)

    # 2) 시작 후보: 서로 2칸 이상 떨어진 빈 성 셋
    empties = sorted(free_cities)
    starts = _pick_starts(rng, empties, cities)
    for c in starts:
        free_cities.remove(c)

    # 3) 황건 봉기: 남은 빈 성 하나
    if event == 'yellow' and free_cities:
        y = rng.choice(sorted(free_cities))
        free_cities.remove(y)
        cities[y].update(owner=R.YELLOW, troops=rng.randint(2400, 3200), wall=1.2)
        for code in ('zhangbao_yt', 'zhangliang', 'bocai'):
            if code not in used and len(cities[y]['officers']) < 2:
                cities[y]['officers'].append(code)
                used.add(code)

    # 4) 군벌 성의 병력·성벽·수비 장수
    req_left = [c for c in required if c not in used]
    for city, v in sorted(cities.items()):
        who = v['owner']
        if who not in lords or lords[who].get('boss'):
            continue
        grade = D.CITY[city].grade
        v['troops'] = 1800 + rng.randint(0, 1200) + GARRISON_BONUS[grade]
        v['wall'] = WALL[grade]
        slots = OFFICER_SLOTS[grade] - (0 if grade != 'normal' else rng.randint(0, 1))
        if who in D.GENERAL and who not in v['officers'] and not any(who in x['officers'] for x in cities.values()):
            v['officers'].append(who)
        info = D.LORDS[who]
        prefs = ([r for r in info['retainers'] if r in req_left] + [r for r in info['retainers'] if r not in used]
                 + [g for g in req_left if D.GENERAL[g].group == info['pool']])
        for code in prefs:
            if len(v['officers']) >= slots:
                break
            if code not in used:
                v['officers'].append(code)
                used.add(code)
                if code in req_left:
                    req_left.remove(code)

    # 5) 시작 장수: 후보마다 ★1~★2 둘. 능력 합이 비슷하게 지그재그로 나눈다(1-2-3-3-2-1)
    low = [c for c in req_left if D.GENERAL[c].tier <= 2]
    pool_low = [g.code for g in D.GENERALS if g.tier <= 2 and g.code not in used]
    rng.shuffle(pool_low)
    six = []
    for code in low + pool_low:
        if code not in used and code not in six:
            six.append(code)
        if len(six) == 6:
            break
    six.sort(key=lambda c: (-D.GENERAL[c].total, c))
    order = (0, 1, 2, 2, 1, 0)
    picks = [[], [], []]
    for code, slot in zip(six, order):
        picks[slot].append(code)
        used.add(code)
        if code in req_left:
            req_left.remove(code)
    start_opts = [{'city': city, 'officers': picks[i]} for i, city in enumerate(starts)]

    # 6) 남은 필수 장수: 군벌 성 빈자리 → 재야
    free: dict = {}
    lord_cities = [c for c, v in sorted(cities.items()) if v['owner'] in lords and not lords[v['owner']].get('boss')]
    for code in list(req_left):
        spot = next((c for c in lord_cities if len(cities[c]['officers']) < OFFICER_SLOTS[D.CITY[c].grade] + 1), None)
        if spot and D.GENERAL[code].tier < 4:
            cities[spot]['officers'].append(code)
        else:
            dest = rng.choice(sorted(free_cities + starts + lord_cities))
            free.setdefault(dest, []).append(code)
        used.add(code)
        req_left.remove(code)

    # 시작 도시마다 재야 한 명은 있게(첫 등용을 해 볼 수 있게)
    spare = [g.code for g in D.GENERALS if g.tier <= 2 and g.code not in used]
    rng.shuffle(spare)
    for city in starts:
        if not free.get(city) and spare:
            code = spare.pop()
            free.setdefault(city, []).append(code)
            used.add(code)

    # 7) 정세
    if event == 'legend':
        legends = [g.code for g in D.by_tier(4) if g.code not in used]
        if legends:
            code = rng.choice(legends)
            spot = sorted(free_cities or lord_cities, key=lambda c: (min(distance(c, s) for s in starts), c))
            dest = spot[len(spot) // 2]
            free.setdefault(dest, []).append(code)
            used.add(code)
    if event == 'alliance':
        pairs = [(a, b) for a in sorted(lords) for b in sorted(lords)
                 if a < b and not lords[a].get('boss') and not lords[b].get('boss') and _touch(cities, a, b)]
        if pairs:
            a, b = rng.choice(pairs)
            lords[a]['ally'], lords[b]['ally'] = b, a

    board = {
        'v': BOARD_VERSION, 'rules': R.RULES_VERSION, 'date': day.isoformat(), 'seed': day_seed(day),
        'event': event, 'cities': cities, 'lords': lords, 'free': free, 'starts': start_opts,
    }
    from . import samguk_legends as L
    board['legends'] = L.board_events(day, board)              # 전설 이벤트(모두에게 같다, 설계 8.1)
    return board


def _touch(cities: dict, a: str, b: str) -> bool:
    bs = {c for c, v in cities.items() if v['owner'] == b}
    return any(n in bs for c, v in cities.items() if v['owner'] == a for n in D.CITY[c].links)


def opportunity(cities: dict, city: str) -> float:
    """시작 도시 주변의 공략 기회 — 맞닿은 도시(빈 성은 쉽고 군벌 성은 어렵다) + 두 칸 거리는 절반 무게."""
    weight = {R.NONE: 1.0}
    near = set(D.CITY[city].links)
    far = {n for c in near for n in D.CITY[c].links} - near - {city}
    total = sum(D.CITY[n].value * weight.get(cities[n]['owner'], 0.45) for n in near)
    total += sum(D.CITY[n].value * weight.get(cities[n]['owner'], 0.45) * 0.4 for n in far)
    return total


def _pick_starts(rng: random.Random, empties: list, cities: dict | None = None) -> list:
    """서로 2칸 이상 떨어진 빈 성 셋. 공략 기회가 가장 고른 조합 몇 개 중에서 고른다(설계: 시작 선택은 지략이되 정답이 뻔하지 않게)."""
    combos = []
    for i, a in enumerate(empties):
        for j in range(i + 1, len(empties)):
            b = empties[j]
            if distance(a, b) < 2:
                continue
            for c in empties[j + 1:]:
                if distance(a, c) >= 2 and distance(b, c) >= 2:
                    combos.append((a, b, c))
    if not combos:                                   # 빈 성이 모자라면 가까워도 고른다
        return empties[:3]
    if cities:
        def spread(combo):
            opp = [opportunity(cities, c) for c in combo]
            return (max(opp) - min(opp)) / max(1.0, sum(opp) / 3)
        combos.sort(key=lambda combo: (round(spread(combo), 3), combo))
        combos = combos[:5]
    return list(rng.choice(combos))


# ── 튜토리얼(설계 2.1): 도시 5개·군벌 2명·장수 4명·군령 6, 운 없음 ─────────────
TUTORIAL_AP = 6


def tutorial() -> dict:
    cities = {
        'xuchang': {'owner': R.NONE, 'troops': 0, 'wall': 1.5, 'officers': []},
        'chenliu': {'owner': R.NONE, 'troops': 500, 'wall': 1.1, 'officers': []},
        'luoyang': {'owner': 'dongzhuo', 'troops': 1500, 'wall': 1.2, 'officers': ['huaxiong']},
        'wan': {'owner': 'yuanshu', 'troops': 2600, 'wall': 1.35, 'officers': ['yuanshu']},
        'shouchun': {'owner': R.NONE, 'troops': 600, 'wall': 1.1, 'officers': []},
    }
    return {
        'v': BOARD_VERSION, 'rules': R.RULES_VERSION, 'date': 'tutorial', 'seed': 0, 'tutorial': True, 'ap': TUTORIAL_AP,
        'event': 'harvest', 'cities': cities,
        'lords': {'dongzhuo': {'name': '동탁', 'ally': None, 'boss': False},
                  'yuanshu': {'name': '원술', 'ally': None, 'boss': False}},
        'free': {'xuchang': ['xunyu'], 'chenliu': ['dianwei']},
        'starts': [{'city': 'xuchang', 'officers': ['caocao', 'xiahoudun']}],
    }
