"""선택이 실제 계산에 반영되는지, 협상·국대 보상이 중복되지 않는지 검증한다."""
import copy
import random
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from community import rookie_story as S
from community import rookie_lite as X
from community import rookie_career as C
from community import rookie_league as L
from community import rookie_sim as M
from community.test_rookie_lite import pro
from community.test_rookie_league import player, active_on, D1
from datetime import timedelta


def demo(role='batter'):
    return SimpleNamespace(flags={}, stats={k: 64 for k in (M.BAT if role == 'batter' else M.PIT)},
                           role=role, age=25, league='kbo1', position='OF' if role == 'batter' else 'SP', ovr=74)


class MindTests(SimpleTestCase):
    def test_neutral_values_preserve_existing_simulation(self):
        p = demo()
        self.assertEqual(S.game_stats(p, p.stats), p.stats)
        self.assertEqual(S.training_mult(p), 1)

    def test_confidence_changes_both_roles_without_permanent_growth(self):
        for role in ('batter', 'pitcher'):
            p = demo(role)
            original = dict(p.stats)
            p.flags['confidence'] = 100
            affected = ('contact', 'eye') if role == 'batter' else ('control', 'mental')
            self.assertTrue(all(n == original[k] + (1.25 if k in affected else 0) for k, n in S.game_stats(p, p.stats).items()))
            p.flags['confidence'] = 0
            self.assertTrue(all(n == original[k] - (1.25 if k in affected else 0) for k, n in S.game_stats(p, p.stats).items()))
            self.assertEqual(p.stats, original)

    def test_clamped_changes_recover_and_preserve_json_reference(self):
        p = demo()
        flags = p.flags
        S.change(p, '성공', confidence=1000, discipline=-1000)
        self.assertIs(p.flags, flags)
        self.assertEqual((S.value(p, 'confidence'), S.value(p, 'discipline')), (100, 0))
        S.recover(p)
        self.assertEqual(S.value(p, 'confidence'), 77.5)
        self.assertAlmostEqual(S.training_mult(p), .9325)

    def test_interview_changes_trust_training_and_public_promise(self):
        p = demo()
        event = S.encounter(p, 'interview', random.Random(1))
        S.resolve(p, event, 'ambition', random.Random(2))
        self.assertTrue(p.flags['story_promise'])
        self.assertEqual(S.value(p, 'confidence'), 60)
        text = S.settle_promise(p, -.5)
        self.assertIn('미치지', text)
        self.assertEqual(S.value(p, 'confidence'), 48)
        self.assertIsNone(p.flags.get('story_promise'))
        self.assertEqual(S.settle_promise(p, 1), '')

    def test_interview_invalid_input_does_not_change_state(self):
        p = demo()
        event = S.encounter(p, 'interview', random.Random(1))
        with self.assertRaises(ValueError):
            S.resolve(p, event, 'forged', random.Random(1))
        self.assertEqual(p.flags, {})

    def test_success_and_failure_move_confidence_in_opposite_directions(self):
        p = demo()
        event = S.encounter(p, 'highlight', random.Random(1))
        with mock.patch.object(M, '_pick', return_value='HR'):
            S.resolve(p, event, 'fast', random.Random(1))
        self.assertEqual(S.value(p, 'confidence'), 60)
        with mock.patch.object(M, '_pick', return_value='SO'):
            S.resolve(p, event, 'fast', random.Random(1))
        self.assertEqual(S.value(p, 'confidence'), 52)

    def test_scouting_read_changes_success_probability(self):
        p = demo()
        event = S.encounter(p, 'highlight', random.Random(1))
        event['read'] = 'fast'
        good = bad = 0
        for seed in range(700):
            a, b = demo(), demo()
            S.resolve(a, event, 'fast', random.Random(seed))
            good += S.value(a, 'confidence') > 50
            S.resolve(b, event, 'break', random.Random(seed))
            bad += S.value(b, 'confidence') > 50
        self.assertGreater(good, bad + 20)

    def test_confidence_materially_changes_batting_results(self):
        totals = []
        for confidence in (10, 90):
            p = demo()
            p.flags['confidence'] = confidence
            t = {}
            for seed in range(500):
                result = M.batter_game(S.game_stats(p, p.stats), 'OF', 64, random.Random(seed), role='lower', slot=7)
                t = L.add(t, result['line'])
            totals.append(L.batting(t)['ops'])
        self.assertGreater(totals[1] - totals[0], .01)
        self.assertLess(totals[1] - totals[0], .04)

    def test_negotiation_choices_and_reputation_change_probability(self):
        p = demo()
        offers = S.posting_offers(p, random.Random(5))
        self.assertEqual(len({o['team'] for o in offers}), 3)
        d = offers[0]
        self.assertGreater(S.deal_chance(p, d, 'compromise'), S.deal_chance(p, d, 'salary'))
        before = S.deal_chance(p, d, 'salary')
        p.flags.update(fame=80, intl_rep=25)
        self.assertGreater(S.deal_chance(p, d, 'salary'), before)

    def test_three_failed_rounds_end_negotiation(self):
        p = demo()
        deal = S.posting_offers(p, random.Random(1))[0]
        rng = mock.Mock(random=lambda: .999)
        for expected in ('counter', 'counter', 'failed'):
            status, deal = S.negotiate(p, deal, 'salary', rng)
            self.assertEqual(status, expected)


class StoryEngineTests(TestCase):
    def test_posting_requires_negotiation_before_transfer(self):
        c = pro('협상선수', ovr=74)
        offers = S.posting_offers(c, random.Random(4))
        c.pending = dict(kind='decision', what='posting', offers=offers)
        club = c.club
        X.decide(c, 'posting', offers[0]['key'], random.Random(2))
        self.assertEqual(c.club, club)
        self.assertEqual(c.pending['what'], 'negotiation')
        keys = {ch['key'] for ch in X.decision_view(c)['choices']}
        self.assertIn('accept', keys)
        self.assertEqual('minor_veto' in keys, offers[0]['system'] == 'mlb' and offers[0].get('entry_league', 'mlb') == 'mlb')
        rng = random.Random(2)
        with mock.patch.object(S, 'negotiate', return_value=('signed', dict(offers[0], annual=offers[0]['annual'] * .9))):
            X.decide(c, 'negotiation', 'compromise', rng)
        self.assertEqual(c.club, offers[0]['team'])
        self.assertGreater(c.flags['contract']['annual'], 0)

    def test_failed_posting_preserves_kbo_team(self):
        c = pro('협상실패', ovr=74)
        c.pending = dict(kind='decision', what='negotiation', deal=dict(S.posting_offers(c, random.Random(4))[0], round=2))
        old = c.league, c.club
        X.decide(c, 'negotiation', 'leave', random.Random(2))
        self.assertEqual((c.league, c.club), old)
        self.assertTrue(c.flags['posted'])

    def test_forged_posting_team_is_rejected(self):
        c = pro('협상위조', ovr=74)
        c.pending = dict(kind='decision', what='posting', offers=S.posting_offers(c, random.Random(4)))
        with self.assertRaises(X.LiteError):
            X.decide(c, 'posting', 'fake-team', random.Random(2))

    def test_international_participation_always_pays_once(self):
        c = pro('대표보상', ovr=74)
        c.flags.update(fame=0, cash=0)
        for key in X.INTL:
            before = X.cash(c), S.value(c, 'fame')
            text = X.national_reward(c, key, 'entry')
            self.assertGreater(X.cash(c), before[0])
            self.assertGreater(S.value(c, 'fame'), before[1])
            after = copy.deepcopy(c.flags), c.earnings
            self.assertEqual(X.national_reward(c, key, 'entry'), '')
            self.assertEqual((c.flags, c.earnings), after)
            self.assertIn('인기', text)

    def test_lite_midseason_choice_resumes_same_season(self):
        c = pro('시즌장면', ovr=68)
        c.pending['event'] = None
        rng = random.Random(5)
        with mock.patch.object(X, 'break_meeting', return_value=None), mock.patch.object(rng, 'random', return_value=.3):
            result = X.run_season(c, X.pick_programs(c, rng), 'normal', '', rng)
        self.assertIsNone(result)
        pending = c.pending
        self.assertIn('encounter', pending)
        choice = pending['encounter']['choices'][0]['key']
        X.decide(c, 'meeting', choice, random.Random(4))
        self.assertEqual(c.seasons.count(), 1)
        self.assertIn('confidence', c.flags)

    def test_full_daily_choice_rejects_replay(self):
        p = player('정식선택')
        event = S.encounter(p, 'interview', random.Random(1))
        p.career['story_pending'] = event
        S.daily_reply(p, event['id'], 'team', random.Random(1), D1)
        with self.assertRaises(ValueError):
            S.daily_reply(p, event['id'], 'team', random.Random(1), D1)
        self.assertEqual(S.value(p, 'trust'), 60)

    def test_full_daily_draw_is_stable_for_same_day(self):
        p = player('정식일일')
        S.prepare_daily(p, D1)
        before = copy.deepcopy(p.career)
        S.prepare_daily(p, D1)
        self.assertEqual(p.career, before)

    def test_unanswered_scene_does_not_freeze_confidence(self):
        p = player('미답회복')
        event = S.encounter(p, 'interview', random.Random(1))
        p.career.update(story_pending=event, story_date=D1.isoformat(), confidence=90)
        S.prepare_daily(p, D1 + timedelta(days=1))
        self.assertEqual(p.career['story_pending']['id'], event['id'])
        self.assertEqual(S.value(p, 'confidence'), 72)

    def test_full_game_stats_uses_confidence(self):
        p = player('정식경기')
        p.career['confidence'] = 85
        self.assertGreater(C.game_stats(p)['contact'], p.stats['contact'])

    def test_public_promise_is_settled_by_actual_full_game_records(self):
        p = player('약속평가', level=64)
        p.career['story_promise'] = {'target': 50, 'since': (D1 - timedelta(days=3)).isoformat(), 'label': '평균보다 좋은 성적'}
        p.save(update_fields=['career'])
        active_on(p, D1)
        L.simulate_day(D1, random.Random(4))
        p.refresh_from_db()
        self.assertNotIn('story_promise', p.career)
        self.assertLess(S.value(p, 'confidence'), 50)

    def test_actual_lite_scene_renders_on_pc_and_mobile(self):
        c = pro('장면노출', ovr=74)
        c.pending = dict(kind='decision', what='meeting', about='highlight', phase='mid',
                         encounter=S.encounter(c, 'highlight', random.Random(4)))
        c.save()
        self.client.force_login(c.user)
        for ua in ('Mozilla/5.0 (Windows NT 10.0)', 'Mozilla/5.0 (iPhone) Mobile/15E148'):
            response = self.client.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'rs-story-scene')
            self.assertContains(response, c.pending['encounter']['id'])

    def test_full_post_is_owned_and_cannot_be_replayed(self):
        p = player('정식요청')
        event = S.encounter(p, 'interview', random.Random(1))
        p.career.update(story_pending=event, story_date=D1.isoformat())
        p.save(update_fields=['career'])
        self.client.force_login(p.user)
        self.assertEqual(self.client.get('/rookie/story/').status_code, 405)
        with mock.patch('community.views.rookie_views.timezone.localdate', return_value=D1):
            response = self.client.post('/rookie/story/', {'event_id': event['id'], 'choice': 'team'})
            self.assertEqual(response.status_code, 302)
            p.refresh_from_db()
            once = copy.deepcopy(p.career)
            self.client.post('/rookie/story/', {'event_id': event['id'], 'choice': 'team'})
            p.refresh_from_db()
            self.assertEqual(p.career, once)

    def test_lite_rejects_old_scene_identifier(self):
        c = pro('라이트중복', ovr=74)
        offers = S.posting_offers(c, random.Random(4))
        c.pending = dict(kind='decision', what='negotiation', deal=dict(offers[0], round=0))
        c.save()
        self.client.force_login(c.user)
        before = copy.deepcopy(c.pending)
        self.client.post('/rookie/lite/act/', {'action': 'decide', 'what': 'negotiation', 'choice': 'salary', 'event_id': 'old-round'})
        c.refresh_from_db()
        self.assertEqual(c.pending, before)

    @override_settings(DEBUG=True)
    def test_new_scenes_render_both_editions_without_creating_players(self):
        for edition in ('full', 'lite'):
            for scene in ('manager', 'interview', 'conduct', 'highlight', 'posting', 'negotiation'):
                response = self.client.get(f'/rookie/preview/?edition={edition}&scene={scene}', HTTP_USER_AGENT='Mozilla/5.0')
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'rs-story-scene')
