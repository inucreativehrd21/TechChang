"""정식 판 리메이크 하네스 — 같은 선수들로 한 시즌을 예전 방식(밤에 몰아서)과 새 방식(시간대 경기 + 전·후기 리그 + 가을야구)으로
치러 기록 분포가 움직이는지 잰다(임시 테스트 DB, 시즌마다 되돌림).

1) 분포 이동: 선수별 시즌 타율·OPS·600타석당 홈런·평균자책점·WAR·경기 수 — 평균 차이와 표준오차(같은 선수끼리 짝).
   시간대 경기는 경기 수·순서가 같으므로 훈련 반영 시점 말고는 분포가 같아야 한다(docs/rookie-full-remake-proposal.md 11장).
2) 일정 불변식: 개인 세계 순위표가 시즌 끝에 모든 라운드를 치렀는지, 전·후기면 반기마다 모든 구단이 G/2경기인지.
3) 새 방식에서만: 반기 MVP 수, 가을야구 시리즈 길이 분포·내 구단 결승 우승률.
4) DB 없이 개인 세계 --worlds 개: 정규시즌 1위 구단 우승률·결승 진출률·한 구단 두 반기 석권률·시리즈 길이(1군 리그).
"""
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.test.utils import override_settings, setup_databases, teardown_databases
from django.utils import timezone

from community import rookie as R
from community import rookie_league as L
from community import rookie_universe as U
from community import rookie_world as W

SEASON = 2
OFF = dict(ROOKIE_FULL_SLOTS='false', ROOKIE_FULL_HALVES='false', ROOKIE_FULL_POSTSEASON='false')
NEW = dict(ROOKIE_FULL_SLOTS='true', ROOKIE_FULL_HALVES='true', ROOKIE_FULL_POSTSEASON='true', ROOKIE_SLOTS_FROM_SEASON=str(SEASON))
LEAGUES = ('kbo1', 'kbo1', 'kbo2', 'mlb', 'npb1', 'cpbl')
TEAMS = {'kbo1': 'lg', 'kbo2': 'kia', 'mlb': 'nyy', 'npb1': 'yomiuri', 'cpbl': 'brothers'}


def _club(league, i):
    clubs = U.teams(league)
    return clubs[i % len(clubs)] if clubs else TEAMS.get(league, 'lg')


def bump_ids(seed):
    """런마다 선수 pk 를 다르게(같은 런의 예전/새 방식은 같은 pk — 같은 개인 세계로 짝 비교). SQLite 임시 DB 에서만."""
    from community.models import RookiePlayer
    if connection.vendor != 'sqlite':
        return
    table = RookiePlayer._meta.db_table
    with connection.cursor() as cur:
        cur.execute('DELETE FROM sqlite_sequence WHERE name = %s', [table])
        cur.execute('INSERT INTO sqlite_sequence (name, seq) VALUES (%s, %s)', [table, seed % 1_000_000])


def final_odds(k, seed):
    """DB 없이 개인 세계 k개(1군 리그)의 전·후기 결승 — 정규시즌 1위 구단의 우승률, 한 구단 두 반기 석권률, 시리즈 길이."""
    from types import SimpleNamespace
    from community import rookie_halves as H
    out = {}
    for league in ('kbo1', 'mlb', 'npb1', 'cpbl'):
        champ_top, swept, lengths, top_in = [], 0, Counter(), 0
        for i in range(k):
            p = SimpleNamespace(pk=seed + i, club='', league=league, career={})
            U.advance(p, SEASON, league, L.SEASON_GAMES, None, split=True)
            halves = U.half_tables(p)
            whole = U.table(p, SEASON, league, L.SEASON_GAMES)
            a, b = U.half_finalists(halves, whole)
            swept += halves['first_champ']['club'] == halves['second_champ']['club']
            cap, need = H.TOP_FORMAT
            seq = H.series_seq(a, b, cap, need, random.Random(f'odds:{seed}:{league}:{i}'))
            lengths[len(seq)] += 1
            winner = a if sum(seq) >= need else b
            top = whole['rows'][0]['club']
            top_in += top in (a['club'], b['club'])
            champ_top.append(int(winner['club'] == top))
        out[league] = {'worlds': k, 'season_top_champion': round(sum(champ_top) / k, 3),
                       'season_top_in_final': round(top_in / k, 3), 'one_club_both_halves': round(swept / k, 3),
                       'series_length': {f'{n}경기': round(c / k, 3) for n, c in sorted(lengths.items())}}
    return out


def make_players(n, seed):
    """프로 성인 선수 n명 — 리그·역할·능력치를 시드로 고르게. 나이 한계·특성이 기록을 흔들지 않게 고정한다."""
    from common.models import Profile
    from community.models import RookieLog, RookiePlayer
    r = random.Random(seed)
    out = []
    for i in range(n):
        role = 'pitcher' if i % 3 == 2 else 'batter'
        league = LEAGUES[i % len(LEAGUES)]
        u = User.objects.create_user(username=f'h{seed}_{i}', password='pw12345!', email=f'h{seed}_{i}@example.com')
        prof, _ = Profile.objects.get_or_create(user=u)
        prof.nickname, prof.is_email_verified = f'하네스{i}', True
        prof.save()
        p = R.create(u, name=f'하네스{i}'[:12], role=role, team='lg', region='서울')
        level = round(r.uniform(52, 78), 1)
        p.stats = {k: level for k in p.stats}
        p.ovr, p.league, p.club = level, league, _club(league, i)
        p.position = 'SP' if role == 'pitcher' else r.choice(('C', '1B', '2B', '3B', 'SS', 'OF', 'DH'))
        p.age, p.potential, p.traits, p.grade, p.grade_since, p.pending = 26, 99, [], 0, None, {}
        p.career = {'path': [{'league': league, 'club': p.club, 'age': 26, 'season': 0, 'day': '2026-10-01'}]}
        p.role_since = date(2026, 10, 1)
        p.save()
        RookiePlayer.objects.filter(pk=p.pk).update(created_at=timezone.make_aware(datetime(2026, 10, 1, 12)))
        RookieLog.objects.filter(player=p, kind='start').update(day=date(2026, 10, 1))
        out.append(p.pk)
    return out


def play_season(n, seed, settings):
    """한 시즌을 치르고 선수별 결과를 모은 뒤 되돌린다."""
    from community.models import RookieAward, RookieLog, RookiePlayer, RookieSeasonStat
    with override_settings(**settings), transaction.atomic():
        bump_ids(seed)                                  # 되돌림마다 pk 가 같아지면 개인 세계(pk 씨앗)가 런마다 같다
        pks = make_players(n, seed)
        start, end = L.season_bounds(SEASON)
        s = L.get_season(SEASON)
        for k in range(L.SEASON_DAYS):
            day = start + timedelta(days=k)
            RookieLog.objects.bulk_create([RookieLog(player_id=pk, kind='earn', source='checkin', ref=str(day), tp=20,
                                                     text='출석', day=day) for pk in pks])
            L.simulate_day(day, rng=random.Random(f'{seed}:{k}'))
        s.refresh_from_db()
        rows = {}
        for pk in pks:
            p = RookiePlayer.objects.get(pk=pk)
            tot, war = {}, 0.0
            for st in RookieSeasonStat.objects.filter(season=s, player=p):
                tot, war = L.add(tot, st.totals or {}), war + st.war
            world = ((p.career or {}).get('career_universe') or {}).get('leagues') or {}
            state = world.get(p.league)
            sched = U.schedule(p.league, state['games'], state.get('split', False))[1] if state else ()
            halves = U.half_tables(p)
            rows[pk] = dict(role=p.role, league=p.league, totals=tot, war=war,
                            world_done=bool(state) and len(state['scores']) == len(sched),
                            half_games=sorted({r['g'] for t in (halves['first'], halves['second']) for r in t['rows']})
                            if halves and halves['second'] else None,
                            post=(p.career or {}).get('post'))
        half_awards = RookieAward.objects.filter(season=s, kind='half').count()
        closed = s.closed
        transaction.set_rollback(True)
    return rows, half_awards, closed


def rates(row):
    t, v = row['totals'], L.line_view(row['role'], row['totals']) if row['totals'] else {}
    if row['role'] == 'batter':
        pa = t.get('pa', 0)
        ok = pa >= 150
        return {'avg': v.get('avg') if ok else None, 'ops': v.get('ops') if ok else None,
                'hr600': t.get('hr', 0) * 600 / pa if ok else None, 'war': row['war'], 'games': t.get('g', 0)}
    ok = t.get('outs', 0) >= 120
    return {'era': v.get('era') if ok else None, 'war': row['war'], 'games': t.get('g', 0)}


def mean_se(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None, None, len(xs)
    return round(statistics.mean(xs), 4), round(statistics.stdev(xs) / math.sqrt(len(xs)), 4), len(xs)


class Command(BaseCommand):
    help = '정식 판 리메이크: 예전 방식 / 시간대 경기 + 전·후기 + 가을야구 한 시즌 분포 비교'

    def add_arguments(self, parser):
        parser.add_argument('--players', type=int, default=24)
        parser.add_argument('--runs', type=int, default=3)
        parser.add_argument('--seed', type=int, default=9_100_000)
        parser.add_argument('--worlds', type=int, default=1000, help='가을야구 확률을 잴 개인 세계 수(DB 없이)')
        parser.add_argument('--output', default='')

    def handle(self, *args, **opts):
        started = time.time()
        old = setup_databases(verbosity=0, interactive=False, keepdb=False)
        try:
            report = self._run(opts)
        finally:
            teardown_databases(old, verbosity=0)
            connection.close()
        report['seconds'] = round(time.time() - started, 1)
        text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
        if opts['output']:
            Path(opts['output']).write_text(text, encoding='utf-8')
        self.stdout.write(text)

    def _run(self, opts):
        diff, off_vals, new_vals = defaultdict(list), defaultdict(list), defaultdict(list)
        checks = Counter()
        lengths, top_seed = Counter(), []
        half_awards = []
        for run in range(opts['runs']):
            seed = opts['seed'] + run * 1000
            off, _a, off_closed = play_season(opts['players'], seed, OFF)
            new, awards, new_closed = play_season(opts['players'], seed, NEW)
            half_awards.append(awards)
            checks['season_closed'] += int(off_closed and new_closed)
            for i, (a, b) in enumerate(zip(off.values(), new.values())):
                ra, rb = rates(a), rates(b)
                for key, va in ra.items():
                    vb = rb.get(key)
                    if va is not None and vb is not None:
                        diff[key].append(vb - va)
                        off_vals[key].append(va)
                        new_vals[key].append(vb)
                checks['world_done_off'] += int(a['world_done'])
                checks['world_done_new'] += int(b['world_done'])
                if W.is_pro(b['league']):
                    checks['pro_players'] += 1
                    checks['halves_even'] += int(b['half_games'] == [L.season_games(b['league']) // 2])
                post = b['post']
                if post:
                    checks['post_built'] += 1
                    rnd = post['doc']['rounds'][0]
                    lengths[f"{post['final']} {len(rnd['games'])}경기"] += 1
                    if post['mine']:
                        top_seed.append(int(post['doc']['result'] == '우승'))
        shift = {}
        for key, xs in diff.items():
            m, se, n = mean_se(xs)
            shift[key] = {'off_mean': mean_se(off_vals[key])[0], 'new_mean': mean_se(new_vals[key])[0],
                          'mean_diff': m, 'se': se, 'n': n,
                          'significant': bool(m is not None and se and abs(m) > 2 * se)}
        return {'players': opts['players'], 'runs': opts['runs'], 'distribution_shift': shift,
                'final_odds': final_odds(opts['worlds'], opts['seed']),
                'schedule_checks': dict(checks), 'half_mvps_per_season': half_awards,
                'postseason_lengths': dict(sorted(lengths.items())),
                'my_team_final_win_rate': mean_se(top_seed)}
