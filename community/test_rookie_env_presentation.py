"""조건부 특성 화면의 비공개 경계와 기록 해석을 검증해요."""
from types import SimpleNamespace
from django.test import SimpleTestCase, TestCase, override_settings
from django.template.loader import render_to_string
from community import rookie_env_presentation as UI


@override_settings(ROOKIE_ENV_ENABLED=True, GAME_CONTROLS_USE_DB=False)
class EnvironmentPresentationTests(SimpleTestCase):
    def test_reveal_reads_only_known_traits_and_includes_big_stage_news(self):
        c = SimpleNamespace(traits_seen=['rain_man', 'global'], traits=['rain_man', 'global', 'cold_weak'])
        s = SimpleNamespace(env={'revealed': ['rain_man', 'cold_weak']}, news=[
            '숨은 특성 발견 — 비 오는 날의 사나이: 비 타율 .333(시즌 .267)',
            '숨은 특성 발견 — 국제대회 체질: WBC 결승에서 기회를 살렸어요'])
        items = UI.discoveries(c, s)
        self.assertEqual([t['key'] for t in items], ['rain_man', 'global'])
        self.assertIn('WBC 결승', items[1]['evidence'])
        self.assertEqual(s.env, {'revealed': ['rain_man', 'cold_weak']})

    def test_scout_report_discovery_and_switch_off(self):
        c = SimpleNamespace(traits_seen=['heat_weak', 'rain_man'])
        s = SimpleNamespace(env={}, news=['스카우팅 리포트 — 숨은 특성: 더위에 약함'])
        self.assertEqual([t['key'] for t in UI.discoveries(c, s)], ['heat_weak'])
        with override_settings(ROOKIE_ENV_ENABLED=False):
            self.assertEqual(UI.discoveries(c, s), [])
            self.assertNotIn('icon', UI.visible_traits(c)[0])

    def test_weakness_is_named_and_colored_without_claiming_a_championship(self):
        html = render_to_string('community/games/_lite_trait_discovery.html', {
            'trait_discoveries': [dict(UI.trait('cold_weak'), evidence='한파 12경기')], 'trait_preview': True})
        self.assertIn('is-weak', html)
        self.assertIn('약점', html)
        self.assertNotIn('rl-mfx-confetti', html)
        self.assertIn('role="dialog"', html)
        self.assertIn('data-rl-mfx-close', html)

    def test_dome_is_not_counted_twice_and_wind_direction_is_visible(self):
        items = UI.game_conditions({'weather': '돔', 'time': '야간', 'park': 'dome', 'crowd': '만원'})
        self.assertEqual([i['label'] for i in items], ['돔', '야간', '만원 관중'])
        self.assertIn('맞바람', [i['label'] for i in UI.game_conditions({'weather': '강풍', 'wind': 'in'})])
        self.assertEqual(UI.game_conditions(None), [])

    def test_batting_and_pitching_splits_keep_the_original_rates_and_small_samples(self):
        for role in ('batter', 'pitcher'):
            ctx = UI.preview_context(role)
            grouped = [r for g in ctx['env_groups'] for r in g['rows']]
            self.assertEqual(len(grouped), len(ctx['env_rows']))
            for row in grouped:
                original = next(r for r in ctx['env_rows'] if r['key'] == row['key'])
                self.assertEqual(row['rate'], original['rate'])
                self.assertGreaterEqual(row['width'], 0)
                self.assertLessEqual(row['width'], 100)
            self.assertTrue(next(r for r in grouped if r['key'] == '한파')['small'])
            self.assertEqual(len(ctx['routines']), 6)


@override_settings(ROOKIE_ENV_ENABLED=True)
class RoutineDraftTests(TestCase):
    def test_shop_draft_preserves_routine_and_rejects_unknown_values(self):
        import random
        from django.contrib.auth.models import User
        from django.http import QueryDict
        from community import rookie_lite as X
        from community.views.rookie_lite_views import _save_plan_draft, _plan_key
        c = X.create(User.objects.create(username='routine-draft'), name='루틴선수', role='batter', position='SS',
                     style='contact', region='서울', team='lg', rng=random.Random(7))
        data = QueryDict('', mutable=True)
        data.update(_draft_key=_plan_key(c), _draft_routine='night')
        _save_plan_draft(c, data)
        self.assertEqual(c.pending['draft']['routine'], 'night')
        data['_draft_routine'] = 'unknown'
        _save_plan_draft(c, data)
        self.assertNotIn('routine', c.pending['draft'])
