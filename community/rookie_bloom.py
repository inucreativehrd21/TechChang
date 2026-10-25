"""31세 뒤 라이트 전용 만개. 확률·기간·추가 각성 한 번을 저장 상태로 검증해요.

2026-10-25 사용자 요청: 너무 강해서 '오래 빛을 못 본 선수'에게만 — 최근 프로 3시즌 내리 평범한 성적(평균 대비
z < DULL_Z, 큰 상 없음)이거나 최근 2시즌 내리 하위 리그(퓨처스·육성군·트리플A 이하·NPB 2군)에 있었을 때만 후보가 되고,
후보가 돼도 그 시즌에 제안이 뜰 확률은 APPEAR 예요(선수·시즌마다 고정 — 새로고침으로 다시 뽑지 않아요).
"""
import hashlib
from . import rookie_modes as Modes, rookie_world as W

NORMAL_AWAKEN_AGE = 31
NEAR_LIMIT, YEARS, AGING_KEEP = 6.0, 3, .30
DULL_YEARS, BURIED_YEARS, DULL_Z, APPEAR = 3, 2, 0.3, .30
MAJOR_AWARDS = ('mvp', 'gg', 'ace', 'title', 'rookie', 'ring')

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
    if X.base_stars(c) + X.awakened(c) > 3:
        return False
    gaps = [max(0, X.stat_pot(c, k) - float(c.stats[k])) for k in c.stats]
    return bool(gaps) and sum(gaps) / len(gaps) <= NEAR_LIMIT and overlooked(c)


def overlooked(c):
    """오래 빛을 못 봤나 — 최근 프로 DULL_YEARS 시즌 내리 평범했거나, 최근 BURIED_YEARS 시즌 내리 하위 리그."""
    from . import rookie_lite as X
    if not getattr(c, 'pk', None):
        return False
    pro = [s for s in c.seasons.order_by('-year')[:DULL_YEARS + 3] if W.is_pro(s.league)]

    def minor(s):
        return s.league not in W.TOP_LEAGUES

    def dull(s):
        z = X.perf_z(c.role, s.totals, s.games)
        return (z is None or z < DULL_Z) and not any(a.get('kind') in MAJOR_AWARDS for a in (s.awards or []))
    buried = len(pro) >= BURIED_YEARS and all(minor(s) for s in pro[:BURIED_YEARS])
    stalled = len(pro) >= DULL_YEARS and all(dull(s) for s in pro[:DULL_YEARS])
    return buried or stalled


def appears(c):
    """후보 시즌에 제안이 실제로 뜨나 — 선수·시즌마다 고정된 APPEAR 확률."""
    roll = int(hashlib.sha256(f'bloom-appear:{c.pk}:{c.year}'.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return roll < APPEAR

def offer(c):
    if not ready(c) or not appears(c):
        return None
    from . import rookie_lite as X
    last = c.seasons.order_by('-year').first() if c.pk else None
    z = X.perf_z(c.role, last.totals, last.games) if last and last.totals else None
    odds = min(.75, .55 + (.10 if X.has(c, 'grinder') else 0) + (.05 if z is not None and z >= 0 else 0))
    ident = hashlib.sha256(f'bloom:{c.pk}:{c.year}:{c.age}:{c.potential}'.encode()).hexdigest()[:24]
    from . import rookie_bloom_stories as Stories
    return dict(kind='decision', what='bloom', id=ident, odds=odds, story=Stories.pick(c, ident))

def scene(c):
    p = c.pending or {}
    from . import rookie_bloom_stories as Stories
    result = p.get('what') == 'bloom_result'
    # 이야기는 제안 때 정한 것(예전 저장이면 id 로 고른다) — 도전 전 글과 결과 글이 한 줄기로 이어진다
    story = Stories.render(c, p.get('story') or Stories.pick(c, (p.get('id') or '').split(':')[0]))
    return dict(p, story=story, title=story['title'] if not result else '내 야구는 아직 끝나지 않았어요',
                odds_pct=round(p.get('odds', 0) * 100), result=result,
                bonus=bonus_available(c), years=YEARS, aging_percent=round((1-AGING_KEEP)*100))

def resolve(c, choice, rng):
    from . import rookie_lite as X, rookie as R
    p = c.pending or {}
    if p.get('what') != 'bloom':
        raise X.LiteError('지금은 만개를 선택할 차례가 아니에요.')
    if not ready(c):          # 조건이 바뀌기 전(2026-10-25)에 떠 있던 제안 — 막히지 않게 다음 시즌으로
        c.pending = X.plan_step(c, rng)
        return '만개 조건이 바뀌어 이번 제안은 사라졌어요. 다음 시즌을 준비해요.'
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
    c.pending = dict(kind='decision', what='bloom_result', id=p['id']+':result', ok=ok, changes=changes, story=p.get('story'))
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

