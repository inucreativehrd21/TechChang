"""마이너 패치: 재정비의 시즌 보장, 중간 중계와 결과, 기사·팬 반응 회귀 검사."""
import copy
import random
from collections import Counter
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase

from . import rookie_lite as X
from . import rookie_story as Story
from .models import LiteSeason
from .test_rookie_lite import MOBILE, PC, new


class LiteHotfixTests(TestCase):
    def test_reaction_style_is_three_to_seven_over_ten_seasons(self):
        c = new('반응비율')
        s = LiteSeason(career=c, year=1, age=18, league='hs', club=c.club, duty='주전', games=30,
                       totals=dict(pa=100, ab=90, h=30, hr=4, bb=10, so=15, sb=2), awards=[], months=[])
        counts = Counter()
        for year in range(1, 11):
            s.year = year
            reactions = X.season_reactions(c, s)
            counts.update(r['style'] for r in reactions)
            self.assertEqual(reactions, X.season_reactions(c, s))
        self.assertEqual(counts, {'standard': 9, 'community': 21})

    def test_every_social_choice_has_a_cost_or_an_unfulfilled_promise(self):
        n = 0
        for kind in ('manager', 'interview', 'conduct', 'rival'):
            signatures = set()
            for key, _label, _tone, _hint in Story.CHOICES[kind]:
                n += 1
                c = new(f'대가{n}')
                c.league, c.club, c.age = 'kbo1', 'lg', 26
                c.flags.update(confidence=50, trust=50, discipline=50, fame=50)
                stats = dict(c.stats)
                event = Story.encounter(c, kind, random.Random(1))
                before = {k: Story.value(c, k) for k in ('confidence', 'trust', 'discipline', 'fame')}
                rng = random.Random(1)
                with mock.patch.object(rng, 'random', return_value=.999):
                    Story.resolve(c, event, key, rng)
                delta = tuple(Story.value(c, k) - before[k] for k in before)
                self.assertTrue(any(v < 0 for v in delta) or c.flags.get('story_promise'), (kind, key, delta))
                signatures.add(delta)
                self.assertEqual(c.stats, stats)
            self.assertEqual(len(signatures), len(Story.CHOICES[kind]), kind)

    def test_saved_scene_gets_new_hints_without_changing_the_scouting_odds(self):
        c = new('저장힌트')
        m = X.make_moment(c, 'series', '한국시리즈 최종 승부', '10월', random.Random(2))
        original = copy.deepcopy(m)
        view = X.moment_view(c, m)
        self.assertEqual(m, original)
        self.assertEqual(view['opp']['fast'], m['opp']['fast'])
        self.assertNotIn('%', view['opp']['scout'])
        self.assertEqual([ch['key'] for ch in view['choices']], [ch[0] for ch in m['choices']])
        e = Story.encounter(c, 'highlight', random.Random(1))
        e['choices'][0]['hint'] = '이걸 고르면 유리해요'
        refreshed = Story.encounter_view(c, e)
        self.assertNotIn('유리해요', refreshed['choices'][0]['hint'])
        self.assertEqual(e['read'], refreshed['read'])
        self.assertEqual(e['id'], refreshed['id'])

    def test_mentor_has_learning_and_a_real_routine_cost(self):
        c = new('멘토대가')
        before = dict(c.stats)
        text = X.apply_event(c, 'mentor', 'accept', random.Random(1), {'injury': 0, 'train': 1, 'salary': 1})
        self.assertGreater(c.stats['eye'], before['eye'])
        self.assertEqual(Story.value(c, 'discipline'), 47)
        self.assertIn('자기 관리 −3', text)

    def test_rebuild_goes_to_training_without_second_release_review(self):
        for i, (role, pos, league) in enumerate([('batter', 'SS', 'kbo3'), ('pitcher', 'SP', 'kbo1'),
                                                ('pitcher', 'RP', 'mlb_aaa')]):
            with self.subTest(role=role, position=pos):
                c = new(f'재정비{i}', role, pos)
                c.age, c.year, c.league, c.club = 36, 21, league, 'nyy' if league == 'mlb_aaa' else 'lg'
                c.stats = {k: 35.0 for k in c.stats}
                c.ovr = 35
                c.flags = dict(c.flags, served=True)
                c.pending = dict(kind='decision', what='meeting', about='career_market', phase='end',
                                 market_event=X.Balance.market_event(c, .7))
                c.save()
                before = dict(c.stats)
                cache.clear()
                client = Client(HTTP_USER_AGENT=MOBILE)
                client.force_login(c.user)
                event_id = X.decision_view(c)['id']
                with mock.patch.object(X, 'next_step', side_effect=AssertionError('중복 방출 심사')):
                    response = client.post('/rookie/lite/act/', dict(action='decide', what='meeting',
                                          choice='rebuild', event_id=event_id))
                self.assertEqual(response.status_code, 302)
                c.refresh_from_db()
                self.assertIsNone(c.retired_at)
                self.assertEqual(c.pending['kind'], 'plan')
                self.assertEqual(c.stats, before)
                self.assertTrue(c.flags['rebuild_used'])
                self.assertNotIn('move', c.flags)
                self.assertEqual(c.position, 'RP' if role == 'pitcher' else pos)
                cache.clear()
                client.post('/rookie/lite/act/', dict(action='decide', what='meeting', choice='rebuild', event_id=event_id))
                c.refresh_from_db()
                self.assertIsNone(c.retired_at)
                self.assertEqual(c.pending['kind'], 'plan')

    def test_successful_retry_also_keeps_promised_season(self):
        c = new('테스트합격')
        c.age, c.league, c.club = 36, 'kbo3', 'lg'
        c.pending = dict(kind='decision', what='meeting', about='career_market', phase='end',
                         market_event=X.Balance.market_event(c, .7))
        rng = random.Random(1)
        with mock.patch.object(rng, 'random', return_value=0), mock.patch.object(X, 'next_step', side_effect=AssertionError):
            X.decide(c, 'meeting', 'retry', rng)
        self.assertIsNone(c.retired_at)
        self.assertEqual(c.pending['kind'], 'plan')

    def test_failed_retry_shows_result_before_explicit_retirement(self):
        c = new('테스트결과')
        c.age, c.league, c.club = 36, 'kbo3', 'lg'
        c.pending = dict(kind='decision', what='meeting', about='career_market', phase='end',
                         market_event=X.Balance.market_event(c, .7))
        before = dict(c.stats)
        rng = random.Random(1)
        with mock.patch.object(rng, 'random', return_value=.999):
            X.decide(c, 'meeting', 'retry', rng)
        self.assertIsNone(c.retired_at)
        self.assertEqual(c.stats, before)
        event = c.pending['market_event']
        self.assertIn('통과하지 못했어요', event['last_rejection'])
        self.assertEqual({ch['key'] for ch in event['choices']}, {'rebuild', 'retire'})
        X.decide(c, 'meeting', 'retire', rng)
        self.assertIsNotNone(c.retired_at)
        self.assertEqual(c.pending['kind'], 'retired')

    def test_midseason_board_stops_before_choice_and_resumes_after_result(self):
        c = new('중간중계')
        c.pending = {'kind': 'plan', 'event': None, 'intl': []}
        rng = random.Random(42)
        state = X.start_season(c, ['contact', 'power'], 'normal', '', {}, rng)
        event = Story.encounter(c, 'interview', rng)
        c.pending = dict(kind='decision', what='meeting', about='interview', phase='mid', half=state, encounter=event)
        c.save()
        self.assertFalse(c.seasons.exists())
        self.assertTrue(all(not line for line in state['splits'][0]['chunks'][3:]))
        for ua in (PC, MOBILE):
            cache.clear()
            client = Client(HTTP_USER_AGENT=ua)
            client.force_login(c.user)
            response = client.get('/rookie/lite/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context['season']['months']), 3)
            self.assertContains(response, '전반기를 마쳤어요')
            self.assertContains(response, 'data-rl-scene')
            html = response.content.decode()
            self.assertLess(html.index('data-rl-ticker'), html.index('data-rl-scene'))
        with mock.patch.object(X, 'moments_for', return_value=[]), mock.patch.object(X, 'TOURNAMENTS', {}):
            text = X.decide(c, 'meeting', 'team', rng)
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.pending['kind'], 'review')
        self.assertEqual(c.pending['playback']['from'], 3)
        self.assertIn(text, c.seasons.get().news)
        cache.clear()
        response = client.get('/rookie/lite/')
        html = response.content.decode()
        self.assertContains(response, ' data-rl-row-seen>', count=3)
        self.assertLess(html.index('aria-label="선택 결과"'), html.index('data-rl-ticker'))
        self.assertContains(response, '가상 커뮤니티 반응')

    def test_news_uses_season_records_and_never_consumes_game_randomness(self):
        c = new('기사검사')
        s = LiteSeason(career=c, year=3, age=18, league='hs', club=c.club, duty='주전', games=30,
                       totals=dict(pa=100, ab=90, h=30, hr=4, bb=10, so=15, sb=2), awards=[], months=[])
        before = copy.deepcopy((c.stats, c.flags, s.totals))
        rng_state = random.getstate()
        articles = X.season_press(c, s, [])
        reactions = X.season_reactions(c, s)
        self.assertIn('[기록 분석]', [n['tag'] for n in articles])
        self.assertIn('[유망주]', [n['tag'] for n in articles])
        self.assertIn('[대회 결산]', [n['tag'] for n in articles])
        self.assertEqual(len(reactions), 3)
        self.assertEqual(reactions, X.season_reactions(c, s))
        self.assertEqual(random.getstate(), rng_state)
        self.assertEqual((c.stats, c.flags, s.totals), before)
        self.assertIn('OPS', reactions[1]['text'])
