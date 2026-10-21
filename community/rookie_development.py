"""고졸 미국 직행 선수의 초기 적응. 성인 포스팅·대졸에게는 적용하지 않는다."""
from . import rookie_world as W


def mark_entry(p, source, system):
    from . import rookie_story as S
    if source != 'hs' or system != 'mlb':
        return
    data = S.state(p)
    data['development_route'] = dict(kind='hs_us', age=p.age, league=p.league)
    S.put(p, data)


def multiplier(p):
    from . import rookie_story as S
    if not (S.state(p).get('development_route') or {}).get('kind') == 'hs_us':
        return 1.0
    if p.league not in ('mlb_a', 'mlb_aa') or p.age >= 24:
        return 1.0
    # 역대급 재능도 약간의 적응은 필요하지만, 보통 유망주는 맞춤 코칭이 부족하다.
    elite = min(1, max(0, (p.potential - 82) / 8))
    base = .50 + elite * .38
    age_relief = max(0, p.age - 20) * .035
    support = min(.08, S.value(p, 'discipline') / 1250)
    return round(min(.95, base + age_relief + support), 3)


def exceptional_school(p, totals, games):
    """충분한 졸업 기록과 경기 수준을 요구한다. 타고난 잠재력만으로 결정하지 않는다."""
    from . import rookie_league as L
    if not totals or games <= 0 or p.ovr < W.level('mlb_a') - 2:
        return False
    if p.role == 'pitcher':
        line = L.pitching(totals)
        return (totals.get('outs', 0) >= games * 1.5 and line['era'] <= 2.0
                and totals.get('so', 0) >= totals.get('outs', 0) * .32)
    line = L.batting(totals)
    return totals.get('pa', 0) >= games * 2.5 and line['avg'] >= .340 and line['ops'] >= 1.050


def view(p):
    mult = multiplier(p)
    if mult == 1:
        return None
    return dict(percent=round(mult * 100), text='고졸 미국 직행 적응기예요. 싱글A·더블A에서는 맞춤 코칭과 생활 지원이 부족해 성장·훈련·경기 경험 효과가 줄어요. 24세부터 이 보정은 끝나요.')
