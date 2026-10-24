"""시리즈 시뮬레이터 하네스 — 같은 시드로 커리어를 스위치 끈 채·켠 채 두 번 끝까지 돌려 비교한다(임시 테스트 DB).

1) 분포 동일성: 시즌마다 우승·메달·수상·순위·리그·은퇴가 두 실행에서 똑같아야 한다(결과는 기존 규칙이 정하므로).
2) 흐름 점검: 결승 길이, 라운드 길이, 경기당 득점, 이닝 합 = R, 9회말 X, 내 타점·득점 ≤ 팀 득점,
   우승 확정 뒤 경기 없음, 시리즈 승수와 결과의 일치.
3) 현재 확률표 대비: 리그·순위별 결승 진출률(표의 2배 값)과 우승률, 국제대회 단계 분포.
"""
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.test.utils import override_settings, setup_databases, teardown_databases

from community import rookie_extreme as E
from community import rookie_lite as X
from community import rookie_modes as Modes
from community import rookie_series as Series
from community.management.commands.rookie_balance import choose
from community.models import LiteCareer

POLICIES = ('playing', 'salary', 'bold', 'us', 'domestic', 'steady')


def run(index: int, seed: int, mode: str, tag: str):
    rng = random.Random(seed)
    role = 'batter' if index % 2 == 0 else 'pitcher'
    u = User.objects.create(username=f'series-{index}', is_staff=True)
    position = ('C', '1B', '2B', '3B', 'SS', 'OF', 'DH')[(index // 2) % 7] if role == 'batter' else ('SP', 'RP')[(index // 2) % 2]
    c = X.create(u, mode=mode, name=f'검증{index}', role=role, position=position,
                 style=list(X.STYLES[role])[(index // 4) % 4], region='서울', team='lg', rng=rng)
    policy = POLICIES[index % len(POLICIES)]
    for _step in range(300):
        if c.retired_at:
            break
        p = c.pending
        if p['kind'] == 'plan':
            if Modes.is_extreme(c):
                ev = E.event_view(c)
                if ev:
                    E.resolve(c.pk, u, ev['id'], ev['choices'][0]['key'], random.Random(seed))
                    c = LiteCareer.objects.get(pk=c.pk)
                    p = c.pending
            event, choice = p.get('event'), ''
            if event:
                keys = [i[0] for i in X.EVENTS[event]['choices']]
                choice = next((k for k in ('team_work', 'team', 'rest', 'together', 'short', 'break', 'accept') if k in keys), keys[0])
            X.run_season(c, X.pick_programs(c, rng), 'normal', choice, rng, intl={k: 'go' for k in p.get('intl') or []})
        elif p['kind'] == 'review':
            X.next_season(c, rng)
        else:
            try:
                X.decide(c, p['what'], choose(c, rng, policy), rng)
            except X.LiteError:
                # 밸런스 하네스의 자동 선택이 화면에 없는 선택지를 고르는 경우(예: 거부권 없는 협상) — 화면의 첫 선택지로
                view = X.decision_view(c) or {}
                keys = [ch['key'] for ch in view.get('choices') or []] + [o['key'] for o in view.get('offers') or []]
                X.decide(c, p['what'], keys[0] if keys else 'accept', rng)
            c.save()
    seasons = [dict(year=s.year, league=s.league, club=s.club, team_rank=s.team_rank, champion=s.champion,
                    awards=list(s.awards or []), series=list(s.series or [])) for s in c.seasons.order_by('year')]
    sig = [(s['year'], s['league'], s['club'], s['team_rank'], s['champion'],
            tuple(sorted(a['label'] for a in s['awards'] if a.get('kind') in ('ring', 'national'))))
           for s in seasons]
    tail = (c.pk, c.age, c.peak, len(seasons), round(c.war, 3), bool(c.retired_at))
    return sig, tail, [d for s in seasons for d in s['series']], seasons


def isolated(index, seed, mode, tag):
    """같은 pk·같은 빈 세계에서 비교하려고 한 커리어씩 트랜잭션 안에서 돌리고 되돌린다
    (리그 순위표·kbo_final 의 씨앗이 커리어 pk 를 쓰고, 경쟁자 기록이 다른 회원 커리어를 본다)."""
    with transaction.atomic():
        out = run(index, seed, mode, tag)
        transaction.set_rollback(True)
    return out


def check_doc(doc: dict, bad: Counter, stats: dict):
    for rd in doc.get('rounds', []):
        games = rd.get('games', [])
        need, w = rd.get('need', 1), [0, 0]
        w = list(rd.get('head') or [0, 0])
        for i, g in enumerate(games):
            us, them = g['score']
            if us == them:
                bad['tie score'] += 1
            if (us > them) != g['won']:
                bad['score/winner mismatch'] += 1
            for side, runs in (('us', us), ('them', them)):
                inns = [x for x in g[side] if x != 'X']
                if sum(inns) != runs:
                    bad['innings sum != R'] += 1
            if 'X' in g['us'] + g['them']:
                xside = 'us' if 'X' in g['us'] else 'them'
                if g['home'] != xside or not ((us > them) == (xside == 'us')):
                    bad['X on wrong side'] += 1
            me = (g.get('me') or {}).get('line') or {}
            if me:
                if me.get('rbi', 0) > us or me.get('r', 0) > us and 'ab' in me:
                    bad['my RBI/R > team runs'] += 1
                if 'outs' in me and me.get('r', 0) > them:
                    bad['my runs allowed > opp runs'] += 1
            stats['runs'].append(us)
            stats['runs'].append(them)
            stats['walkoff'].append(1 if g.get('walkoff') else 0)
            if rd.get('opponent') is not None and rd['code'] not in ('pool', 'open', 'super', 'group'):
                w[0 if g['won'] else 1] += 1
                if max(w[0], w[1]) > need:
                    bad['game after clinch'] += 1
        if rd.get('result') in ('won', 'lost') and rd.get('format', '').endswith('선승제'):
            stats['len'][(doc['kind'], rd['code'] == 'final', rd.get('cap'))].append(len(games))
            winner_ok = (rd['wins'][0] >= need) if rd['result'] == 'won' else (rd['wins'][1] >= need)
            if not winner_ok and len(games) < rd.get('cap', 99):
                bad['result without enough wins'] += 1


class Command(BaseCommand):
    help = '시리즈 시뮬레이터: 스위치 끈/켠 같은 시드 비교 + 흐름 점검'

    def add_arguments(self, parser):
        parser.add_argument('--careers', type=int, default=120)
        parser.add_argument('--seed', type=int, default=8_100_000)
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
        mismatch, total_seasons = [], 0
        bad, docs = Counter(), []
        stats = {'runs': [], 'walkoff': [], 'len': defaultdict(list)}
        champ_by = defaultdict(lambda: [0, 0])      # (리그, 순위) → [시즌 수, 우승]
        reach_by = defaultdict(lambda: [0, 0])      # (리그, 순위) → [시즌 수, 결승 진출]
        intl_tiers = Counter()
        kinds = Counter()
        for i in range(opts['careers']):
            seed = opts['seed'] + i
            mode = Modes.EXTREME if i % 3 == 2 else Modes.LITE
            with override_settings(ROOKIE_SERIES_ENABLED=False):
                off_sig, off_tail, off_docs, _ = isolated(i, seed, mode, 'off')
            with override_settings(ROOKIE_SERIES_ENABLED=True):
                on_sig, on_tail, on_docs, seasons = isolated(i, seed, mode, 'on')
            total_seasons += len(on_sig)
            if off_sig != on_sig or off_tail != on_tail:
                first = next((a, b) for a, b in zip(off_sig + [None], on_sig + [None]) if a != b) if off_sig != on_sig else (off_tail, on_tail)
                mismatch.append({'career': i, 'seed': seed, 'mode': mode, 'first_diff': repr(first)[:300]})
            if off_docs:
                bad['series written while switch off'] += 1
            for d in on_docs:
                kinds[d['kind']] += 1
                check_doc(d, bad, stats)
                docs.append(d)
                if d['kind'] == 'intl':
                    intl_tiers[(d['key'], d['result'])] += 1
            for s in seasons:
                if s['league'] in X.POSTSEASON and s['team_rank']:
                    key = f"{s['league']}:{s['team_rank']}"
                    champ_by[key][0] += 1
                    champ_by[key][1] += int(any(a.get('kind') == 'ring' for a in s['awards']))
                    reached = any(d.get('kind') == 'post' and d['rounds'] and d['rounds'][-1]['code'] == 'final'
                                  for d in s['series'])
                    reach_by[key][0] += 1
                    reach_by[key][1] += int(reached)
        lens = {f'{k[0]}{"-final" if k[1] else ""}-bo{k[2]}': dict(sorted(Counter(v).items())) for k, v in stats['len'].items()}
        table = {}
        for key, (n, champs) in sorted(champ_by.items()):
            lg, rank = key.split(':')
            odds = X.POSTSEASON[lg]
            rank = int(rank)
            if rank <= len(odds) and n:
                table[key] = {'seasons': n, 'champion_rate': round(champs / n, 3), 'table_odds': odds[rank - 1],
                              'final_rate': round(reach_by[key][1] / n, 3),
                              'table_final': min(1.0, 2 * odds[rank - 1]) if lg != 'kbo1' else None}
        return {
            'careers': opts['careers'], 'seasons': total_seasons,
            'identical_outcomes': not mismatch, 'mismatches': mismatch[:10],
            'consistency_problems': dict(bad), 'series_docs': dict(kinds),
            'runs_per_team_game': round(statistics.mean(stats['runs']), 2) if stats['runs'] else None,
            'walkoff_share': round(statistics.mean(stats['walkoff']), 3) if stats['walkoff'] else None,
            'series_lengths': lens, 'postseason_vs_table': table,
            'intl_results': {f'{k[0]}:{k[1]}': v for k, v in sorted(intl_tiers.items())},
        }
