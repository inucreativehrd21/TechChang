"""계약 선택이 강등·출전·실제 급여·이적에 미치는 결과를 검증해요."""
import copy
import random
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from . import rookie as R
from . import rookie_contracts as K
from . import rookie_story as S
from . import rookie_lite as X
from . import rookie_league as L
from .test_rookie_lite import pro, PC, MOBILE
from .test_rookie_league import player, active_on, D1


def offer(**extra):
    return K.terms(dict(dict(key='nyy', system='mlb', team='nyy', years=3, annual=600000,
                            budget=690000, role='주전 경쟁', interest=.6), **extra))


def with_contract(p, **extra):
    p.league, p.club = 'mlb', 'nyy'
    S.put(p, dict(S.state(p), contract=K.signed(offer(**extra), getattr(p, 'year', 1))))
    return p


class ContractTermsTests(SimpleTestCase):
    def setUp(self):
        self.p = SimpleNamespace(flags={}, league='kbo1', club='lg', ovr=74, role='batter')
        self.yes = mock.Mock(random=lambda: 0)
        self.no = mock.Mock(random=lambda: .999)

    def test_default_acceptance_does_not_grant_assignment_or_optout_rights(self):
        status, d = S.negotiate(self.p, offer(), 'accept', self.yes)
        self.assertEqual(status, 'signed')
        self.assertFalse(d['minor_veto'])
        self.assertFalse(d['player_opt_out'])
        self.assertFalse(d['split'])  # 보장 연봉과 강등 거부권은 별개예요.

    def test_veto_ultimatum_is_risky_and_rejection_ends_talks_immediately(self):
        d = offer()
        self.assertGreater(S.deal_chance(self.p, d, 'accept') - S.deal_chance(self.p, d, 'minor_veto'), .4)
        status, rejected = S.negotiate(self.p, d, 'minor_veto', self.no)
        self.assertEqual(status, 'failed')
        self.assertFalse(rejected['minor_veto'])
        status, agreed = S.negotiate(self.p, d, 'minor_veto', self.yes)
        self.assertEqual(status, 'signed')
        self.assertTrue(agreed['minor_veto'])

    def test_salary_for_rights_is_a_real_cost(self):
        d = offer()
        self.assertGreater(S.deal_chance(self.p, d, 'veto_discount'), S.deal_chance(self.p, d, 'minor_veto'))
        status, agreed = S.negotiate(self.p, d, 'veto_discount', self.yes)
        self.assertEqual(status, 'signed')
        self.assertTrue(agreed['minor_veto'])
        self.assertEqual(agreed['annual'], 390000)
        self.assertEqual(d['annual'], 600000)

    def test_failed_requests_do_not_leak_into_counteroffers(self):
        for choice, field in [('veto_discount', 'minor_veto'), ('opt_out', 'player_opt_out')]:
            status, counter = S.negotiate(self.p, offer(), choice, self.no)
            self.assertEqual(status, 'counter')
            self.assertFalse(counter[field])
        _, counter = S.negotiate(self.p, offer(), 'salary', self.no)
        self.assertLess(counter['annual'], 600000)

    def test_npb_cannot_submit_mlb_clauses(self):
        with self.assertRaises(ValueError):
            S.negotiate(self.p, dict(offer(), system='npb'), 'minor_veto', self.yes)

    def test_guaranteed_pay_is_retained_in_minors_but_split_pay_is_prorated(self):
        rows = [{'league': 'mlb', 'from': 0, 'to': 3}, {'league': 'mlb_aaa', 'from': 3, 'to': 6}]
        self.assertEqual(K.salary(offer(), rows), 600000)
        self.assertEqual(K.salary(offer(split=True, minor_annual=6000), rows), 303000)
        self.assertEqual(K.salary(offer(split=True, minor_annual=6000), league='mlb_aaa'), 6000)

    def test_refusal_requires_rights_and_does_not_buy_a_starting_job(self):
        with_contract(self.p)
        with self.assertRaises(ValueError):
            K.assignment_reply(self.p, 'refuse', self.yes, 1)
        self.p.flags['contract']['minor_veto'] = True
        K.assignment_reply(self.p, 'refuse', self.yes, 1)
        self.assertEqual(self.p.league, 'mlb')
        self.assertEqual(self.p.flags['mlb_bench_season'], 1)
        self.assertEqual(K.bench_role(self.p)[0], 'bench')

    def test_five_mlb_service_seasons_grant_consent_even_without_clause(self):
        with_contract(self.p)
        self.p.flags['mlb_service'] = 4.99
        self.assertFalse(K.veto(self.p))
        self.p.flags['mlb_service'] = 5
        self.assertTrue(K.veto(self.p))


class ContractCareerTests(TestCase):
    def test_new_foreign_deal_clears_previous_system_promotion(self):
        c = pro('리그예약정리', ovr=74)
        c.league, c.club = 'mlb_aaa', 'nyy'
        c.flags['move'] = {'kind': 'promote', 'to': 'mlb'}
        d = offer(system='npb', team='orix')
        c.pending = dict(kind='decision', what='negotiation', deal=d)
        with mock.patch.object(S, 'negotiate', return_value=('signed', d)):
            X.decide(c, 'negotiation', 'accept', random.Random(2))
        self.assertEqual((c.league, c.club), ('npb1', 'orix'))
        self.assertNotIn('move', c.flags)
        self.assertIsNone(X.end_meeting(c, random.Random(2)))

    def test_legacy_cross_system_promotion_does_not_move_japanese_club_to_mlb(self):
        c = pro('이전예약보호', ovr=74)
        c.league, c.club = 'npb1', 'orix'
        c.flags['move'] = {'kind': 'promote', 'to': 'mlb'}
        self.assertIsNone(X.end_meeting(c, random.Random(2)))
        self.assertEqual((c.league, c.club), ('npb1', 'orix'))

    def lite(self, name, **extra):
        c = with_contract(pro(name, ovr=74), **extra)
        c.pending = X.plan_step(c, random.Random(1))
        c.pending['event'] = None
        c.pending['intl'] = []
        c.save()
        return c

    def test_unprotected_player_can_lose_opening_mlb_spot(self):
        c = self.lite('개막강등', split=True)
        rng = random.Random(2)
        with mock.patch.object(rng, 'random', return_value=.01), mock.patch.object(X, 'break_meeting', return_value=None):
            X.run_season(c, X.pick_programs(c, rng), 'normal', '', rng)
        c.refresh_from_db()
        self.assertEqual(c.league, 'mlb_aaa')
        # 시즌 중 일반 장면이 나와도 전반기는 이미 마이너에서 치렀어요.
        if c.pending.get('what') == 'meeting':
            self.assertEqual(c.pending['half']['splits'][0]['league'], 'mlb_aaa')

    def test_protected_opening_assignment_pauses_and_refusal_uses_bench_in_simulator(self):
        c = self.lite('거부권실행', minor_veto=True)
        rng = random.Random(2)
        programs = X.pick_programs(c, rng)
        with mock.patch.object(rng, 'random', return_value=0):
            self.assertIsNone(X.run_season(c, programs, 'normal', '', rng))
        self.assertEqual(c.pending['phase'], 'camp')
        self.assertIn('refuse', {ch['key'] for ch in X.decision_view(c)['choices']})
        X.decide(c, 'meeting', 'refuse', rng)
        self.assertEqual(c.pending['kind'], 'plan')
        state = X.start_season(c, programs, 'normal', '', {}, rng)
        self.assertEqual(state['splits'][0]['role'], 'bench')
        self.assertEqual(c.league, 'mlb')

    def test_midseason_minor_assignment_changes_real_split_pay_and_service(self):
        c = self.lite('분할지급', split=True)
        rng = random.Random(7)
        state = X.start_season(c, X.pick_programs(c, rng), 'normal', '', {}, rng)
        c.pending = dict(kind='decision', what='meeting', about='demote', phase='mid', to='mlb_aaa', half=state)
        X.decide(c, 'meeting', 'accept', rng)
        season = c.seasons.get(year=c.year - 1)
        self.assertEqual(season.salary, 303000)
        self.assertEqual(c.salary, 303000)
        self.assertAlmostEqual(c.flags['mlb_service'], .5)
        self.assertEqual([s['league'] for s in season.splits], ['mlb', 'mlb_aaa'])
        self.assertEqual(c.flags['contract']['years'], 2)
        self.assertIn('playback', c.pending)
        self.assertTrue(c.pending['playback']['title'])

    def test_bad_meeting_cannot_bypass_minor_veto(self):
        c = self.lite('불화보호', minor_veto=True)
        m = dict(about='role_down', phase='mid', merit=-10, line='', new_role=['bench', 0, '벤치'], old_role=['lower', 6, '하위'])
        X.resolve_meeting(c, m, 'argue', mock.Mock(random=lambda: .01))
        self.assertEqual(c.league, 'mlb')

    def test_optout_waives_guarantee_before_new_talks_and_can_fail(self):
        c = self.lite('옵트아웃', player_opt_out=True)
        c.flags['contract'].update(elapsed=1, years=2)
        c.pending = dict(kind='decision', what='contract_optout')
        X.decide(c, 'contract_optout', 'market', random.Random(4))
        self.assertNotIn('contract', c.flags)
        self.assertEqual(c.flags['last_contract']['ended'], 'optout')
        self.assertEqual(c.pending['what'], 'posting')
        X.decide(c, 'posting', c.pending['offers'][0]['key'], random.Random(4))
        X.decide(c, 'negotiation', 'leave', random.Random(4))
        self.assertEqual((c.league, c.club), ('kbo2', c.team))
        self.assertNotIn('contract', c.flags)

    def test_keeping_contract_only_prompts_once_per_season(self):
        c = self.lite('계약유지', player_opt_out=True)
        c.flags['contract']['elapsed'] = 1
        c.pending = dict(kind='decision', what='contract_optout')
        X.decide(c, 'contract_optout', 'keep', random.Random(4))
        self.assertEqual(c.flags['contract']['annual'], 600000)
        self.assertNotEqual(c.pending.get('what'), 'contract_optout')

    def test_assignment_form_is_shared_and_stale_submission_is_rejected(self):
        c = self.lite('계약화면', minor_veto=True)
        c.pending = dict(kind='decision', what='meeting', about='demote', phase='camp', to='mlb_aaa', plan=c.pending)
        c.save()
        self.client.force_login(c.user)
        for ua in (PC, MOBILE):
            response = self.client.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(response, '계약서의 작은 글씨')
            self.assertContains(response, 'name="event_id"')
        before = copy.deepcopy(c.pending)
        self.client.post('/rookie/lite/act/', dict(action='decide', what='meeting', choice='refuse', event_id='stale'))
        c.refresh_from_db()
        self.assertEqual(c.pending, before)
        self.assertEqual(c.league, 'mlb')

    def test_full_game_obeys_assignment_rights_and_records_minor_pay(self):
        p = with_contract(player('정식거부권', level=74, league='mlb'), minor_veto=True, split=True)
        p.save()
        active_on(p, D1)
        with mock.patch.object(K, 'camp_risk', return_value=1):
            L.simulate_day(D1, random.Random(1))
        p.refresh_from_db()
        self.assertTrue(p.career['assignment_pending'])
        self.assertEqual((p.league, p.lineup), ('mlb', 'bench'))
        event_id = p.career['assignment_pending']['id']
        S.daily_reply(p, event_id, 'accept', random.Random(1), D1)
        p.save()
        with self.assertRaises(ValueError):
            S.daily_reply(p, event_id, 'accept', random.Random(1), D1)
        active_on(p, D1 + timedelta(days=1))
        L.simulate_day(D1 + timedelta(days=1), random.Random(1))
        p.refresh_from_db()
        self.assertEqual(p.league, 'mlb_aaa')
        self.assertAlmostEqual(p.career['mlb_service'], 1 / L.SEASON_DAYS)
        self.assertAlmostEqual(p.career['mlb_contract_income'], (600000 + 6000) / L.SEASON_DAYS, places=1)

    def test_full_inactivity_cannot_force_demotion_without_consent(self):
        p = with_contract(player('정식감쇠', level=60, league='mlb'), minor_veto=True)
        p.settled_through = D1 - timedelta(days=3)
        p.last_active = D1 - timedelta(days=3)
        p.save()
        R._decay(p, D1)
        p.refresh_from_db()
        self.assertEqual(p.league, 'mlb')
        self.assertTrue(p.career['assignment_pending'])
        S.daily_reply(p, p.career['assignment_pending']['id'], 'refuse', random.Random(4), D1)
        p.settled_through = D1 - timedelta(days=1)
        R._decay(p, D1 + timedelta(days=1))
        self.assertNotIn('assignment_pending', p.career)
        K.full_assignment(p, D1 + timedelta(days=1), mock.Mock(random=lambda: 0))
        self.assertNotIn('assignment_pending', p.career)

    def test_trade_in_minors_keeps_contract_and_negotiated_rights(self):
        c = self.lite('권리승계', minor_veto=True)
        c.league = 'mlb_aaa'
        m = dict(about='demote', phase='mid', to='mlb_aa', merit=10, line='')
        X.resolve_meeting(c, m, 'trade', random.Random(4))
        self.assertNotEqual(c.club, 'nyy')
        self.assertTrue(K.veto(c))
        self.assertEqual(c.flags['contract']['team'], c.club)

    def test_active_mlb_contract_avoids_legacy_release_and_forced_retirement(self):
        c = self.lite('계약잔류')
        c.age, c.ovr = 38, 50
        d = X.next_step(c, mock.Mock(random=lambda: 0), skip_meeting=True)
        self.assertEqual(d['what'], 'return')

    def test_full_contract_expires_once_and_drops_protections(self):
        p = with_contract(player('정식기간', level=74, league='mlb'), minor_veto=True)
        K.roll_full(p, 2)
        self.assertEqual(p.career['contract']['years'], 2)
        K.roll_full(p, 2)
        self.assertEqual(p.career['contract']['years'], 2)
        K.roll_full(p, 4)
        self.assertIsNone(K.active(p))
        self.assertFalse(K.veto(p))

    def test_legacy_contracts_are_not_retroactively_split(self):
        c = pro('기존계약', ovr=74)
        c.league, c.club = 'mlb_aaa', 'nyy'
        c.flags['contract'] = dict(years=2, annual=600000)
        self.assertEqual(X.salary_for(c, 0), 600000)

    def test_expiry_opens_new_market_instead_of_free_mlb_roster_spot(self):
        c = self.lite('계약만료')
        c.flags['last_contract'] = dict(c.flags.pop('contract'), ended='expired')
        c.pending = X.next_step(c, random.Random(4))
        self.assertEqual((c.league, c.club), ('kbo2', c.team))
        self.assertEqual(c.pending['what'], 'posting')
        self.assertEqual(len(c.pending['offers']), 3)
        X.decide(c, 'posting', 'stay', random.Random(4))
        self.assertEqual(c.league, 'kbo2')
        self.assertIsNone(K.expiry_market(c, random.Random(4)))

    def test_full_expiry_prepares_a_market_and_saves_fallback_club(self):
        p = with_contract(player('정식만료', level=74, league='mlb'))
        S.prepare_daily(p, L.season_bounds(4)[0])
        self.assertEqual(p.league, 'kbo2')
        self.assertEqual(p.career['story_pending']['kind'], 'posting')
        self.assertEqual(len(p.career['story_pending']['offers']), 3)

    def test_mlb_fa_selection_also_requires_negotiation(self):
        c = pro('FA협상', ovr=74)
        c.pending = dict(kind='decision', what='fa', offers=[dict(key='mlb', team='nyy', years=3, annual=600000)])
        X.decide(c, 'fa', 'mlb', random.Random(4))
        self.assertEqual(c.league, 'kbo1')
        self.assertEqual(c.pending['what'], 'negotiation')
        self.assertFalse(c.pending['deal']['minor_veto'])

    @override_settings(DEBUG=True)
    def test_previews_do_not_modify_a_real_career(self):
        c = self.lite('미리보기보존')
        before = copy.deepcopy(c.flags)
        for scene in ('negotiation', 'assignment', 'optout'):
            response = self.client.get('/rookie/preview/', {'scene': scene}, HTTP_USER_AGENT=PC)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '계약서의 작은 글씨')
        c.refresh_from_db()
        self.assertEqual(c.flags, before)
