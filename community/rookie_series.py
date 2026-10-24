"""포스트시즌·국제대회·아마추어 결승을 경기 단위로 — 특별 전광판에 1차전부터 끝까지 보여 줄 기록(2026-10-25 사용자 요청).

원칙(사용자 결정: 우승·메달 분포는 지금 확률표와 최대한 같게):
- **결과는 기존 규칙이 정한다.** 결승 진출(`POSTSEASON` 표·`kbo_final`), 우승(결정적 순간), 국제대회 단계(`INTL` 표)는
  지금 코드가 그대로 정하고, 이 모듈은 그 결과에 맞는 경기 흐름을 만든다. 그래서 분포는 '비슷'이 아니라 시드마다 같다.
- **메인 난수는 쓰지 않는다.** 커리어·연도·용도로 만든 파생 난수만 쓴다 → 기존 시즌의 난수 순서·기록이 그대로다.
- 경기마다 정해진 승패가 나올 때까지 기존 경기 함수(batter_game·starter_game·relief_game)를 다시 굴린다(기각 표본).
  이길 때는 내가 잘한 경기가, 질 때는 못한 경기가 뽑히기 쉬워 내 기록과 팀 결과가 자연스럽게 맞물린다.
- 결승의 결정적 순간은 언제나 시리즈를 끝내는 경기다. 장면 전엔 경기 번호(N차전)만 정하고, 앞 경기들의 승패는
  결과가 정해진 뒤 만든다(전광판은 결정적 순간 뒤 시즌 결산에 보인다). 4·5·6·7차전 ≈ 17·24·23·36%.
- `ROOKIE_SERIES_ENABLED`(설정 또는 환경 변수, 기본 꺼짐)가 꺼져 있으면 아무 일도 하지 않는다.

기록 형식(전광판이 읽는 값) — `series_doc()` 참고.
"""
from __future__ import annotations

import os
import random
import re

from . import rookie_league as L
from . import rookie_sim as M
from . import rookie_world as W


def enabled() -> bool:
    from django.conf import settings
    v = getattr(settings, 'ROOKIE_SERIES_ENABLED', os.environ.get('ROOKIE_SERIES_ENABLED', 'false'))
    return v is True or str(v).lower() == 'true'


def rng_for(c, tag: str) -> random.Random:
    """파생 난수 — 같은 선수·같은 시즌·같은 용도면 같은 흐름(새로고침해도 같다)."""
    return random.Random(f'series:{getattr(c, "pk", 0)}:{getattr(c, "name", "")}:{getattr(c, "year", 0)}:{tag}')


# ───────────────────────────── 대회 형식 (실제 방식을 단순화 — 리그 하나로 운영하는 게임 구조에 맞춤)
# (코드, 이름, 최대 경기 수, 필요한 승수)
ROUNDS = {
    'kbo1': (('wc', '와일드카드 결정전', 2, 2), ('semi', '준플레이오프', 5, 3), ('po', '플레이오프', 5, 3),
             ('final', '한국시리즈', 7, 4)),
    'mlb': (('wc', '와일드카드 시리즈', 3, 2), ('ds', '디비전 시리즈', 5, 3), ('cs', '챔피언십 시리즈', 7, 4),
            ('final', '월드시리즈', 7, 4)),
    'npb1': (('cs1', '클라이맥스 시리즈 퍼스트 스테이지', 3, 2), ('cs2', '클라이맥스 시리즈 파이널 스테이지', 6, 4),
             ('final', '일본시리즈', 7, 4)),
    'cpbl': (('wc', '와일드카드 시리즈', 3, 2), ('po', '플레이오프', 5, 3), ('final', '대만시리즈', 7, 4)),
}
POST_LEVEL = 2.0                     # 가을야구 상대는 리그 평균보다 조금 강하다


def entry_round(league: str, rank: int) -> int:
    """정규시즌 순위 → 처음 치르는 라운드(상위 시드는 건너뛴다). KBO 는 kbo_final 을 그대로 따른다."""
    if league == 'mlb':
        return 1 if rank <= 4 else 0
    if league == 'npb1':
        return 1 if (rank + 1) // 2 == 1 else 0          # 두 리그의 1위 둘은 파이널 스테이지부터
    if league == 'cpbl':
        return 2 if rank == 1 else 1 if rank == 2 else 0
    return {1: 3, 2: 2, 3: 1}.get(rank, 0)               # kbo1


def _head_start(league: str, code: str, us_higher: bool) -> tuple:
    """(우리 선승, 상대 선승) — KBO 와일드카드 4위 1승, NPB 파이널 스테이지 리그 1위 1승."""
    if (league, code) in (('kbo1', 'wc'), ('npb1', 'cs2')):
        return (1, 0) if us_higher else (0, 1)
    return 0, 0


def _p_game(rank: int, opp_rank: int) -> float:
    return max(.35, min(.65, .5 + .025 * (opp_rank - rank)))


def _clubs(league: str, exclude: str) -> list:
    sysname = W.system_of(league)
    return [t for t in W.PRO_TEAM.values() if t['system'] == sysname and t['code'] != exclude]


def team_of(league: str, code: str) -> dict:
    t = W.PRO_TEAM.get(code) or {}
    return {'code': code, 'name': t.get('name', code), 'short': W.club_short(league, code) if t else code,
            'color': t.get('color', '')}


# ───────────────────────────── 한 경기
INNING_W = (1.0, 1.0, 1.05, 1.05, 1.1, 1.1, 1.15, 1.1, 1.0)
LOSER_RUNS = ((0, .11), (1, .17), (2, .19), (3, .17), (4, .13), (5, .09), (6, .06), (7, .04), (8, .02), (9, .02))
MARGIN = ((1, .31), (2, .22), (3, .16), (4, .11), (5, .08), (6, .05), (7, .04), (8, .03))


def _pick(table, r):
    return r.choices([v for v, _w in table], [w for _v, w in table])[0]


def _score(won: bool, r) -> tuple:
    lo = _pick(LOSER_RUNS, r)
    hi = lo + _pick(MARGIN, r)
    return (hi, lo) if won else (lo, hi)


def _spread(runs: int, innings: int, r) -> list:
    out = [0] * innings
    for _ in range(runs):
        out[r.choices(range(innings), INNING_W[:innings])[0]] += 1
    return out


def linescore(us: int, them: int, home: str, r, walkoff_ok: bool = True) -> dict:
    """이닝별 점수 — 홈 팀이 이기면 9회말이 없거나(X) 끝내기. 합계는 언제나 R 과 같다."""
    away, home_runs = (us, them) if home == 'them' else (them, us)
    a = _spread(away, 9, r)
    margin = home_runs - away
    if home_runs > away:
        if walkoff_ok and margin <= 2 and r.random() < .35:
            # 끝내기는 결승점이 나는 순간 끝난다 — 9회말 득점은 뒤진 만큼 + 1(홈런이면 최대 4점)
            ninth = r.randint(margin, min(4, margin + 2, home_runs))
            before = home_runs - ninth                       # 9회말 전엔 비기거나 뒤져 있었다(before ≤ away)
            h = _spread(before, 8, r) + [ninth]
            walkoff = True
        else:
            h = _spread(home_runs, 8, r) + ['X']
            walkoff = False
    else:
        h = _spread(home_runs, 9, r)
        walkoff = False
    us_line, them_line = (h, a) if home == 'us' else (a, h)
    hits = lambda runs: runs + r.randint(2, 6) + (runs // 3)                      # noqa: E731
    return {'us': us_line, 'them': them_line,
            'rhe': {'us': [us, hits(us), r.choice((0, 0, 0, 1, 1, 2))], 'them': [them, hits(them), r.choice((0, 0, 0, 1, 1, 2))]},
            'walkoff': walkoff}


class Me:
    """내가 나서는 경기의 기록을 만드는 쪽 — 호출하는 곳(rookie_lite)이 능력치·보직을 넘겨준다."""

    def __init__(self, role: str, stats: dict, position: str, duty: tuple, lvl: float):
        self.role, self.stats, self.position, self.lvl = role, stats, position, lvl
        self.duty_role, self.slot = duty[0], duty[1]
        self.starts = 0

    def appear(self, i: int, r):
        """None 이면 이 경기는 나오지 않는다."""
        if self.role == 'batter':
            role = self.duty_role if self.duty_role != 'bench' else 'bench'
            return M.batter_game(self.stats, self.position, self.lvl, r, role=role, slot=self.slot or 7)
        if self.duty_role == 'sp':
            turn = max(0, min(3, (self.slot or 1) - 1))       # 가을야구는 4선발 — 내 순번 경기에 선발
            return M.starter_game(self.stats, self.lvl, r) if i % 4 == turn else None
        if r.random() < .55:
            return M.relief_game(self.stats, self.lvl, r, self.duty_role if self.duty_role in M.RELIEF else 'mop')
        return None

    def label(self, out) -> str:
        if not out:
            return ''
        if self.role == 'batter':
            return L.bat_summary(out['line'])
        return out.get('summary') or L.pit_summary(out['line'])


def _clamp_line(role: str, line: dict, us: int, them: int) -> dict:
    line = dict(line)
    if role == 'batter':
        for k in ('r', 'rbi'):
            line[k] = min(int(line.get(k, 0)), us)
        line['hr'] = min(int(line.get('hr', 0)), us, int(line.get('h', 0)))
    else:
        line['r'] = min(int(line.get('r', 0)), them)
        line['er'] = min(int(line.get('er', line.get('r', 0))), line['r'])
        won = us > them
        if (won and line.get('l')) or (not won and (line.get('w') or line.get('sv') or line.get('hld'))):
            for k in ('w', 'l', 'sv', 'hld'):
                line.pop(k, None)
    return line


def game(no: int, won: bool, home: str, me: Me | None, r, tries: int = 40) -> dict:
    """한 경기 — 승패는 정해져 있고, 내 기록은 그 승패가 나오는 경기에서 뽑는다."""
    out = None
    us = them = None
    if me is not None:
        for _ in range(tries):
            cand = me.appear(no, r)
            if cand is None:
                out = None
                break
            out = cand
            tr, orr = int(cand.get('team_runs', 0)), int(cand.get('opp_runs', 0))
            if tr != orr and (tr > orr) == won:
                us, them = tr, orr
                break
    if us is None:
        us, them = _score(won, r)
    mine = None
    if out:
        line = _clamp_line(me.role, out['line'], us, them)
        mine = {'line': {k: v for k, v in line.items() if k not in L.META_KEYS},
                'text': L.bat_summary(line) if me.role == 'batter' else L.pit_summary(line)}
    g = {'no': no + 1, 'home': home, 'won': won, 'score': [us, them], 'me': mine}
    g.update(linescore(us, them, home, r))
    return g


def moment_game(no: int, won: bool, moment: dict, r) -> dict:
    """결정적 순간이 들어 있는 경기 — 장면(이닝·공수·장면 전후 점수)과 맞는 홈/원정·이닝별 점수.
    타자 9회말 = 우리 홈(끝내기), 투수 9회말·7회말 = 우리 원정(상대가 말 공격), 타자 8회초 = 우리 원정."""
    inning = moment.get('inning') or '9회말'
    m = re.match(r'(\d+)회(초|말)', inning)
    num, bottom = (int(m.group(1)), m.group(2) == '말') if m else (9, True)
    side = moment.get('side', 'bat')
    home = 'us' if (side == 'bat') == bottom else 'them'
    before = list(moment.get('before') or [0, 0])
    after = list(moment.get('after') or before)
    us, them = after
    if us == them or (us > them) != won:                       # 장면 뒤에도 경기가 이어져 승패가 갈렸다
        if won:
            us = max(us, them + 1)
        else:
            them = max(them, us + 1)
    batting_us = side == 'bat'
    a_us = _spread(before[0], num - 1, r) + [0] * (9 - num + 1)
    a_them = _spread(before[1], num - 1, r) + [0] * (9 - num + 1)
    (a_us if batting_us else a_them)[num - 1] += (after[0] - before[0]) if batting_us else (after[1] - before[1])
    for arr, extra in ((a_us, us - after[0]), (a_them, them - after[1])):    # 장면 뒤 점수는 남은 이닝(없으면 그 이닝)에
        if extra > 0:
            later = list(range(num, 9)) or [num - 1]
            for _ in range(extra):
                arr[r.choice(later)] += 1
    home_arr = a_us if home == 'us' else a_them
    away_total = them if home == 'us' else us
    home_total = us if home == 'us' else them
    walkoff = home_total > away_total and bottom and num == 9 and ((side == 'bat') == (home == 'us'))
    if home_total > away_total and not walkoff and sum(home_arr[:8]) > away_total:
        home_arr[8] = 'X'                                       # 9회초가 끝났을 때 이미 앞서 있었다
    hits = lambda runs: runs + r.randint(2, 6) + (runs // 3)    # noqa: E731
    return {'no': no + 1, 'home': home, 'won': won, 'score': [us, them], 'us': a_us, 'them': a_them,
            'rhe': {'us': [us, hits(us), r.choice((0, 0, 0, 1))], 'them': [them, hits(them), r.choice((0, 0, 0, 1))]},
            'walkoff': bool(walkoff), 'me': {'line': {}, 'text': moment.get('line', '')},
            'moment': {'stage': moment.get('stage', ''), 'inning': inning, 'ok': moment.get('ok')}}


# ───────────────────────────── 시리즈
def _series_seq(p: float, need: int, cap: int, head: tuple, r) -> list:
    """경기마다 이기면 1 — 누가 need 승에 먼저 닿을 때까지(최대 cap 경기, 그래도 못 가리면 상위 시드)."""
    w = list(head)
    seq = []
    while max(w) < need and len(seq) < cap:
        x = 1 if r.random() < p else 0
        seq.append(x)
        w[0 if x else 1] += 1
    return seq


def _wins(seq, head) -> list:
    return [head[0] + sum(seq), head[1] + len(seq) - sum(seq)]


def _home(i: int, us_higher: bool, cap: int = 7) -> str:
    """상위 시드 홈 배정 — 7전 2-3-2, 6전 2-2-2, 5전 2-2-1, 3전 1-1-1, 2전(KBO 와일드카드)은 모두 상위 시드 홈."""
    higher_home = {7: (0, 1, 5, 6), 6: (0, 1, 4, 5), 5: (0, 1, 4), 3: (0, 2), 2: (0, 1)}.get(cap, (0, 1, 5, 6))
    at_higher = i in higher_home
    return 'us' if at_higher == us_higher else 'them'


def round_doc(league: str, idx: int, opp: dict, seq: list, head: tuple, us_higher: bool, me: Me | None, r,
              status: str = '') -> dict:
    code, name, cap, need = ROUNDS[league][idx]
    games = [game(i, bool(x), _home(i, us_higher, cap), me, r) for i, x in enumerate(seq)]
    wins = _wins(seq, head)
    result = status or ('won' if wins[0] >= need or (wins[0] == wins[1] and us_higher and len(seq) >= cap)
                        else 'lost' if wins[1] >= need or len(seq) >= cap else 'pending')
    return {'code': code, 'name': name, 'format': f'{cap}전 {need}선승제' if cap != 2 else '2전(1승 우위)',
            'need': need, 'cap': cap, 'us_higher': us_higher, 'head': list(head), 'opponent': opp, 'wins': wins,
            'result': result, 'games': games}


def postseason(c, league: str, rank: int, reached_final: bool, me: Me | None, standings=None,
               kbo_games: list | None = None) -> dict:
    """결승 전까지의 라운드(결승에 올랐으면 결승 라운드는 '진행 중'으로 남긴다 — 결정적 순간이 이어 받는다)."""
    r = rng_for(c, f'post:{league}')
    rounds = ROUNDS.get(league)
    if not rounds:
        return {}
    teams = _clubs(league, c.club)
    r.shuffle(teams)
    docs = []
    if league == 'kbo1' and kbo_games is not None:
        for idx, opp_code, seq, head, higher in kbo_games:
            docs.append(round_doc(league, idx, team_of(league, opp_code), seq, head, higher, me, r))
    else:
        start = entry_round(league, rank)
        plan = None
        for _attempt in range(400):                                    # 결과(결승 진출 여부)에 맞는 흐름이 나올 때까지
            trial, alive = [], True
            for idx in range(start, len(rounds) - 1):
                opp_rank = max(1, rank + r.choice((-3, -2, -1, 1, 2, 3)))
                higher = rank < opp_rank
                head = _head_start(league, rounds[idx][0], higher)
                seq = _series_seq(_p_game(rank, opp_rank), rounds[idx][3], rounds[idx][2], head, r)
                w = _wins(seq, head)
                won = w[0] >= rounds[idx][3] or (w[0] == w[1] and higher)
                trial.append((idx, seq, head, higher))
                if not won:
                    alive = False
                    break
            if alive == reached_final:
                plan = trial
                break
        if plan is None:                                               # 아주 드물게 — 정해진 결과대로 바로 만든다
            plan = []
            for idx in range(start, len(rounds) - 1):
                need = rounds[idx][3]
                seq = [1] * need if reached_final else [0] * need
                plan.append((idx, seq, (0, 0), True))
                if not reached_final:
                    break
        for n, (idx, seq, head, higher) in enumerate(plan):
            docs.append(round_doc(league, idx, team_of(league, teams[n % len(teams)]['code']), seq, head, higher, me, r))
    out = {'kind': 'post', 'key': league, 'title': f'{W.short(league)} 포스트시즌', 'rounds': docs,
           'team': team_of(league, c.club), 'result': ''}
    if not reached_final and docs:
        out['result'] = f"{docs[-1]['name']} 탈락"
    return out


def kbo_games(p, standings) -> list:
    """kbo_final 과 같은 씨앗·같은 순서로 다시 굴려 경기마다 승자를 적는다 — 결과가 kbo_final 과 똑같다."""
    if not standings or standings['league'] != 'kbo1':
        return []
    top = standings['rows'][:5]
    rr = random.Random(f'kbo-post:{p.pk}:{standings["year"]}')
    rounds = []

    def series(a, b, need, first=0, idx=0):
        wins, seq = [first, 0], []
        chance = max(.3, min(.7, .53 + (a['pct'] - b['pct']) * .8))
        while max(wins) < need:
            x = 0 if rr.random() < chance else 1
            wins[x] += 1
            seq.append(x)
        winner = a if wins[0] == need else b
        if p.club in (a['club'], b['club']):
            us_a = p.club == a['club']
            mine = [1 - x if us_a else x for x in seq]               # 우리가 이긴 경기 = 1
            head = (first, 0) if us_a else (0, first)
            rounds.append((idx, (b if us_a else a)['club'], mine, head, us_a))
        return winner
    wc = series(top[3], top[4], 2, 1, idx=0)
    semi = series(top[2], wc, 3, idx=1)
    series(top[1], semi, 3, idx=2)
    return rounds


# ───────────────────────────── 결승(결정적 순간이 시리즈를 끝낸다)
# 결정적 순간은 언제나 시리즈를 끝내는 경기에 있다. 장면 전에 정하는 건 그 경기 번호뿐이고, 앞 경기들의 승패는
# 결과(won)가 정해진 뒤에 만든다 — 전광판은 결정적 순간이 끝난 뒤(시즌 결산)에 보이므로 어긋날 일이 없다.
# 경기 수 분포는 실제 7전 4선승제 결승(월드시리즈 역대)과 비슷하게: 4·5·6·7차전 ≈ 17·24·23·36%.
FINAL_LENGTH = {
    4: ((4, .17), (5, .24), (6, .23), (7, .36)),
    3: ((3, .25), (4, .37), (5, .38)),
    2: ((2, .5), (3, .5)),
    1: ((1, 1.0),),
}


def final_open(c, league: str, opp: dict, us_higher: bool, me: Me | None = None, tag: str = 'final') -> dict:
    """결승 — 결정적 순간이 들 경기 번호(N차전)만 먼저 정한다. 앞 경기들은 final_close 가 결과에 맞춰 만든다."""
    r = rng_for(c, f'{tag}:{league}')
    idx = len(ROUNDS[league]) - 1
    code, name, cap, need = ROUNDS[league][idx]
    n = _pick(FINAL_LENGTH[need], r)
    doc = round_doc(league, idx, opp, [], (0, 0), us_higher, None, r, status='pending')
    return {'round': doc, 'moment_game': n}


def final_close(c, opened: dict, won: bool, moment: dict, me: Me | None) -> dict:
    """결정적 순간 뒤 — 앞 경기들(이긴 쪽 need−1 승)을 만들고, 결정적 순간 경기가 시리즈를 끝낸다."""
    r = rng_for(c, 'final-close')
    doc = dict(opened['round'])
    need, cap = doc['need'], doc.get('cap', 7)
    us_higher = doc.get('us_higher', True)
    n = int(opened['moment_game'])
    winner_pre, loser_pre = need - 1, n - need                       # 결정적 순간 전까지의 승수
    seq = [1] * winner_pre + [0] * loser_pre if won else [0] * winner_pre + [1] * loser_pre
    r.shuffle(seq)
    games = [game(i, bool(x), _home(i, us_higher, cap), me, r) for i, x in enumerate(seq)]
    games.append(moment_game(len(games), won, moment, r))
    w = [sum(seq) + int(won), len(seq) - sum(seq) + int(not won)]
    doc.update(games=games, wins=w, result='won' if won else 'lost')
    return doc


# ───────────────────────────── 국제대회 · 아마추어
INTL_FILLER = ('호주', '체코', '네덜란드', '이탈리아', '캐나다', '파나마', '콜롬비아', '중국', '영국', '독일')
INTL_PLAN = {   # 단계: (코드, 이름, 경기 수, 조별이면 진출에 필요한 승수)
    'wbc': (('pool', '1라운드', 4, 3), ('qf', '8강', 1, 0), ('sf', '4강', 1, 0), ('final', '결승', 1, 0)),
    'premier12': (('open', '오프닝 라운드', 5, 3), ('super', '슈퍼라운드', 3, 2), ('final', '결승', 1, 0)),
    'olympics': (('group', '조별리그', 3, 1), ('sf', '준결승', 1, 0), ('final', '결승', 1, 0)),
    'asian': (('group', '조별리그', 3, 2), ('sf', '준결승', 1, 0), ('final', '결승', 1, 0)),
}
# 국제대회 단계(tier) → 어디까지 갔나: 'final' 은 결승(메달 색은 결정적 순간), 그 밖은 탈락 지점
INTL_REACH = {
    'wbc': {'champ': 'final', 'final': 'final', 'semi': 'sf', 'quarter': 'qf', 'out': 'pool'},
    'premier12': {'champ': 'final', 'final': 'final', 'semi': 'bronze', 'out': 'super'},
    'olympics': {'gold': 'final', 'silver': 'final', 'bronze': 'bronze_won', 'out': 'bronze_lost'},
    'asian': {'gold': 'final', 'silver': 'final', 'bronze': 'bronze_won', 'out': 'bronze_lost'},
}


def _countries(key: str, r, n: int) -> list:
    from .rookie_lite import INTL_FIELD
    field = [x[0] for x in INTL_FIELD.get(key, ())]
    pool = field + [x for x in INTL_FILLER if x not in field]
    r.shuffle(pool)
    strong = [x for x in field]
    r.shuffle(strong)
    return (strong + [x for x in pool if x not in strong])[:max(n, 1)]


def _group(cap: int, need: int, advance: bool, r) -> list:
    for _ in range(300):
        seq = [1 if r.random() < .62 else 0 for _ in range(cap)]
        if (sum(seq) >= need) == advance:
            return seq
    return [1] * need + [0] * (cap - need) if advance else [0] * cap


def intl(c, key: str, tier: str, me: Me | None) -> dict:
    """국제대회 흐름 — 결승이면 결승 경기는 비워 둔다(결정적 순간이 메달 색을 정한다)."""
    r = rng_for(c, f'intl:{key}')
    plan = INTL_PLAN[key]
    reach = INTL_REACH[key].get(tier, plan[0][0])
    opps = _countries(key, r, 12)
    stages, k, n = [], 0, 0

    def opp():
        nonlocal k
        k += 1
        return {'code': '', 'name': opps[(k - 1) % len(opps)], 'short': opps[(k - 1) % len(opps)], 'color': ''}

    def single(code, name, won):
        nonlocal n
        g = game(n, won, 'us' if r.random() < .5 else 'them', me, r)
        n += 1
        return {'code': code, 'name': name, 'format': '단판', 'need': 1, 'head': [0, 0], 'opponent': opp(),
                'wins': [int(won), int(not won)], 'result': 'won' if won else 'lost', 'games': [g]}

    for code, name, cap, need in plan:
        if code == 'final':
            if reach == 'final':
                stages.append({'code': code, 'name': name, 'format': '단판', 'need': 1, 'head': [0, 0], 'opponent': opp(),
                               'wins': [0, 0], 'result': 'pending', 'games': []})
            break
        if need:                                                          # 조별·라운드로빈
            stop_here = reach == code
            seq = _group(cap, need, not stop_here, r)
            games = []
            for x in seq:
                g = game(n, bool(x), 'us' if r.random() < .5 else 'them', me, r)
                g['opponent'] = opp()
                games.append(g)
                n += 1
            stages.append({'code': code, 'name': name, 'format': f'{cap}경기', 'need': need, 'head': [0, 0],
                           'opponent': None, 'wins': [sum(seq), cap - sum(seq)],
                           'result': 'lost' if stop_here else 'won', 'games': games})
            if stop_here:
                break
            continue
        lose_here = reach == code or (code == 'sf' and reach.startswith('bronze'))
        stages.append(single(code, name, not lose_here))
        if lose_here:
            if reach.startswith('bronze'):
                stages.append(single('bronze', '동메달 결정전', reach == 'bronze_won'))
            break
    if reach == 'bronze' and key == 'premier12':                          # 슈퍼라운드 3·4위 → 3·4위전
        stages.append(single('bronze', '3·4위전', r.random() < .5))
    from .rookie_lite import INTL
    return {'kind': 'intl', 'key': key, 'title': INTL[key]['name'], 'rounds': stages,
            'team': {'code': 'kor', 'name': '대한민국', 'short': '대한민국', 'color': '#CD2E3A'}, 'result': ''}


AMATEUR_ROUNDS = {'hs': ('1회전', '16강', '8강', '4강'), 'univ': ('예선', '8강', '4강')}


def amateur(c, league: str, name: str, won: bool | None, me: Me | None) -> dict:
    """아마추어 대회 결승 — 결승 전까지 다 이겼다. won 이 None 이면 결승은 결정적 순간이 정한다."""
    r = rng_for(c, f'amateur:{name}')
    schools = [s for _reg, s in W.schools(league) if s != getattr(c, 'club', '')]
    r.shuffle(schools)
    stages = []
    for n, rd in enumerate(AMATEUR_ROUNDS.get(league, ('8강', '4강'))):
        g = game(n, True, 'us' if r.random() < .5 else 'them', me, r)
        stages.append({'code': f'r{n}', 'name': rd, 'format': '단판', 'need': 1, 'head': [0, 0],
                       'opponent': {'code': '', 'name': schools[n % len(schools)] if schools else '상대 학교',
                                    'short': '', 'color': ''},
                       'wins': [1, 0], 'result': 'won', 'games': [g]})
    final = {'code': 'final', 'name': '결승', 'format': '단판', 'need': 1, 'head': [0, 0],
             'opponent': {'code': '', 'name': schools[-1] if schools else '상대 학교', 'short': '', 'color': ''},
             'wins': [0, 0], 'result': 'pending', 'games': []}
    if won is not None:
        g = game(len(stages), won, 'us' if r.random() < .5 else 'them', me, r)
        final.update(wins=[int(won), int(not won)], result='won' if won else 'lost', games=[g])
    stages.append(final)
    return {'kind': 'amateur', 'key': name, 'title': name, 'rounds': stages,
            'team': {'code': '', 'name': getattr(c, 'club', ''), 'short': '', 'color': ''},
            'result': ('우승' if won else '준우승') if won is not None else ''}


def close_single(c, doc: dict, won: bool, moment: dict) -> dict:
    """국제대회·아마추어 결승(단판) — 결정적 순간 경기 하나로 끝난다."""
    r = rng_for(c, f'single-close:{doc.get("key")}')
    doc = dict(doc)
    rounds = [dict(x) for x in doc['rounds']]
    last = rounds[-1]
    g = moment_game(sum(len(x['games']) for x in rounds[:-1]), won, moment, r)
    last.update(games=[g], wins=[int(won), int(not won)], result='won' if won else 'lost')
    rounds[-1] = last
    doc['rounds'] = rounds
    return doc


def series_doc() -> str:
    """전광판이 읽는 기록 형식(Codex 디자인 인계용)."""
    return __doc__ + """
LiteSeason.series = [
  {kind: 'post'|'intl'|'amateur', key: 리그 코드·대회 키·대회 이름, title: '…', result: '우승'|'준우승'|'… 탈락'|'금메달'…,
   team: {code,name,short,color},                      # 우리 팀(국가대표면 대한민국)
   rounds: [
     {code, name: '한국시리즈', format: '7전 4선승제', need: 4, head: [우리 선승, 상대 선승],
      opponent: {code,name,short,color}|None(조별), wins: [우리, 상대], result: 'won'|'lost'|'pending',
      games: [
        {no: 1, home: 'us'|'them', won: bool, score: [우리, 상대],
         us: [이닝별 득점…] (홈 팀이 이기면 9회말 'X'), them: [...], rhe: {us: [R,H,E], them: [R,H,E]}, walkoff: bool,
         me: {line: {경기 기록 키}, text: '4타수 2안타 1타점'} | None(결장),
         moment?: {stage, inning, ok}, opponent?: {...}(조별 경기)}
      ]}
  ]}
]"""


def demo(role: str = 'batter') -> list:
    """디자인 작업용 견본(미리보기 장면) — DB 없이 실제 시뮬레이터로 만든다: KBO 가을야구(한국시리즈 우승), WBC 결승, 고교 대회."""
    from types import SimpleNamespace
    role = role if role in ('batter', 'pitcher') else 'batter'
    c = SimpleNamespace(pk=7, year=5, club='lg', league='kbo1')
    keys = M.BAT if role == 'batter' else M.PIT
    stats = {k: 74.0 for k in keys}
    me = Me(role, stats, 'SS' if role == 'batter' else 'SP', ('lower', 6) if role == 'batter' else ('sp', 1),
            W.level('kbo1') + POST_LEVEL)
    post = postseason(c, 'kbo1', 3, True, me)
    opened = final_open(c, 'kbo1', team_of('kbo1', 'kia'), False, me)
    final = final_close(c, opened, True, {'before': [3, 4], 'after': [5, 4], 'side': 'bat', 'game_won': True, 'line': '9회말 2사 2·3루 · 끝내기 2타점 적시타',
                                          'stage': f"한국시리즈 {opened['moment_game']}차전", 'inning': '9회말', 'ok': True}, me)
    post['rounds'] = post['rounds'] + [final]
    post['result'] = '한국시리즈 우승!'
    wbc = intl(c, 'wbc', 'champ', me)
    wbc = close_single(c, wbc, True, {'before': [2, 2], 'after': [3, 2], 'side': 'bat', 'line': '8회초 1사 3루 · 결승 희생플라이', 'stage': 'WBC 결승',
                                       'inning': '8회초', 'ok': True})
    wbc['result'] = 'WBC 우승'
    hs = amateur(SimpleNamespace(pk=7, year=2, club='덕수고', league='hs'), 'hs', '봉황대기', True,
                 Me(role, {k: 60.0 for k in keys}, me.position, me.duty_role and ('lower', 4) or ('lower', 4), W.level('hs')))
    return [post, wbc, hs]
