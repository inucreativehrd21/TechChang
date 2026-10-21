"""실제 진행 함수를 임시 테스트 DB에서 100개 커리어 끝까지 실행한다."""
import copy
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import setup_databases, teardown_databases

from community import rookie_lite as X
from community import rookie_league as L
from community import rookie_sim as M
from community import rookie_world as W
from community import rookie_development as D
from community import rookie_story as S
from community import rookie_balance_rules as B
from community.models import LiteSeason


def choose(c, rng, policy):
    p = c.pending
    what = p['what']
    if what == 'meeting':
        opts = X.decision_view(c)['choices']
        keys = [ch['key'] for ch in opts]
        if p.get('pitch_event'):
            return 'test' if 'test' in keys else 'accept' if 'accept' in keys else 'course' if 'course' in keys else 'stay'
        if p.get('market_event'):
            return 'rebuild' if 'rebuild' in keys and policy == 'playing' else 'retry' if 'retry' in keys else 'retire'
        if 'refuse' in keys and policy == 'bold':
            return 'refuse'
        preferred = {'manager': 'team_work', 'interview': 'team', 'conduct': 'rest', 'rival': 'together', 'highlight': 'short'}
        return next((key for key in ('accept', preferred.get(p.get('about')), 'team_work', 'team', 'rest', 'together', 'short', 'break', 'modest') if key in keys), keys[0])
    if what == 'moment':
        m = p['moments'][p.get('i', 0)]
        return ('fast' if m['opp'].get('fast', 50) >= 50 else 'break') if m['side'] == 'bat' else 'break'
    if what == 'draft':
        abroad = p.get('abroad') or {}
        if abroad.get('mlb') and policy in ('us', 'bold'):
            return 'mlb:' + X._teams_of(abroad['mlb'])[0]
        return 'sign' if p.get('offer') else 'develop'
    if what == 'posting':
        if policy == 'domestic':
            return 'stay'
        offers = p.get('offers') or []
        if policy == 'salary':
            return max(offers, key=lambda o: o.get('minor_annual', o['annual']) if o.get('entry_league') == 'mlb_aaa' else o['annual'])['key'] if offers else 'stay'
        if policy == 'playing':
            return next((o['key'] for o in offers if o.get('entry_league') in W.TOP_LEAGUES), 'stay')
        return next((o['key'] for o in offers if o['system'] == 'mlb'), offers[0]['key'] if offers else 'stay')
    if what == 'negotiation':
        return 'minor_veto' if policy == 'bold' and p['deal']['system'] == 'mlb' else 'accept'
    if what == 'contract_optout':
        return 'market' if policy == 'bold' else 'keep'
    if what == 'fa':
        offers = p['offers']
        if policy == 'domestic':
            return 'stay'
        return next((o['key'] for o in offers if o['key'].startswith('mlb')), offers[0]['key'])
    if what == 'military':
        return 'sangmu'
    if what == 'return':
        return p['offers'][0]['key'] if c.age >= 36 and c.ovr < 65 else 'stay'
    if what == 'awaken':
        return 'try'
    if what == 'retire':
        last = c.seasons.order_by('-year').first()
        productive = last and last.war >= 1.5
        return 'continue' if c.age < 34 or productive or (policy == 'playing' and c.age < 37) else 'retire'
    return 'retire'


def run_career(index, seed, policy, stress=None):
    rng = random.Random(seed)
    role = 'batter' if index % 2 == 0 else 'pitcher'
    u = User.objects.create(username=f'balance-{index}-{seed}')
    position = ('C', '1B', '2B', '3B', 'SS', 'OF', 'DH')[(index // 2) % 7] if role == 'batter' else ('SP', 'RP')[(index // 2) % 2]
    style = list(X.STYLES[role])[(index // 4) % 4]
    c = X.create(u, name=f'연습선수{index}', role=role, position=position,
                 style=style, region='서울', team='lg', rng=rng)
    if stress is not None:
        c.potential = stress
        c.stats = {k: round(X.stat_pot(c, k) * X.frac(c, k, c.age), 1) for k in c.stats}
        from community import rookie as R
        c.ovr = c.best_ovr = R.overall(c.role, c.stats)
        c.save()
    initial_potential = c.potential
    decisions = Counter()
    for step in range(260):
        if c.retired_at:
            break
        p = c.pending
        if p['kind'] == 'plan':
            event = p.get('event')
            choice = ''
            if event:
                keys = [item[0] for item in X.EVENTS[event]['choices']]
                preferred = dict(manager='team_work', interview='ambition' if policy == 'salary' else 'team',
                                 conduct='fans' if policy == 'salary' else 'rest', rival='together',
                                 highlight='short' if c.role == 'batter' else 'break').get(event)
                choice = next((key for key in (preferred, 'decline' if policy == 'domestic' else 'accept') if key in keys), None)
                if choice is None:
                    choice = rng.choice(sorted(keys))
            X.run_season(c, X.pick_programs(c, rng), 'normal', choice, rng,
                         intl={k: 'go' if policy != 'steady' else 'skip' for k in p.get('intl') or []})
        elif p['kind'] == 'review':
            X.next_season(c, rng)
        else:
            decisions[p['what']] += 1
            X.decide(c, p['what'], choose(c, rng, policy), rng)
            c.save()
    if not c.retired_at:
        raise AssertionError(f'{index}: 260단계 안에 종료하지 않았어요: {c.pending}')
    rows = list(c.seasons.order_by('year'))
    errors, leagues, levels = [], set(), defaultdict(list)
    for season in rows:
        t = season.totals
        if not all(math.isfinite(float(v)) for v in (season.war, season.ovr_end, season.salary)):
            errors.append('비정상 수치')
        if c.role == 'batter' and not (0 <= t.get('hr', 0) <= t.get('h', 0) <= t.get('ab', 0) <= t.get('pa', 0)):
            errors.append(f'{season.year} 타격 기록 보존')
        if c.role == 'pitcher' and (t.get('w', 0) + t.get('l', 0) > t.get('g', 0)
                                    or t.get('outs', 0) > t.get('g', 0) * 27):
            errors.append(f'{season.year} 투수 기록 보존')
        if W.is_pro(season.league) and season.club != '국군체육부대(상무)':
            if W.PRO_TEAM.get(season.club, {}).get('system') != W.system_of(season.league):
                errors.append(f'{season.year} 구단과 리그 불일치')
        if season.team_of and not (0 <= season.team_w + season.team_l <= season.games and 1 <= season.team_rank <= season.team_of):
            errors.append(f'{season.year} 팀 경기/순위')
        for split in season.splits:
            lg, total = split['league'], split['totals']
            leagues.add(lg)
            line = L.batting(total) if role == 'batter' else L.pitching(total)
            sample = total.get('pa', 0) if role == 'batter' else total.get('outs', 0) / 3
            if sample >= (split['G'] * 2 if role == 'batter' else split['G'] * .3):
                levels[lg].append(dict(avg=line.get('avg'), ops=line.get('ops'), era=line.get('era'),
                                       war=split['war'], hr=total.get('hr', 0), sample=round(sample, 1)))
            world = split.get('table')
            if world:
                table = world['rows']
                if sum(x['w'] for x in table) != sum(x['l'] for x in table):
                    errors.append(f'{season.year} 리그 승패 불일치')
                if sum(x['rf'] for x in table) != sum(x['ra'] for x in table):
                    errors.append(f'{season.year} 리그 득실 불일치')
                if any(x['g'] != world['games'] for x in table):
                    errors.append(f'{season.year} 구단 경기 수 불일치')
                if any(x['w'] + x['l'] + x['d'] != x['g'] for x in table):
                    errors.append(f'{season.year} 구단 승패무 보존')
    season_data = [dict(year=s.year, age=s.age, league=s.league, duty=s.duty, games=s.games,
                        salary=s.salary, war=s.war, totals=s.totals,
                        splits=[{k: part.get(k) for k in ('league', 'role', 'G', 'war', 'totals')} for part in s.splits]) for s in rows]
    majors = B.totals(c)
    mlb_games = sum(r.get('totals', {}).get('g', 0) for s in rows for r in B.top_splits(s) if r['league'] == 'mlb')
    mlb_years = sum(any(r['league'] == 'mlb' and r.get('totals', {}).get('g', 0) for r in B.top_splits(s)) for s in rows)
    return dict(index=index, seed=seed, role=role, position=position, final_position=c.position, style=style,
                policy=policy, stress=stress, potential=initial_potential,
                seasons=len(rows), retired_age=c.age, peak=c.peak, peak_ovr=c.best_ovr, earnings=c.earnings,
                war=c.war, top_war=majors['war'], top_seasons=majors['seasons'], mlb_games=mlb_games,
                mlb_established=mlb_years >= 2, income=c.flags.get('career_income', {}),
                pitch_history=c.flags.get('pitch_history', []), seasons_detail=season_data,
                retirement_reason=c.pending.get('why', ''),
                max_season_war=max([s.war for s in rows] or [0]),
                max_h=max([s.totals.get('h', 0) for s in rows] or [0]),
                max_hr=max([s.totals.get('hr', 0) for s in rows] or [0]), leagues=sorted(leagues),
                max_wins=max([s.totals.get('w', 0) for s in rows] or [0]),
                max_so=max([s.totals.get('so', 0) for s in rows] or [0]),
                hs_us=bool(c.flags.get('development_route')), decisions=dict(decisions),
                levels=dict(levels), errors=errors, json_bytes=len(json.dumps(c.flags, ensure_ascii=False).encode('utf8')))


def calibration():
    out = []
    for gap in (-12, 0, 12, 26):
        b, p = {k: 64 + gap for k in M.BAT}, {k: 64 for k in M.PIT}
        probs = M.pa_probs(b, p)
        hit = sum(probs[k] for k in ('1B', '2B', '3B', 'HR'))
        old = hit / M.HIT_RATE
        out.append(dict(gap=gap, old_h_per_pa=round(old, 5), new_h_per_pa=round(hit, 5), relative=round(hit / old, 4)))
    # 4년간 같은 훈련·출전·난수의 국내/미국 직행 쌍. 완결 커리어와 구분해 보고한다.
    adaptation = []
    from types import SimpleNamespace
    for pot in (76, 84, 90):
        base = SimpleNamespace(pk=None, name='적응표본', flags={}, role='batter', style=list(X.STYLES['batter'])[0],
                               potential=pot, traits=[], age=19, league='kbo2', stats={k: 50.0 for k in M.BAT}, ovr=50, best_ovr=50)
        us = copy.deepcopy(base)
        us.league = 'mlb_a'
        D.mark_entry(us, 'hs', 'mlb')
        for age in range(19, 23):
            for p in (base, us):
                p.age = age
                X.grow(p, ['contact', 'power'], 'normal', .7, 0, random.Random(age))
        adaptation.append(dict(potential=pot, domestic_ovr=base.ovr, us_ovr=us.ovr, difference=round(us.ovr - base.ovr, 2)))
    return dict(hit_rates=out, adaptation=adaptation)


class Command(BaseCommand):
    help = '격리된 SQLite 테스트 DB에서 실제 커리어를 끝까지 진행하고 JSON 보고서를 남겨요.'

    def add_arguments(self, parser):
        parser.add_argument('--runs', type=int, default=100)
        parser.add_argument('--seed', type=int, default=20261020)
        parser.add_argument('--output', default='community/reports/rookie-balance-20261020.json')

    def handle(self, *args, **opts):
        if connection.vendor != 'sqlite' or not settings.SETTINGS_MODULE.endswith('.local'):
            raise CommandError('로컬 SQLite 설정에서만 실행할 수 있어요. 운영 DB에는 실행하지 않아요.')
        if not 1 <= opts['runs'] <= 1000:
            raise CommandError('실행 수는 1~1,000개예요.')
        began = time.monotonic()
        config = setup_databases(verbosity=0, interactive=False)
        records, failures = [], []
        try:
            for i in range(opts['runs']):
                try:
                    records.append(run_career(i, opts['seed'] + i, ('domestic', 'us', 'salary', 'playing')[(i // 2) % 4]))
                except Exception as ex:
                    import traceback
                    failures.append(dict(index=i, error=str(ex), trace=traceback.format_exc()))
                if (i + 1) % 10 == 0:
                    self.stdout.write(f'{i + 1}/{opts["runs"]} 완료 · 오류 {len(failures)}', ending='\n')
                    self.stdout.flush()
            # 보통 분포에서 보기 힘든 최상위 재능의 국내 잔류/직행 경로도 별도 검사.
            stress = []
            if opts['runs'] >= 100:
                for i, (pot, policy) in enumerate([(60, 'domestic'), (60, 'us'), (84, 'domestic'), (84, 'us'), (90, 'domestic'), (90, 'us')]):
                    for side in range(2):
                        n = 1000 + i * 2 + side
                        try:
                            stress.append(run_career(n, opts['seed'] + n, policy, pot))
                        except Exception as ex:
                            failures.append(dict(index=n, error=str(ex)))
            report = dict(seed=opts['seed'], runs=opts['runs'], completed=len(records), failures=failures,
                          seconds=round(time.monotonic() - began, 2), calibration=calibration(), records=records, stress=stress,
                          summary=dict(mean_seasons=round(statistics.mean(r['seasons'] for r in records), 2) if records else 0,
                                       reached_mlb=sum(r['mlb_games'] > 0 for r in records),
                                       established_mlb=sum(r['mlb_established'] for r in records),
                                       mean_retired_age=round(statistics.mean(r['retired_age'] for r in records), 2) if records else 0,
                                       mean_top_war=round(statistics.mean(r['top_war'] for r in records), 2) if records else 0,
                                       median_top_war=round(statistics.median(r['top_war'] for r in records), 2) if records else 0,
                                       mean_earnings=round(statistics.mean(r['earnings'] for r in records), 2) if records else 0,
                                       median_earnings=round(statistics.median(r['earnings'] for r in records), 2) if records else 0,
                                       hs_us=sum(r['hs_us'] for r in records),
                                       invariant_errors=sum(len(r['errors']) for r in records + stress),
                                       max_json_bytes=max([r['json_bytes'] for r in records + stress] or [0])))
            target = Path(opts['output'])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            self.stdout.write(json.dumps({k: report[k] for k in ('runs', 'completed', 'seconds', 'summary')}, ensure_ascii=False))
            if failures or report['summary']['invariant_errors']:
                raise CommandError(f'불변식 또는 진행 오류를 발견했어요. {target}를 확인해 주세요.')
        finally:
            teardown_databases(config, verbosity=0)
