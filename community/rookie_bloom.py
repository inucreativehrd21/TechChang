"""31세 뒤 라이트 전용 만개. 확률·기간·추가 각성 한 번을 저장 상태로 검증해요."""
import hashlib
from . import rookie_modes as Modes, rookie_world as W

NORMAL_AWAKEN_AGE = 31
MIN_PRO_YEARS, NEAR_LIMIT, YEARS, AGING_KEEP = 7, 6.0, 3, .30

def state(c):
    return (c.flags or {}).get('bloom') or {}

def succeeded(c):
    return getattr(c, 'mode', 'lite') == Modes.LITE and bool(state(c).get('ok'))

def bonus_available(c):
    return succeeded(c) and not state(c).get('bonus_used')

def aging_multiplier(c):
    bloom = state(c)
    return AGING_KEEP if succeeded(c) and bloom['year'] <= c.year < bloom['year'] + YEARS else 1.0

def ready(c):
    from . import rookie_lite as X
    if getattr(c, 'mode', 'lite') != Modes.LITE or c.retired_at or not W.is_pro(c.league):
        return False
    f, b = c.flags or {}, state(c)
    if c.age <= NORMAL_AWAKEN_AGE or f.get('army') or b.get('attempted') or c.year < b.get('next_year', 0):
        return False
    if X.base_stars(c) + X.awakened(c) > 3 or f.get('pro_years', 0) < MIN_PRO_YEARS:
        return False
    gaps = [max(0, X.stat_pot(c, k) - float(c.stats[k])) for k in c.stats]
    return bool(gaps) and sum(gaps) / len(gaps) <= NEAR_LIMIT

def offer(c):
    if not ready(c):
        return None
    from . import rookie_lite as X
    last = c.seasons.order_by('-year').first() if c.pk else None
    z = X.perf_z(c.role, last.totals, last.games) if last and last.totals else None
    odds = min(.75, .55 + (.10 if X.has(c, 'grinder') else 0) + (.05 if z is not None and z >= 0 else 0))
    ident = hashlib.sha256(f'bloom:{c.pk}:{c.year}:{c.age}:{c.potential}'.encode()).hexdigest()[:24]
    return dict(kind='decision', what='bloom', id=ident, odds=odds)

def scene(c):
    p = c.pending or {}
    result = p.get('what') == 'bloom_result'
    return dict(p, title='늦게 핀 꽃' if not result else '내 야구는 아직 끝나지 않았어요',
                odds_pct=round(p.get('odds', 0) * 100), result=result,
                bonus=bonus_available(c), years=YEARS, aging_percent=round((1-AGING_KEEP)*100))

def resolve(c, choice, rng):
    from . import rookie_lite as X, rookie as R
    p = c.pending or {}
    if p.get('what') != 'bloom' or not ready(c):
        raise X.LiteError('지금은 만개를 선택할 차례가 아니에요.')
    if choice not in ('try', 'skip'):
        raise X.LiteError('다시 도전할지 골라 주세요.')
    if choice == 'skip':
        c.flags = dict(c.flags or {}, bloom=dict(state(c), next_year=c.year+1))
        c.pending = X.plan_step(c, rng)
        return '올해는 내 호흡을 지키기로 했어요. 만개 조건을 유지하면 다음 시즌에 다시 찾아와요.'
    before = dict(potential=c.potential, awaken=int((c.flags or {}).get('awaken', 0)),
                  ovr=c.ovr, stats=dict(c.stats))
    ok = rng.random() < float(p['odds'])
    b = dict(attempted=True, ok=ok, year=c.year, age=c.age, before=before, bonus_used=False)
    c.flags = dict(c.flags or {}, bloom=b)
    changes = []
    if ok:
        c.potential = X.STAR_FLOOR[4]
        # 이전 각성 횟수는 역사로 보존하고, 새 4성 잠재력 뒤의 별만 새로 센다.
        b['awaken_base'] = before['awaken']
        for k, old in list(c.stats.items()):
            new = round(max(float(old), min(X.stat_pot(c, k), X.stat_pot(c, k)*.96)), 1)
            c.stats[k] = new
            delta = round(new-float(old), 1)
            if delta:
                X._note(c, k, delta, '만개 — 쌓아 온 시간의 개화')
                label = next(lab for key, lab, _ in R.ROLES[c.role]['stats'] if key == k)
                changes.append(dict(label=label, before=round(float(old), 1), after=new, delta=delta))
        c.ovr = R.overall(c.role, c.stats)
        c.best_ovr = max(c.best_ovr, c.ovr)
        b['after_ovr'] = c.ovr
        b['changes'] = changes
        text = '만개했어요. 잠재력 4성, 이번 시즌부터 3시즌 동안 노쇠가 70% 줄어요.'
    else:
        text = '기대한 결과에는 닿지 못했지만, 다시 그라운드에 선 오늘까지 사라지는 건 아니에요.'
    c.flags.setdefault('press', []).append(X.press('[만개]' if ok else '[다시 서다]', f'{c.name}, 늦게 찾아온 도전 — '+('마침내 피어나다' if ok else '결과보다 오래 남을 한 걸음')))
    c.pending = dict(kind='decision', what='bloom_result', id=p['id']+':result', ok=ok, changes=changes)
    return text

def consume_bonus(c):
    if not bonus_available(c):
        return False
    c.flags = dict(c.flags or {}, bloom=dict(state(c), bonus_used=True, bonus_year=c.year))
    return True

def retirement_limit(c, normal):
    return max(normal, state(c)['age'] + YEARS - 1) if succeeded(c) else normal

def info(c):
    if not succeeded(c):
        return None
    return dict(left=max(0, state(c)['year']+YEARS-c.year), bonus=bonus_available(c))

