"""경기 환경 하네스 — 같은 시드로 커리어를 환경 끈 채·켠 채(루틴별) 끝까지 돌려 분포가 얼마나 움직이는지 잰다(임시 테스트 DB).

1) 분포 이동: 프로 시즌 타율·OPS·평균자책점·WAR, 커리어 시즌 수·은퇴 나이·최고 OVR·도달 리그·우승 — 평균 차이와 표준오차.
2) 효과가 기록에 보이나: 조건별 성적(홈/원정, 타자 친화/투수 친화, 비/폭염/한파, 강풍 뒷바람/맞바람)의 타율·홈런율·평균자책점.
3) 루틴: 같은 시드로 루틴만 바꿔 WAR 차이.
"""
import json
import math
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.test.utils import override_settings, setup_databases, teardown_databases

from community import rookie_env as Env
from community import rookie_league as L
from community import rookie_lite as X
from community import rookie_world as W
from community.management.commands.evaluate_rookie_series import run as play


def career(index, seed, mode, routine):
    """한 커리어를 트랜잭션 안에서 돌리고 되돌린다(같은 pk·같은 빈 세계에서 비교)."""
    orig = X.run_season

    def with_routine(c, programs, intensity, choice, rng, intl=None, routine_arg=None, **kw):
        return orig(c, programs, intensity, choice, rng, intl=intl, routine=routine)
    X.run_season = with_routine
    try:
        with transaction.atomic():
            sig, tail, _docs, seasons = play(index, seed, mode, routine or 'none')
            from community.models import LiteCareer
            c = LiteCareer.objects.order_by('-pk').first()
            rows = [dict(league=s.league, totals=dict(s.totals or {}), war=s.war, env=dict(s.env or {}), champion=s.champion)
                    for s in c.seasons.order_by('year')]
            out = dict(role=c.role, seasons=len(rows), age=c.age, best_ovr=c.best_ovr, peak=c.peak, war=c.war,
                       rings=sum(1 for s in rows if s['champion']), rows=rows)
            transaction.set_rollback(True)
    finally:
        X.run_season = orig
    return out


def mean_se(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None, None, len(xs)
    return round(statistics.mean(xs), 4), round(statistics.stdev(xs) / math.sqrt(len(xs)), 4), len(xs)


def pro_rates(c):
    """프로 시즌(1군 리그) 합계 — 타자 타율·OPS·600타석당 홈런, 투수 평균자책점."""
    tot = {}
    for s in c['rows']:
        if s['league'] in W.TOP_LEAGUES or W.is_pro(s['league']):
            tot = L.add(tot, s['totals'])
    v = L.line_view(c['role'], tot) if tot else {}
    if c['role'] == 'batter':
        pa = tot.get('pa', 0)
        return {'avg': v.get('avg') if pa >= 200 else None, 'ops': v.get('ops') if pa >= 200 else None,
                'hr600': (tot.get('hr', 0) * 600 / pa) if pa >= 200 else None}
    outs = tot.get('outs', 0)
    return {'era': v.get('era') if outs >= 300 else None}


class Command(BaseCommand):
    help = '경기 환경: 끈/켠 같은 시드 분포 비교 + 조건별 성적 + 루틴'

    def add_arguments(self, parser):
        parser.add_argument('--careers', type=int, default=120)
        parser.add_argument('--seed', type=int, default=8_600_000)
        parser.add_argument('--routines', default='balance,travel,heat,weather,night,park')
        parser.add_argument('--output', default='')

    def handle(self, *args, **opts):
        started = time.time()
        old = setup_databases(verbosity=0, interactive=False, keepdb=False)
        try:
            with override_settings(ROOKIE_EXTREME_PREVIEW=True, ROOKIE_EXTREME_ENABLED=True):
                report = self._run(opts)
        finally:
            teardown_databases(old, verbosity=0)
            connection.close()
        report['seconds'] = round(time.time() - started, 1)
        text = json.dumps(report, ensure_ascii=False, indent=1)
        if opts['output']:
            Path(opts['output']).write_text(text, encoding='utf-8')
        self.stdout.write(text)

    def _run(self, opts):
        routines = [r for r in opts['routines'].split(',') if r in Env.ROUTINES]
        diff = defaultdict(list)                  # 지표 → [켠 값 − 끈 값]
        off_vals, on_vals = defaultdict(list), defaultdict(list)
        splits = {'batter': defaultdict(dict), 'pitcher': defaultdict(dict)}
        routine_war = defaultdict(list)
        for i in range(opts['careers']):
            seed = opts['seed'] + i
            mode = 'extreme' if i % 3 == 2 else 'lite'
            with override_settings(ROOKIE_ENV_ENABLED=False):
                off = career(i, seed, mode, None)
            with override_settings(ROOKIE_ENV_ENABLED=True):
                on = career(i, seed, mode, 'balance')
                if routines and i % 4 == 0:                                  # 4명에 1명꼴로 루틴별 같은 시드 비교
                    for rt in routines:
                        if rt == 'balance':
                            routine_war[rt].append(on['war'] - off['war'])
                            continue
                        alt = career(i, seed, mode, rt)
                        routine_war[rt].append(alt['war'] - off['war'])
            for key in ('seasons', 'age', 'best_ovr', 'war', 'rings'):
                diff[key].append(on[key] - off[key])
                off_vals[key].append(off[key])
                on_vals[key].append(on[key])
            ro, rn = pro_rates(off), pro_rates(on)
            for key in ro:
                if ro[key] is not None and rn.get(key) is not None:
                    diff[key].append(rn[key] - ro[key])
                    off_vals[key].append(ro[key])
                    on_vals[key].append(rn[key])
            diff['reached_mlb'].append(int(any(s['league'] == 'mlb' for s in on['rows'])) -
                                       int(any(s['league'] == 'mlb' for s in off['rows'])))
            for s in on['rows']:
                for bucket, t in ((s.get('env') or {}).get('splits') or {}).items():
                    splits[on['role']][bucket] = L.add(splits[on['role']].get(bucket, {}), t)
        shift = {}
        for key, xs in diff.items():
            m, se, n = mean_se(xs)
            shift[key] = {'off_mean': mean_se(off_vals[key])[0] if off_vals[key] else None,
                          'on_mean': mean_se(on_vals[key])[0] if on_vals[key] else None,
                          'mean_diff': m, 'se': se, 'n': n,
                          'significant': bool(m is not None and se and abs(m) > 2 * se)}
        visible = {}
        for role, table in splits.items():
            rows = {}
            for bucket, t in table.items():
                v = L.line_view(role, t)
                if role == 'batter' and t.get('pa', 0) >= 300:
                    rows[bucket] = {'pa': t['pa'], 'avg': round(v.get('avg', 0), 3), 'ops': round(v.get('ops', 0), 3),
                                    'hr_per_600': round(t.get('hr', 0) * 600 / t['pa'], 1)}
                if role == 'pitcher' and t.get('outs', 0) >= 300:
                    rows[bucket] = {'ip': round(t['outs'] / 3), 'era': round(v.get('era', 0), 2)}
            visible[role] = dict(sorted(rows.items()))
        return {'careers': opts['careers'], 'distribution_shift': shift, 'condition_splits': visible,
                'routine_war_vs_off': {k: dict(zip(('mean', 'se', 'n'), mean_se(v))) for k, v in routine_war.items()}}
