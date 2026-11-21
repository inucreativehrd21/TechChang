"""테크창 삼국지 — 시작 도시 보정(설계 2장: 시작 선택은 지략이되 정답이 뻔하지 않게).

하네스(30판) 결과 시작 후보 셋의 최고점 차가 평균 150점 안팎(최고점의 27%)이었다.
판을 만들 때 작은 빔 탐색으로 세 시작점의 기대 점수를 어림하고, 낮은 쪽에 금·병력을 보태 차를 줄인다.
판은 하루 한 번 만들고(06:05 cron) DB 에 저장하므로 몇 초 걸려도 된다. 보정값은 board['starts'][i]['bonus'] 에 남는다.
"""
from __future__ import annotations

from . import samguk_data as D
from . import samguk_rules as R

BEAM = 20
GOLD_PER_POINT = 5
TROOPS_PER_POINT = 8
GOLD_CAP = 2500
TROOPS_CAP = 5000


def _moves(s: dict) -> list:
    out = []
    for city in R.mine(s):
        c = s['cities'][city]
        if not c['officers']:
            continue
        out.append({'kind': 'develop', 'city': city})
        if s['gold'] >= R.CONSCRIPT_COST:
            out.append({'kind': 'conscript', 'city': city})
        best_pol = max((D.GENERAL[o] for o in c['officers']), key=lambda g: g.pol)
        for code in s['free'].get(city, []) + s['captives'].get(city, []):
            captive = code in s['captives'].get(city, [])
            gold = R.recruit_gold_needed(s, best_pol, D.GENERAL[code], captive)
            if gold is not None:
                out.append({'kind': 'recruit', 'city': city, 'target': code, 'by': best_pol.code, 'gold': gold})
        if c['troops'] > 0:
            party = sorted(c['officers'], key=lambda o: -(D.GENERAL[o].lead + D.GENERAL[o].war))[:3]
            for dst in R.links(s, city):
                if s['cities'][dst]['owner'] != R.ME:
                    out.append({'kind': 'attack', 'from': city, 'to': dst, 'officers': party, 'troops': c['troops']})
    return out


def _value(s: dict) -> float:
    troops = sum(s['cities'][c]['troops'] for c in R.mine(s))
    return R.score(s)['total'] + troops / 120 + s['gold'] / 150


def estimate(board: dict, start: int, faction: str = 'qun', seed: int = 1) -> int:
    """그 시작점에서 기본 군령으로 낼 수 있는 점수의 어림(운은 고정 시드)."""
    s0 = R.new_run(board, faction, start, seed)
    beam, best = [s0], R.score(s0)['total']
    while beam:
        nxt = []
        for s in beam:
            for mv in _moves(s):
                try:
                    s2, _ = R.apply(board, s, mv)
                except R.RuleError:
                    continue
                best = max(best, R.score(s2)['total'])
                if not s2['over']:
                    nxt.append(s2)
        nxt.sort(key=lambda x: -_value(x))
        beam = nxt[:BEAM]
    return best


def compensate(board: dict) -> dict:
    """낮은 시작점에 금·병력을 보탠다. 세 번 나눠 어림하고, 그중 차가 가장 작았던 보정을 남긴다
    (작은 빔 어림은 흔들려서, 보탠 뒤 오히려 어림이 내려가는 판도 있다). board 를 고쳐 돌려준다."""
    import copy
    n = len(board['starts'])
    est = [estimate(board, i) for i in range(n)]
    best = (max(est) - min(est), [copy.deepcopy(o.get('bonus')) for o in board['starts']], est)
    for _round in range(3):
        top = max(est)
        for i, opt in enumerate(board['starts']):
            gap = top - est[i]
            if gap <= 20:
                continue
            bonus = opt.setdefault('bonus', {'gold': 0, 'troops': 0})
            bonus['gold'] = min(GOLD_CAP, bonus['gold'] + int(gap * GOLD_PER_POINT // 2 // 50 * 50))
            bonus['troops'] = min(TROOPS_CAP, bonus['troops'] + int(gap * TROOPS_PER_POINT // 2 // 100 * 100))
        est = [estimate(board, i) for i in range(n)]
        if max(est) - min(est) < best[0]:
            best = (max(est) - min(est), [copy.deepcopy(o.get('bonus')) for o in board['starts']], est)
    for opt, bonus in zip(board['starts'], best[1]):
        if bonus:
            opt['bonus'] = bonus
        else:
            opt.pop('bonus', None)
    board['start_estimate'] = best[2]
    return board
