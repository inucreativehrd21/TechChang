"""실제 저장·기용·계약 경로의 밸런스와 투수 전환 회귀 검사."""
import random
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from . import rookie_balance_rules as B
from . import rookie_pitching as P
from . import rookie_story as S
from . import rookie_lite as X
from . import rookie_sim as M
from . import rookie_league as L
from . import rookie_contracts as C
from .models import LiteSeason, RookiePlayer
from .test_rookie_lite import new, member


def pitcher(**over):
    fields = dict(pk=None, name='평가선수', role='pitcher', position='RP', league='kbo1', club='lg',
                  age=25, potential=80, ovr=72, stats={k: 72.0 for k in M.PIT}, flags={}, year=7)
    fields.update(over)
    return SimpleNamespace(**fields)


class BalanceRuleTests(SimpleTestCase):
    def test_confidence_changes_approach_without_extra_power_or_velocity(self):
        p = pitcher(flags={'confidence': 100, 'discipline': 100})
        result = S.game_stats(p, p.stats)
        self.assertEqual(result['velocity'], 72)
        self.assertEqual(result['stamina'], 72)
        self.assertEqual(result['control'], 73.25)
        self.assertLessEqual(S.training_mult(p), 1.075)
        S.recover(p)
        self.assertLess(p.flags['confidence'], 80)

    def test_low_ability_receives_no_automatic_major_offer(self):
        p = pitcher(ovr=69, stats={k: 69.0 for k in M.PIT})
        offers = S.posting_offers(p, random.Random(1))
        self.assertEqual(len(offers), 3)
        self.assertTrue(all(o['entry_league'] != 'mlb' for o in offers))
        self.assertEqual(B.overseas_level(p, 'mlb'), 'mlb_aaa')

    def test_no_interest_is_a_valid_market_outcome(self):
        p = pitcher(ovr=55, stats={k: 55.0 for k in M.PIT})
        self.assertEqual(S.posting_offers(p, random.Random(1)), [])

    def test_contract_entry_level_survives_signing(self):
        deal = C.signed(dict(system='mlb', team='nyy', years=1, annual=4000, entry_league='mlb_aaa'), 5)
        self.assertEqual(deal['entry_league'], 'mlb_aaa')

    def test_older_fa_has_shorter_lower_offer(self):
        young, old = pitcher(age=28), pitcher(age=36)
        self.assertGreater(B.fa_terms(young, 3)[0], B.fa_terms(old, 3)[0])
        self.assertGreater(B.fa_terms(young, 3)[1], B.fa_terms(old, 3)[1])

    def test_starter_course_is_not_instant_conversion(self):
        p = pitcher()
        e = P.offer(p, {}, 7)
        P.resolve(p, e, 'course', random.Random(2))
        self.assertEqual(p.position, 'RP')
        self.assertIn('starter_course', p.flags)
        self.assertIsNone(P.offer(p, {}, 7))
        self.assertEqual(P.offer(p, {}, 8)['mode'], 'assessment')

    def test_successful_trial_changes_real_track(self):
        p = pitcher()
        e = P.offer(p, {}, 7)
        line = dict(g=1, gs=1, outs=18, er=1, r=1, so=6, bb=1, h=4)
        with mock.patch.object(M, 'starter_game', return_value={'line': line}):
            text = P.resolve(p, e, 'trial', random.Random(2))
        self.assertEqual(p.position, 'SP')
        self.assertEqual(X.duty_for(p, 64)[0], 'sp')
        self.assertIn('선발', text)
        self.assertTrue(p.flags['pitch_last_assessment']['practice'])

    def test_failed_trial_stays_relief(self):
        p = pitcher()
        e = P.offer(p, {}, 7)
        with mock.patch.object(M, 'starter_game', return_value={'line': dict(g=1, gs=1, outs=6, er=5, r=5)}):
            P.resolve(p, e, 'trial', random.Random(2))
        self.assertEqual(p.position, 'RP')
        self.assertNotEqual(X.duty_for(p, 64)[0], 'sp')

    def test_poor_starter_receives_relief_notice(self):
        p = pitcher(position='SP')
        e = P.offer(p, dict(g=12, gs=12, outs=150, er=36, r=36), 7)
        self.assertEqual(e['mode'], 'relief')
        P.resolve(p, e, 'accept', random.Random(2))
        self.assertEqual(p.position, 'RP')

    def test_full_course_requires_ten_days(self):
        p = pitcher()
        del p.flags
        p.career = {}
        today = timezone.localdate()
        token = today.toordinal()
        e = P.offer(p, {}, token, today)
        P.resolve(p, e, 'course', random.Random(2))
        self.assertIsNone(P.offer(p, {}, token + 5, today + timedelta(days=5)))
        self.assertEqual(P.offer(p, {}, token + 10, today + timedelta(days=10))['mode'], 'assessment')


class BalanceStorageTests(TestCase):
    def test_full_creation_preserves_pitching_choice_from_form(self):
        for track in ('SP', 'RP'):
            with self.subTest(track=track):
                u = member('form-' + track)
                self.client.force_login(u)
                response = self.client.post('/rookie/create/', dict(
                    role='pitcher', team='lg', region='서울', name='평가선수',
                    position='SS', pitch_position=track, focus_pitcher='control'),
                    HTTP_USER_AGENT='Mozilla/5.0')
                self.assertRedirects(response, '/rookie/', fetch_redirect_response=False)
                p = RookiePlayer.objects.get(user=u)
                self.assertEqual(P.current(p), track)
                self.assertEqual(p.focus, 'control')

    def test_split_retirement_guarantees_minor_salary_only_once(self):
        c = new('스플릿정산')
        c.flags = dict(contract=dict(years=2, annual=110000, minor_annual=4000, split=True), cash=0)
        initial = c.earnings
        self.assertEqual(B.settle_guarantee(c), 8000)
        self.assertEqual(B.settle_guarantee(c), 0)
        self.assertEqual(c.earnings, initial + 8000)

    def test_split_war_excludes_minor_without_changing_original(self):
        c = new('분리검사')
        s = LiteSeason.objects.create(career=c, year=1, age=25, league='mlb', games=162, war=9,
                                      totals={'g': 150, 'h': 200}, splits=[
                                          dict(league='mlb_aaa', totals={'g': 100, 'h': 150}, war=7, G=100),
                                          dict(league='mlb', totals={'g': 50, 'h': 50}, war=2, G=62)])
        self.assertEqual(B.totals(c)['war'], 2)
        self.assertEqual(X.career_line(c)['pro']['h'], 50)
        s.refresh_from_db()
        self.assertEqual(s.war, 9)

    def test_guaranteed_salary_settles_once(self):
        c = new('보장급여')
        c.flags = dict(contract=dict(years=2, annual=12000), cash=0)
        initial = c.earnings
        self.assertEqual(B.settle_guarantee(c), 24000)
        self.assertEqual(B.settle_guarantee(c), 0)
        self.assertEqual(c.earnings, initial + 24000)
        self.assertGreater(c.flags['cash'], 0)

    def test_midseason_conversion_creates_real_pitching_split(self):
        c = new('보직구간', role='pitcher', position='RP')
        c.league, c.club = 'kbo1', 'lg'
        c.stats = {k: 72 for k in M.PIT}
        e = P.offer(c, {}, c.year)
        state = dict(splits=[dict(league='kbo1', role='setup')])
        meeting = dict(about='pitch_role', phase='mid', pitch_event=e, half=state)
        with mock.patch.object(M, 'starter_game', return_value={'line': dict(g=1, gs=1, outs=18, er=1, r=1)}):
            X.resolve_meeting(c, meeting, 'trial', random.Random(2))
        self.assertEqual(state['splits'][-1]['role'], 'sp')
        self.assertEqual(state['splits'][-1]['from'], 3)
        self.assertEqual(c.seasons.count(), 0)

    def test_full_player_reply_persists_pitcher_position(self):
        u = member('정식보직')
        today = timezone.localdate()
        p = RookiePlayer.objects.create(user=u, name='전환선수', role='pitcher', position='RP', league='kbo1',
                                        club='lg', team='lg', age=25, stats={k: 72 for k in M.PIT}, potential=80,
                                        last_active=today, settled_through=today)
        e = dict(P.offer(p, {}, today.toordinal(), today), id='pitch-test')
        p.career['story_pending'] = e
        with mock.patch.object(M, 'starter_game', return_value={'line': dict(g=1, gs=1, outs=18, er=1, r=1)}):
            S.daily_reply(p, 'pitch-test', 'trial', random.Random(2), today)
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.position, 'SP')
        self.assertEqual(p.lineup, 'sp')

    def test_market_decision_cannot_overwrite_retirement(self):
        c = new('시장종료')
        c.league, c.club, c.age = 'kbo2', 'lg', 28
        e = B.market_event(c, .5)
        c.pending = dict(kind='decision', what='meeting', about='career_market', phase='end', market_event=e)
        X.decide(c, 'meeting', 'retire', random.Random(2))
        self.assertIsNotNone(c.retired_at)
        self.assertEqual(c.pending['kind'], 'retired')
