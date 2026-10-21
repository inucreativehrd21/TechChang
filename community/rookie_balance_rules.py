"""커리어 성장·계약 시장 규칙. 원본 기록과 잠재력은 덮어쓰지 않는다."""
import random

from . import rookie_world as W


def state(p):
    return getattr(p, 'flags' if hasattr(p, 'flags') else 'career', None) or {}


def put(p, data):
    attr = 'flags' if hasattr(p, 'flags') else 'career'
    current = getattr(p, attr, None)
    if isinstance(current, dict):
        current.clear()
        current.update(data)
    else:
        setattr(p, attr, data)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def profile(p):
    data = dict(state(p))
    if 'career_profile' not in data:
        rng = random.Random(f'career-v2:{getattr(p, "pk", 0)}:{p.name}:{p.potential}')
        data['career_profile'] = dict(version=2, development=round(rng.uniform(.68, 1.02), 3),
                                      aging=round(rng.uniform(.88, 1.18), 3), stall=rng.randrange(7))
        put(p, data)
    return data['career_profile']


def growth_factors(p):
    prof = profile(p)
    age = p.age
    stalled = age in range(20, 29) and (age + prof['stall']) % 7 == 0
    train = prof['development'] * (.48 if stalled else .78)
    experience = (.28 if age <= 26 else .12) * (.5 if stalled else 1)
    return train, experience, prof['aging'], stalled


def game_stats(p, stats):
    """소모·해외 적응·접근 수정은 해당 시즌 실전에만 반영한다."""
    out, data = dict(stats), state(p)
    burden = clamp(float(data.get('workload', 0)), 0, 2)
    if p.role == 'pitcher':
        out['stamina'] -= burden
        out['control'] -= burden * .25
    else:
        out['speed'] -= burden * .5
        out['contact'] -= burden * .2
    adaptation = data.get('mlb_adaptation', 0) if hasattr(p, 'flags') else data.get('mlb_service', 0)
    if p.league == 'mlb' and adaptation < 2:
        key = 'eye' if p.role == 'batter' else 'control'
        out[key] -= 1.2 * (1 - adaptation / 2)
    approach = data.get('approach_year') == getattr(p, 'year', getattr(p, 'age_season', 0))
    if approach:
        if p.role == 'batter':
            out['contact'] += 1.5
            out['eye'] += .5
            out['power'] -= 2
        else:
            out['control'] += 1.5
            out['stamina'] += .5
            out['velocity'] -= 2
    return out


def workload_after(p, rows):
    data = dict(state(p))
    if p.role == 'pitcher':
        quantity = sum(r['totals'].get('outs', 0) / 3 for r in rows)
        full = 165 if p.position == 'SP' else 65
    else:
        quantity = sum(r['totals'].get('pa', 0) for r in rows)
        full = 600
    carry = max(0, quantity / full - .65) * .8 + float(data.get('workload', 0)) * .35
    data['workload'] = round(clamp(carry, 0, 2), 2)
    if any(r['league'] == 'mlb' and r['totals'].get('g', 0) for r in rows):
        data['mlb_adaptation'] = min(2, data.get('mlb_adaptation', 0) + 1)
    put(p, data)


def top_splits(season):
    """옛 시즌도 구간 소속을 우선하고 하위 리그와 최상위 기록을 분리한다."""
    rows = season.splits or []
    if rows:
        return [r for r in rows if r.get('league') in W.TOP_LEAGUES]
    if season.league in W.TOP_LEAGUES:
        return [dict(league=season.league, totals=season.totals, war=season.war,
                     G=season.games, role='sp' if season.totals.get('gs') else '')]
    return []


def totals(p, system=None):
    from . import rookie_league as L
    total, war, years = {}, 0.0, 0
    for season in p.seasons.all():
        rows = [r for r in top_splits(season) if system is None or W.system_of(r['league']) == system]
        if rows:
            years += 1
        for row in rows:
            total = L.add(total, row.get('totals') or {})
            war += row.get('war', 0)
    return dict(totals=total, war=round(war, 1), seasons=years)


def recent(p, system=None):
    """최근 실전의 레벨·표본을 구분한다. 시즌 WAR를 다른 리그 연봉에 그대로 쓰지 않는다."""
    from . import rookie_league as L
    if hasattr(p, 'flags') and hasattr(p, 'seasons') and getattr(p, 'pk', None):
        seasons = list(p.seasons.order_by('-year')[:3])
        rows = [r for s in seasons for r in (s.splits or [dict(league=s.league, totals=s.totals, war=s.war, G=s.games)])
                if system is None or W.system_of(r['league']) == system]
    elif getattr(p, 'pk', None) and hasattr(p, 'season_stats'):
        rows = [dict(league=r.league, totals=r.totals, war=r.war, G=144)
                for r in p.season_stats.order_by('-season__number')[:3]
                if system is None or W.system_of(r.league) == system]
    else:
        rows = []
    total, war, games = {}, 0, 0
    for row in rows:
        total = L.add(total, row.get('totals') or {})
        level_scale = min(1, W.level(row['league']) / W.level('kbo1'))
        war += row.get('war', 0) * level_scale ** 3
        games += row.get('G', 0)
    return total, war / max(1, games / 144), games


def market_score(p):
    from . import rookie_league as L
    s = p.stats
    t, _war, _g = recent(p)
    if p.role == 'batter':
        skill = .27 * s['contact'] + .25 * s['eye'] + .3 * s['power'] + .1 * s['defense'] + .08 * s['speed']
        pa = t.get('pa', 0)
        form = clamp((L.batting(t)['ops'] - .80) * 12, -2, 2) * min(1, pa / 650)
        sample = pa >= 350
    else:
        skill = .27 * s['velocity'] + .3 * s['control'] + .25 * s['breaking'] + .1 * s['mental'] + .08 * s['stamina']
        ip = t.get('outs', 0) / 3
        form = clamp((3.6 - L.pitching(t)['era']) * .65, -2, 2) * min(1, ip / 140)
        sample = ip >= (90 if p.position == 'SP' else 40)
    age = max(0, p.age - 29) * .45
    reputation = min(.6, float(state(p).get('intl_rep', 0)) * .01)
    return round(skill + form - age + reputation, 2), sample


def overseas_level(p, system):
    score, sampled = market_score(p)
    if system == 'mlb':
        if sampled and score >= 78:
            return 'mlb'
        return 'mlb_aaa' if score >= 67.5 and p.age <= 31 else None
    if system == 'npb':
        return 'npb1' if sampled and score >= 68 else 'npb2' if score >= 63 and p.age <= 29 else None
    return None


def annual(p, league, performance=0, service=0):
    """만원. 현재 리그의 역할·성적과 계약 단계를 반영한다."""
    fame = min(.1, float(state(p).get('fame', 0)) / 1000)
    w = clamp(performance, 0, 9)
    age_discount = max(.45, 1 - max(0, p.age - 31) * .09)
    if league == 'kbo1':
        pay = (3500 + 4200 * w ** 1.15) * min(1, .52 + service * .08)
    elif league == 'mlb':
        # 원화 환산 게임 가격이며 실제 환율을 실시간으로 사용하지 않는다.
        pay = (110000 if service < 3 else 110000 + 22000 * w ** 1.2 if service < 6
               else 130000 + 60000 * w ** 1.2)
    elif league == 'npb1':
        pay = 6000 + 8500 * w ** 1.18
    else:
        pay = dict(kbo3=3000, kbo2=3500, mlb_a=2200, mlb_aa=2800, mlb_aaa=4000, npb2=3500, cpbl=6500).get(league, 3000)
    floor = 110000 if league == 'mlb' else 3000 if league in ('kbo1', 'kbo2', 'kbo3') else 0
    return max(floor, int(pay * age_discount * (1 + fame)))


def fa_terms(p, war):
    years = 3 if p.age <= 29 and war >= 3 else 2 if p.age <= 32 and war >= 1.5 else 1
    annual_pay = annual(p, 'kbo1', war, 9)
    return years, int(annual_pay * (1.18 if war >= 2 else 1))


def retention(p, season):
    """연 단위 수요 평가. 젊은 유망주·병역은 보호하며 실패한 시즌의 누적을 본다."""
    if not W.is_pro(p.league) or state(p).get('army') or p.age < 22:
        return None
    if not season or season.games == 0:
        return None
    data = dict(state(p))
    year = getattr(p, 'year', getattr(p, 'age_season', 0))
    if data.get('market_review_year') == year:
        return None
    data['market_review_year'] = year
    top = W.SYSTEMS[W.system_of(p.league)][-1]
    deficit = W.level(top) - p.ovr
    t, form, _g = recent(p)
    weak = deficit > 5 or form < .3
    data['weak_years'] = int(data.get('weak_years', 0)) + 1 if weak else 0
    young = p.age <= 25
    risk = .035 + max(0, p.age - 26) * .055 + max(0, deficit - 3) * .022
    risk += max(0, data['weak_years'] - 1) * (.035 if young else .055)
    risk -= clamp(form, 0, 6) * .018
    if young:
        risk *= .45
    if deficit < -5 and form >= 3:
        risk *= .25
    pressure = clamp(risk, 0, .78)
    data['market_pressure'] = round(pressure, 3)
    put(p, data)
    return pressure


def income_record(p, salary, advertising=0, bonus=0):
    data = dict(state(p))
    income = dict(data.get('career_income') or {})
    for key, amount in [('salary', salary), ('advertising', advertising), ('bonus', bonus)]:
        income[key] = income.get(key, 0) + int(amount)
    data['career_income'] = income
    put(p, data)


def contract_years(p, war):
    return 3 if p.age < 30 and war >= 3 else 2 if p.age < 33 and war >= 1 else 1


def market_event(p, pressure):
    data = state(p)
    choices = []
    if data.get('market_retries', 0) < 2:
        choices.append(dict(key='retry', label='낮은 조건으로 테스트를 받을게요',
                            hint='최근 성적·나이·실력으로 재계약을 평가해요. 실패하면 현역 생활을 마쳐요'))
    if not data.get('rebuild_used'):
        choices.append(dict(key='rebuild', label='역할과 무대를 낮춰 다시 준비할게요',
                            hint='한 번의 재정비 기회예요. 하위 리그·불펜·백업에서 낮은 연봉으로 도전해요'))
    choices.append(dict(key='retire', label='현역 생활을 마칠게요', hint='지금까지의 기록과 선수 카드를 남겨요'))
    return dict(kind='career_market', background='manager-office', pressure=pressure,
                title='구단의 다음 시즌 전력 구상',
                text='최근 출전 내용과 새 경쟁자, 건강·연봉을 함께 검토했어요. 지금 역할을 그대로 보장하기 어려워요. 다음 길을 정해야 해요.',
                choices=choices)


def settle_guarantee(p):
    """로스터 탈락으로 남은 보장 급여를 소멸시키지 않는다. 은퇴 때 한 번 정산한다."""
    data = dict(state(p))
    deal = data.pop('contract', None) or {}
    guaranteed = deal.get('minor_annual', 0) if deal.get('split') else deal.get('annual', 0)
    owed = int(guaranteed * max(0, deal.get('years', 0)))
    if owed:
        data['guarantee_settlement'] = data.get('guarantee_settlement', 0) + owed
        if hasattr(p, 'earnings'):
            from .rookie_lite import income_tax
            p.earnings += owed
            data['cash'] = int(data.get('cash', p.earnings - owed)) + owed - income_tax(owed)
        else:
            data['mlb_contract_income'] = data.get('mlb_contract_income', 0) + owed
    put(p, data)
    return owed


def market_reply(p, event, selected, rng, *, defer_failure=False):
    from . import rookie_story as S
    from . import rookie_pitching as P
    if selected not in [c['key'] for c in event['choices']]:
        raise ValueError('현재 구단이 제시한 선택지를 골라 주세요.')
    data = dict(state(p))
    if selected == 'rebuild':
        data['rebuild_used'] = True
        data['weak_years'] = 0
        data['workload'] = 0
        put(p, data)
        if p.role == 'pitcher' and p.position == 'SP':
            from django.utils import timezone
            P.set_track(p, 'RP', getattr(p, 'year', timezone.localdate().toordinal()), '출전 기회를 위해 불펜으로 전환했어요.')
        else:
            previous = W.prev_league(p.league)
            if previous:
                p.league = previous
            if hasattr(p, 'lineup'):
                p.lineup, p.slot = ('bench', 0) if p.role == 'batter' else ('chase', 0)
        return S.change(p, '한 번의 재정비 기회를 얻었어요. 낮은 역할에서 다시 증명해요.', confidence=-2)
    if selected == 'retry':
        data['market_retries'] = data.get('market_retries', 0) + 1
        put(p, data)
        top = W.level(W.SYSTEMS[W.system_of(p.league)][-1])
        chance = clamp(.55 + (p.ovr - top) * .035 - max(0, p.age - 29) * .025, .08, .8)
        if rng.random() < chance:
            return S.change(p, '테스트를 통과해 한 시즌의 경쟁 기회를 얻었어요.', confidence=3)
        if defer_failure:
            data = dict(state(p))
            data['market_test_failed'] = True
            put(p, data)
            return '테스트를 통과하지 못했어요. 재정비 기회가 남았다면 낮은 역할에서 다시 준비할 수 있어요.'
    owed = settle_guarantee(p)
    if hasattr(p, 'flags'):
        from .rookie_lite import retire
        retire(p, '재계약 실패' if selected != 'retire' else '스스로')
    else:
        from .rookie_career import retire_player
        retire_player(p, '구단 수요 감소로 현역 생활을 마쳤어요')
    return '현역 생활을 마쳤어요. 기록과 선수 카드를 남겼어요.' + (' 남은 보장 급여도 정산했어요.' if owed else '')
