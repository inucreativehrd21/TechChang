"""대진·승패 보존, 라이벌 기억, 고졸 직행과 공용 타석/카드 개편 검증."""
import copy
import random
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase

from . import rookie_universe as U
from . import rookie_development as D
from . import rookie_sim as M
from . import rookie_story as S
from . import rookie_card as K
from . import rookie_lite as X
from . import rookie_league as L
from . import rookie_world as W
from .test_rookie_lite import pro
from .test_rookie_league import player, active_on, D1
from .models import LiteSeason


def fake():
    return SimpleNamespace(pk=7, name='연습선수', flags={}, year=1, age=19, role='batter', position='SS',
                           club='lg', league='kbo1', ovr=64, potential=76, stats={k: 50 for k in M.BAT})


class UniverseRulesTests(SimpleTestCase):
    def test_all_pro_schedules_have_exact_games_and_no_self_matches(self):
        for league, games in X.GAMES.items():
            if not W.is_pro(league):
                continue
            teams, rounds = U.schedule(league, games)
            counts = Counter()
            for day in rounds:
                seen = set()
                for a, b in day:
                    self.assertNotEqual(a, b)
                    self.assertFalse({a, b} & seen)
                    seen.update((a, b))
                    counts.update((a, b))
            self.assertEqual(set(counts.values()), {games})
            self.assertEqual(len(counts), len(teams))
            self.assertEqual(len(U.club_fixtures(league, games, teams[0])), games)

    def test_full_144_game_schedule_also_handles_eleven_future_teams(self):
        clubs, _rounds = U.schedule('kbo2', 144)
        self.assertTrue(all(len(U.club_fixtures('kbo2', 144, c)) == 144 for c in clubs))

    def test_wins_losses_and_runs_are_conserved_and_own_score_is_used(self):
        p = fake()
        f = U.club_fixtures(p.league, 144, p.club)[0]
        U.advance(p, 1, p.league, 144, f['day'] + 1, {str(f['day']): {'club': p.club, 'for': 12, 'against': 2}})
        table = U.current_table(p)
        mine = table['mine']
        opponent = next(r for r in table['rows'] if r['club'] == f['opponent'])
        self.assertEqual((mine['w'], mine['rf'], mine['ra']), (1, 12, 2))
        self.assertEqual((opponent['l'], opponent['rf'], opponent['ra']), (1, 2, 12))
        final = U.advance(p, 1, p.league, 144)
        self.assertEqual(sum(r['w'] for r in final['rows']), sum(r['l'] for r in final['rows']))
        self.assertEqual(sum(r['rf'] for r in final['rows']), sum(r['ra'] for r in final['rows']))
        self.assertTrue(all(r['g'] == 144 for r in final['rows']))
        self.assertEqual(final, U.advance(p, 1, p.league, 144))

    def test_future_scores_are_not_shown_before_their_matchday(self):
        p = fake()
        a = U.advance(p, 1, p.league, 144, 20)
        b = U.table(p, 1, p.league, 144, 10)
        self.assertEqual(a['mine']['g'], 20)
        self.assertEqual(b['mine']['g'], 10)

    def test_rival_identity_relationship_and_history_persist(self):
        p = fake()
        r = U.rival_report(p, p.league, 'up')
        U.remember(p, r['id'], 'accept', '함께 연습했어요')
        same = U.rival_report(p, p.league, 'up')
        self.assertEqual((r['id'], r['name']), (same['id'], same['name']))
        self.assertGreater(same['relation'], r['relation'])
        self.assertIn('함께 연습했어요', same['history'][-1])
        p.year = 2
        before = U.rivals(p)
        snapshot = copy.deepcopy(before)
        self.assertEqual(U.rivals(p), snapshot)
        self.assertEqual(before[0]['name'], snapshot[0]['name'])

    def test_rival_dialogue_changes_the_saved_relationship(self):
        p = fake()
        e = S.encounter(p, 'rival', random.Random(1))
        S.resolve(p, e, 'together', random.Random(1))
        stored = next(r for r in p.flags['rivals'] if r['id'] == e['rival']['id'])
        self.assertEqual(stored['relation'], 58)
        self.assertGreater(S.training_mult(p), 1)

    def test_hitting_is_reduced_four_percent_at_every_skill_level(self):
        for gap in (-30, -10, 0, 10, 30):
            for risp in (False, True):
                batter = {k: 64 + gap for k in M.BAT}
                pitcher = {k: 64 for k in M.PIT}
                after = M.pa_probs(batter, pitcher, risp)
                with mock.patch.object(M, 'HIT_RATE', 1):
                    before = M.pa_probs(batter, pitcher, risp)
                for key in ('1B', '2B', '3B', 'HR'):
                    self.assertAlmostEqual(after[key], before[key] * .96)
                self.assertAlmostEqual(sum(after.values()), 1)
                self.assertEqual(after['BB'], before['BB'])

    def test_sacrifice_fly_is_a_pa_but_not_an_ab(self):
        line = Counter()
        rng = mock.Mock(random=lambda: 0, choices=lambda *a, **k: [1])
        with mock.patch.object(M, 'pa_probs', return_value={'OUT': 1}):
            M._plate(line, {}, {}, 'reg', 7, 0, rng, {})
        self.assertEqual((line['pa'], line['ab'], line['sf'], line['rbi']), (1, 0, 1, 1))

    def test_elite_advantage_diminishes_without_reversing_skill_order(self):
        values = [M._duel(gap) for gap in (0, 5, 12, 15, 20, 26, 40)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(M._duel(5), 5 / M.S)
        self.assertAlmostEqual(M._duel(12), 12 / M.S)
        self.assertLess(M._duel(40), 18 / M.S)
        self.assertEqual(M._duel(-20), -M._duel(20))

    def test_elite_pitching_stays_strong_but_not_routinely_sub_one_era(self):
        totals = {}
        for seed in range(3):
            rng = random.Random(33 + seed)
            for _ in range(12 * 28):
                totals = L.add(totals, M.starter_game({k: 90 for k in M.PIT}, 64, rng)['line'])
        self.assertTrue(1.25 <= L.pitching(totals)['era'] <= 2.2, L.pitching(totals))

    def test_every_registered_foreign_club_uses_an_existing_uniform(self):
        for code, team in W.PRO_TEAM.items():
            pal = K._palette(W.SYSTEMS[team['system']][-1], code)
            self.assertIn(pal['jersey_source'], K.KBO_TRIM)
            self.assertIsNotNone(finders.find(pal['jersey_asset']))
        self.assertEqual(K._palette('mlb', 'nyy')['jersey_source'], 'doosan')
        self.assertEqual(K._palette('mlb', 'sf')['jersey_source'], 'hanwha')

    def test_development_penalty_only_applies_to_young_hs_us_route(self):
        p = fake()
        p.league = 'mlb_a'
        self.assertEqual(D.multiplier(p), 1)
        D.mark_entry(p, 'hs', 'mlb')
        ordinary = D.multiplier(p)
        p.potential = 90
        self.assertGreater(D.multiplier(p), ordinary)
        p.age = 24
        self.assertEqual(D.multiplier(p), 1)

    def test_exceptional_school_requires_real_sample_not_only_potential(self):
        p = fake()
        self.assertFalse(D.exceptional_school(p, {'pa': 2, 'ab': 2, 'h': 2}, 30))
        self.assertTrue(D.exceptional_school(p, {'pa': 120, 'ab': 100, 'h': 40, 'hr': 12, 'bb': 20}, 30))


class UniverseCareerTests(TestCase):
    def test_strong_graduation_record_gets_mlb_offer_without_elite_potential(self):
        c = pro('고졸성적', ovr=62)
        c.league, c.club, c.age, c.potential = 'hs', '경기고', 18, 74
        LiteSeason.objects.create(career=c, year=1, age=18, league='hs', club=c.club, games=30,
                                 totals={'pa': 120, 'ab': 100, 'h': 40, 'hr': 12, 'bb': 20})
        d = X.draft_offer(c, 'hs', random.Random(2))
        self.assertEqual(len(d['abroad']['mlb']), 3)
        c.pending = d
        X.decide(c, 'draft', 'mlb:' + d['abroad']['mlb'][0], random.Random(2))
        self.assertEqual(c.league, 'mlb_a')
        self.assertLess(D.multiplier(c), .7)

    def test_reduced_us_growth_is_visible_in_the_change_ledger(self):
        c = pro('적응성장', ovr=54, age=19)
        c.league = 'mlb_a'
        D.mark_entry(c, 'hs', 'mlb')
        result = X.grow(c, ['contact', 'power'], 'normal', .7, 0, random.Random(1))
        self.assertTrue(any(label == '고졸 미국 직행 적응' and value < 0
                            for entries in result['_why'].values() for label, value in entries))

    def test_full_game_opponent_and_score_match_career_schedule(self):
        p = player('정식대진', level=64)
        active_on(p, D1)
        L.simulate_day(D1, random.Random(2))
        p.refresh_from_db()
        fixtures = U.club_fixtures(p.league, 144, p.club)
        for game in p.games.all():
            self.assertEqual(game.opponent, fixtures[game.no - 1]['opponent'])
            self.assertEqual(game.home, fixtures[game.no - 1]['home'])
        table = U.current_table(p)
        self.assertEqual(sum(r['w'] for r in table['rows']), sum(r['l'] for r in table['rows']))

    def test_first_place_reaches_korean_series_against_a_real_other_club(self):
        c = pro('가을대진', ovr=74)
        table = U.advance(c, c.year, 'kbo1', 144)
        table['rows'].sort(key=lambda r: r['club'] != c.club)
        rival, news = U.kbo_final(c, table)
        self.assertNotEqual(rival['club'], c.club)
        self.assertEqual(len(news), 3)
