"""익스트림은 비공개로 유지하고 라이트 기록·진행을 바꾸지 않는지 확인해요."""
from copy import deepcopy
from io import StringIO
import random

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import rookie_extreme as E
from . import rookie_extreme_preview as P
from . import rookie_lite as X
from . import rookie_modes as Modes
from .models import LiteCareer, LiteSeason

PC = 'Mozilla/5.0 Windows NT 10.0 Chrome/130'


@override_settings(ROOKIE_EXTREME_PREVIEW=True)
class ExtremeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('private-preview', password=None, is_staff=True)

    def create(self, mode='extreme', user=None, seed=41):
        return X.create(user or self.user, mode=mode, name='시제품', role='batter', position='SS',
                         style=next(iter(X.STYLES['batter'])), region='서울', team='lg', rng=random.Random(seed))

    def test_default_off_and_active_staff_required(self):
        with override_settings(ROOKIE_EXTREME_PREVIEW=False):
            with self.assertRaises(X.LiteError):
                self.create()
        member = User.objects.create_user('normal')
        with self.assertRaises(X.LiteError):
            self.create(user=member)
        self.user.is_active = False
        with self.assertRaises(X.LiteError):
            self.create()
        self.assertFalse(LiteCareer.objects.exists())

    def test_two_modes_coexist_and_existing_lite_values_are_not_changed(self):
        lite = self.create('lite')
        before = deepcopy(lite.__dict__)
        extreme = self.create()
        lite.refresh_from_db()
        self.assertEqual(lite.mode, 'lite')
        for key in ('stats', 'flags', 'pending', 'potential', 'ovr'):
            self.assertEqual(getattr(lite, key), before[key])
        self.assertAlmostEqual(extreme.ovr - lite.ovr, 5.0)
        self.assertEqual(extreme.potential, min(99, lite.potential + 8))
        self.assertEqual(Modes.training_multiplier(lite), 1)
        self.assertEqual(Modes.training_multiplier(extreme), 1.35)
        self.assertEqual(X.duty_level(extreme) - X.duty_level(lite), 5)
        with self.assertRaises(X.LiteError):
            self.create()

    def test_training_bonus_is_applied_to_training_and_keeps_stat_caps(self):
        lite = self.create('lite')
        extreme = self.create()
        # 생물학적 성장·잠재력·기복은 같게 둬 훈련 보정만 비교해요.
        for c in (lite, extreme):
            c.potential = 80
            c.stats = dict.fromkeys(c.stats, 40.0)
            c.flags['career_profile'] = {'development': .8, 'aging': 1, 'stall': 6}
        programs = [x[0] for x in X.PROGRAMS[lite.role]][:2]
        a = X.grow(lite, programs, 'normal', .5, 0, random.Random(1))
        b = X.grow(extreme, programs, 'normal', .5, 0, random.Random(1))
        trained = next(key for key in lite.stats if any(label == '훈련' for label, _value in a['_why'][key]))
        gain_a = sum(value for label, value in a['_why'][trained] if label == '훈련')
        gain_b = sum(value for label, value in b['_why'][trained] if label == '훈련')
        self.assertAlmostEqual(gain_b, gain_a * 1.35)
        for _ in range(50):
            X.grow(extreme, programs, 'normal', 1, 9, random.Random(1))
        self.assertTrue(all(25 <= value <= X.stat_pot(extreme, key) for key, value in extreme.stats.items()))

    def test_each_stage_has_three_events_cooldown_and_once_per_year(self):
        c = self.create()
        c.flags['extreme'].pop('pending')
        seen = set()
        for phase_index, (age, league) in enumerate(((16, 'hs'), (23, 'kbo1'), (28, 'mlb'), (35, 'kbo1'))):
            for offset in range(3):
                c.age, c.league, c.year = age + offset, league, phase_index * 4 + offset + 1
                c.pending = {'kind': 'plan'}
                event = E.offer(c, random.Random(c.year))
                self.assertIsNotNone(event)
                self.assertNotIn(event['key'], seen)
                seen.add(event['key'])
                E.apply_choice(c, event['id'], event['choices'][0]['key'], random.Random(3))
                self.assertIsNone(E.offer(c, random.Random(5)))
        self.assertEqual(seen, set(E.EVENTS))

    def test_event_resolution_ownership_replay_and_stale_year(self):
        c = self.create()
        event = E.event_view(c)
        other = User.objects.create_user('other-preview', is_staff=True)
        with self.assertRaises(LiteCareer.DoesNotExist):
            E.resolve(c.pk, other, event['id'], event['choices'][0]['key'], random.Random(1))
        E.resolve(c.pk, self.user, event['id'], event['choices'][0]['key'], random.Random(1))
        c.refresh_from_db()
        history = deepcopy(c.flags['extreme']['history'])
        with self.assertRaises(E.ExtremeError):
            E.resolve(c.pk, self.user, event['id'], event['choices'][0]['key'], random.Random(1))
        c.refresh_from_db()
        self.assertEqual(c.flags['extreme']['history'], history)
        c.year += 1
        E.offer(c, random.Random(6))
        stale = E.event_view(c)
        c.year += 1
        with self.assertRaises(E.ExtremeError):
            E.apply_choice(c, stale['id'], stale['choices'][0]['key'], random.Random(1))

    def test_persistent_rivals_do_not_follow_player_stats_and_effects_expire(self):
        c = self.create()
        initial = deepcopy(c.flags['extreme']['rivals'])
        c.flags['extreme']['season'] = {'training': .15, 'risk': .05}
        c.year += 3
        c.age += 3
        c.ovr = 99
        E.complete_year(c)
        first = deepcopy(c.flags['extreme'])
        self.assertEqual([r['name'] for r in initial], [r['name'] for r in first['rivals']])
        self.assertTrue(all(b['level'] == a['level'] + 12 for a, b in zip(initial, first['rivals'])))
        self.assertEqual(first['season'], {})
        c.ovr = 25
        E.complete_year(c)
        self.assertEqual(c.flags['extreme'], first)

    def test_both_contest_outcomes_and_actual_clamped_effects(self):
        original = self.create()
        state = deepcopy(original.flags)
        pending = state['extreme']['pending']
        pending['key'] = 'school_starter'
        for seed, expected in ((1, True), (2, False)):
            c = deepcopy(original)
            c.flags = deepcopy(state)
            c.ovr = next(r['level'] for r in c.flags['extreme']['rivals'] if r['id'] == 'school')
            result = E.apply_choice(c, pending['id'], 'compete', random.Random(seed))
            self.assertIs(result['success'], expected)
        original.flags = deepcopy(state)
        original.flags['trust'] = 100
        result = E.apply_choice(original, pending['id'], 'compete', random.Random(1))
        self.assertEqual(result['trust'], 0)

    def test_private_prototype_not_visible_or_actionable_from_public_routes(self):
        c = self.create()
        client = Client(HTTP_USER_AGENT=PC)
        client.force_login(self.user)
        for suffix in ('', 'card/', 'card.png', 'og.png', 'story.png'):
            self.assertEqual(client.get(f'/rookie/lite/c/{c.pk}/' + suffix).status_code, 404)
        client.post('/rookie/lite/act/', {'action': 'quit', 'confirm': 'yes', 'mode': 'extreme'})
        c.refresh_from_db()
        self.assertIsNone(c.retired_at)
        self.assertEqual(client.get('/rookie/lite/').context['mode'], 'create')

    def test_hall_today_and_cards_do_not_mix_modes_even_for_same_member(self):
        lite, extreme = self.create('lite'), self.create()
        for c in (lite, extreme):
            LiteSeason.objects.create(career=c, year=1, age=25, league='kbo1', club='lg', games=144, war=8,
                                       totals={'pa': 600, 'ab': 540, 'h': 160, 'hr': 20}, awards=[])
            c.retired_at = timezone.now()
            c.save()
        self.assertEqual([row['c'].pk for row in X.hall()], [lite.pk])
        self.assertEqual([row['c'].pk for row in X.hall(mode='extreme')], [extreme.pk])
        client = Client(HTTP_USER_AGENT=PC)
        client.force_login(self.user)
        self.assertEqual([row['c'].pk for row in client.get('/rookie/lite/cards/').context['rows']], [lite.pk])
        self.assertEqual([row['c'].pk for row in client.get('/rookie/lite/today/').context['rows']], [lite.pk])

    def test_http_preview_requires_flag_staff_csrf_and_preserves_lite(self):
        lite = self.create('lite')
        client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=PC)
        self.assertEqual(client.get('/rookie/extreme/lab/').status_code, 404)
        client.force_login(self.user)
        with override_settings(ROOKIE_EXTREME_PREVIEW=False):
            self.assertEqual(client.get('/rookie/extreme/lab/').status_code, 404)
        page = client.get('/rookie/extreme/lab/')
        self.assertContains(page, '새 시제품 선수')
        self.assertIn('no-store', page['Cache-Control'])
        self.assertEqual(page['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(client.post('/rookie/extreme/lab/', {'action': 'create', 'role': 'batter'}).status_code, 403)
        csrf = client.cookies['csrftoken'].value
        client.post('/rookie/extreme/lab/', {'action': 'create', 'role': 'batter', 'seed': '41'}, HTTP_X_CSRFTOKEN=csrf)
        c = LiteCareer.objects.get(user=self.user, mode='extreme')
        event = E.event_view(c)
        data = dict(action='event', career=c.pk, event_id=event['id'], choice=event['choices'][0]['key'])
        client.post('/rookie/extreme/lab/', data, HTTP_X_CSRFTOKEN=csrf)
        c.refresh_from_db()
        self.assertEqual(len(c.flags['extreme']['history']), 1)
        client.post('/rookie/extreme/lab/', data, HTTP_X_CSRFTOKEN=csrf)
        c.refresh_from_db()
        self.assertEqual(len(c.flags['extreme']['history']), 1)
        old_token = P.token(c)
        data = dict(action='advance', career=c.pk, token=old_token)
        client.post('/rookie/extreme/lab/', data, HTTP_X_CSRFTOKEN=csrf)
        c.refresh_from_db()
        self.assertGreater(c.seasons.count(), 0)
        count = c.seasons.count()
        client.post('/rookie/extreme/lab/', data, HTTP_X_CSRFTOKEN=csrf)
        c.refresh_from_db()
        self.assertEqual(c.seasons.count(), count)
        lite.refresh_from_db()
        self.assertEqual((lite.year, lite.seasons.count(), lite.mode), (1, 0, 'lite'))

    def test_evaluation_command_requires_explicit_local_opt_in(self):
        with self.assertRaises(CommandError):
            call_command('evaluate_rookie_extreme', stdout=StringIO())


class ModeMigrationTests(TransactionTestCase):
    def test_existing_career_is_lite_and_data_is_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('community', '0051_lite_splits_press')])
        try:
            apps = executor.loader.project_state([('community', '0051_lite_splits_press')]).apps
            Career = apps.get_model('community', 'LiteCareer')
            old = Career.objects.create(name='기존선수', role='batter', position='SS', style='contact',
                                        region='서울', team='lg', year=7, stats={'contact': 61}, flags={'cash': 12345})
            executor = MigrationExecutor(connection)
            executor.migrate([('community', '0052_litecareer_mode')])
            current = LiteCareer.objects.get(pk=old.pk)
            self.assertEqual((current.mode, current.name, current.year, current.stats, current.flags),
                             ('lite', '기존선수', 7, {'contact': 61}, {'cash': 12345}))
            # 배포 중 잠깐 남아 있는 구버전 프로세스가 mode 없이 쓰더라도 저장돼요.
            from_old_process = Career.objects.create(name='이전프로세스', role='pitcher', position='SP', style='control',
                                                     region='서울', team='lg')
            self.assertEqual(LiteCareer.objects.get(pk=from_old_process.pk).mode, 'lite')
        finally:
            MigrationExecutor(connection).migrate([('community', '0052_litecareer_mode')])
