"""시리즈 시뮬레이터(rookie_series) — 결과는 기존 규칙이 정하고, 흐름은 그 결과와 어긋나지 않아야 해요."""
import random
import re
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings

from . import rookie_lite as X
from . import rookie_series as S
from . import rookie_universe as U
from . import rookie_world as W
from .management.commands.rookie_balance import choose


def fake(pk=7, year=5, club='lg', league='kbo1'):
    return SimpleNamespace(pk=pk, year=year, club=club, league=league)


def me(role='batter'):
    keys = S.M.BAT if role == 'batter' else S.M.PIT
    return S.Me(role, {k: 72.0 for k in keys}, 'SS' if role == 'batter' else 'SP',
                ('lower', 6) if role == 'batter' else ('sp', 1), W.level('kbo1') + S.POST_LEVEL)


def check(case, doc):
    """모든 경기·라운드가 지켜야 할 것."""
    for rd in doc['rounds']:
        need = rd['need']
        w = list(rd.get('head') or [0, 0])
        for g in rd['games']:
            us, them = g['score']
            case.assertNotEqual(us, them)
            case.assertEqual(us > them, g['won'])
            for side, runs in (('us', us), ('them', them)):
                case.assertEqual(sum(x for x in g[side] if x != 'X'), runs)
            if 'X' in g['us'] + g['them']:
                xside = 'us' if 'X' in g['us'] else 'them'
                case.assertEqual(g['home'], xside)                        # 9회말 X 는 이긴 홈 팀만
                case.assertEqual(us > them, xside == 'us')
            if g.get('walkoff') and not g.get('moment'):
                home_line = g[g['home']]
                away_total = them if g['home'] == 'us' else us
                case.assertLessEqual(sum(home_line[:8]), away_total)           # 9회말 전엔 비기거나 뒤져 있었다
                case.assertLessEqual(home_line[8], 4)                           # 끝내기는 결승점에서 끝난다(홈런 최대 4점)
            line = (g.get('me') or {}).get('line') or {}
            if 'ab' in line:
                case.assertLessEqual(line.get('rbi', 0), us)
                case.assertLessEqual(line.get('r', 0), us)
            if 'outs' in line:
                case.assertLessEqual(line.get('r', 0), them)
            if rd.get('opponent') is not None and rd['format'] != '단판':
                w[0 if g['won'] else 1] += 1
                case.assertLessEqual(max(w), need)                       # 확정 뒤 경기 없음
        if rd['result'] in ('won', 'lost') and rd['format'].endswith('선승제'):
            if len(rd['games']) < rd['cap']:
                case.assertEqual(max(rd['wins']), need)
                case.assertEqual(rd['wins'][0] >= need, rd['result'] == 'won')


class SeriesRulesTests(SimpleTestCase):
    def test_postseason_flow_matches_the_decided_result(self):
        for league, ranks in (('mlb', range(1, 13)), ('npb1', range(1, 7)), ('cpbl', range(1, 5)), ('kbo1', range(1, 6))):
            for rank in ranks:
                for reached in (True, False):
                    if league == 'cpbl' and rank == 1 and not reached:
                        continue                                          # 1위는 결승 직행 — 탈락할 라운드가 없다
                    doc = S.postseason(fake(pk=rank * 31, club='nyy' if league == 'mlb' else 'lg', league=league),
                                       league, rank, reached, me())
                    check(self, doc)
                    if doc['rounds']:
                        self.assertEqual(all(r['result'] == 'won' for r in doc['rounds']), reached)

    def test_final_moment_decides_the_series_both_ways(self):
        for pk in range(40):
            for won in (True, False):
                for side, inning, before, after in (('bat', '9회말', [3, 4], [5, 4] if won else [3, 4]),
                                                    ('pit', '9회말', [4, 3], [4, 3] if won else [4, 6]),
                                                    ('bat', '8회초', [2, 2], [3, 2] if won else [2, 2]),
                                                    ('pit', '7회말', [2, 2], [2, 2] if won else [2, 3])):
                    c = fake(pk=pk)
                    opened = S.final_open(c, 'kbo1', S.team_of('kbo1', 'kia'), pk % 2 == 0, me())
                    self.assertIn(opened['moment_game'], (4, 5, 6, 7))
                    rd = S.final_close(c, opened, won, {'before': before, 'after': after, 'side': side, 'game_won': won,
                                                        'line': '장면', 'stage': '한국시리즈', 'inning': inning, 'ok': won}, me())
                    self.assertEqual(rd['result'], 'won' if won else 'lost')
                    self.assertEqual(rd['wins'][0 if won else 1], 4)
                    self.assertEqual(len(rd['games']), opened['moment_game'])        # 결정적 순간 경기가 시리즈를 끝낸다
                    mg = rd['games'][-1]
                    self.assertTrue(mg.get('moment'))
                    self.assertEqual(mg['won'], won)
                    self.assertEqual(mg['home'] == 'us', (side == 'bat') == inning.endswith('말'))
                    check(self, {'rounds': [rd]})

    def test_international_and_amateur_paths_follow_the_tier(self):
        for key, tiers in S.INTL_REACH.items():
            for tier, reach in tiers.items():
                doc = S.intl(fake(pk=hash(tier) % 97), key, tier, me())
                check(self, doc)
                last = doc['rounds'][-1]
                if reach == 'final':
                    self.assertEqual((last['code'], last['result'], last['games']), ('final', 'pending', []))
                else:
                    self.assertNotEqual(last['result'], 'pending')
                    self.assertFalse(any(r['code'] == 'final' for r in doc['rounds']))
        for won in (True, False, None):
            doc = S.amateur(fake(league='hs', club='덕수고'), 'hs', '봉황대기', won, me())
            check(self, doc)
            self.assertEqual(doc['rounds'][-1]['result'], {True: 'won', False: 'lost', None: 'pending'}[won])

    def test_same_career_same_season_same_flow(self):
        a = S.postseason(fake(pk=5), 'mlb', 6, True, me())
        b = S.postseason(fake(pk=5), 'mlb', 6, True, me())
        self.assertEqual(a, b)
        self.assertNotEqual(a, S.postseason(fake(pk=6), 'mlb', 6, True, me()))

    def test_kbo_bracket_replays_kbo_final_exactly(self):
        clubs = ['lg', 'kia', 'ssg', 'doosan', 'kt', 'samsung', 'lotte', 'hanwha', 'nc', 'kiwoom']
        for pk in range(60):
            rng = random.Random(pk)
            rows = [dict(club=cl, name=cl, pct=round(.62 - i * .03 + rng.uniform(-.01, .01), 3)) for i, cl in enumerate(clubs)]
            mine = clubs[pk % 5]
            p = SimpleNamespace(pk=pk, club=mine)
            standings = dict(league='kbo1', year=3, rows=rows)
            opponent, news = U.kbo_final(p, standings)
            rounds = S.kbo_games(p, standings)
            if mine == clubs[0]:
                self.assertEqual(rounds, [])
                self.assertIsNotNone(opponent)
                continue
            all_won = all(sum(seq) + head[0] >= S.ROUNDS['kbo1'][idx][3] for idx, _o, seq, head, _h in rounds)
            self.assertEqual(opponent is not None, all_won and rounds[-1][0] == 2)
            label = {0: '와일드카드', 1: '준플레이오프', 2: '플레이오프'}
            for idx, opp, seq, head, _higher in rounds:
                line = next(n for n in news if n.startswith(label[idx]))
                a, b = map(int, re.search(r'(\d+):(\d+)', line).groups())
                us_wins, them_wins = head[0] + sum(seq), head[1] + len(seq) - sum(seq)
                self.assertEqual(sorted((a, b)), sorted((us_wins, them_wins)))

    def test_result_text_strips_any_game_number(self):
        for stage in ('한국시리즈 7차전', '한국시리즈 5차전', '한국시리즈 최종 승부', '월드시리즈 6차전'):
            text = X.moment_result_text({'kind': 'series', 'key': '', 'stage': stage, 'won': True})
            self.assertNotIn('차전', text)
            self.assertTrue(text.endswith('우승!'))

    def test_board_template_renders_demo(self):
        for role in ('batter', 'pitcher'):
            for doc in S.demo(role):
                check(self, doc)
                html = render_to_string('community/games/_series_board.html', {'doc': doc})
                self.assertIn('data-sb', html)
                self.assertNotIn('None', html)


@override_settings(ROOKIE_EXTREME_PREVIEW=True)
class SeriesSwitchTests(TestCase):
    def play(self, seed, enabled):
        with override_settings(ROOKIE_SERIES_ENABLED=enabled):
            rng = random.Random(seed)
            u = User.objects.create(username=f'series-{seed}-{enabled}', is_staff=True)
            c = X.create(u, name='시리즈', role='batter', position='SS', style='contact', region='서울', team='lg', rng=rng)
            for _ in range(160):
                if c.retired_at:
                    break
                p = c.pending
                if p['kind'] == 'plan':
                    event, pick = p.get('event'), ''
                    if event:
                        keys = [i[0] for i in X.EVENTS[event]['choices']]
                        pick = next((k for k in ('team_work', 'team', 'rest', 'together', 'short', 'break', 'accept') if k in keys), keys[0])
                    X.run_season(c, X.pick_programs(c, rng), 'normal', pick, rng, intl={k: 'go' for k in p.get('intl') or []})
                elif p['kind'] == 'review':
                    X.next_season(c, rng)
                else:
                    try:
                        X.decide(c, p['what'], choose(c, rng, 'playing'), rng)
                    except X.LiteError:
                        view = X.decision_view(c) or {}
                        keys = [ch['key'] for ch in view.get('choices') or []] + [o['key'] for o in view.get('offers') or []]
                        X.decide(c, p['what'], keys[0], rng)
                    c.save()
            return c, list(c.seasons.order_by('year'))

    def test_switch_off_writes_nothing_and_switch_on_writes_consistent_flows(self):
        _c, off = self.play(4242, False)
        self.assertFalse(any(s.series for s in off))
        _c, on = self.play(4242, True)
        docs = [d for s in on for d in s.series]
        self.assertTrue(docs)                                              # 고교 결승·국제대회·가을야구 중 무엇이든
        for d in docs:
            check(self, d)
        self.assertFalse(S.enabled())                                      # 기본은 꺼져 있다
