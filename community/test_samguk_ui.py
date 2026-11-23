"""연속 플레이 응답이 서버 판정·기본 폼·CSRF 계약을 유지하는지 검증해요."""
import re
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from community import samguk as S
from community.models import SamgukCodex, SamgukMember, SamgukRun
from community.test_samguk import verified


@override_settings(SAMGUK_ENABLED=True, GAME_CONTROLS_USE_DB=False, SAMGUK_BALANCE_STARTS=False)
class SamgukContinuousUITests(TestCase):
    headers = {'HTTP_X_SAMGUK_PARTIAL': '1'}

    def setUp(self):
        cache.clear()
        self.user = verified('continuous')
        self.client.force_login(self.user)
        S.set_faction(self.user, 'wei')
        S.set_tutorial(self.user, 'skipped')
        self.run = S.start(self.user, 0)
        self.city = self.run.state['start']

    def test_partial_get_has_server_html_and_cache_variant(self):
        response = self.client.get(reverse('community:samguk_home'), **self.headers)
        body = response.json()
        self.assertEqual(body['version'], 1)
        self.assertEqual(body['screen'], 'home')
        self.assertIn('data-sg-board', body['html'])
        self.assertIn('name="csrfmiddlewaretoken"', body['html'])
        self.assertNotIn('<html', body['html'])
        self.assertIn('X-Samguk-Partial', response['Vary'])
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(self.run.actions.count(), 0)

    def test_repeated_actions_use_fresh_seq_without_reloading_page(self):
        for seq in range(2):
            response = self.client.post(reverse('community:samguk_act'),
                {'kind': 'develop', 'city': self.city, 'seq': seq}, follow=True, **self.headers)
            body = response.json()
            self.assertIn(f'name="seq" value="{seq + 1}"', body['html'])
            self.assertTrue(any(m['level'] == 'success' for m in body['messages']))
        self.run.refresh_from_db()
        self.assertEqual(self.run.ap_spent, 2)
        self.assertEqual(self.run.actions.count(), 2)
        self.assertEqual(self.client.get(reverse('community:samguk_home'), **self.headers).json()['messages'], [])

    def test_stale_seq_does_not_apply_action_twice(self):
        data = {'kind': 'develop', 'city': self.city, 'seq': 0}
        self.client.post(reverse('community:samguk_act'), data, follow=True, **self.headers)
        response = self.client.post(reverse('community:samguk_act'), data, follow=True, **self.headers)
        self.assertTrue(any(m['level'] == 'error' for m in response.json()['messages']))
        self.run.refresh_from_db()
        self.assertEqual(self.run.actions.count(), 1)
        self.assertEqual(self.run.ap_spent, 1)

    def test_rule_error_returns_fresh_panel_without_spending_ap(self):
        response = self.client.post(reverse('community:samguk_act'),
            {'kind': 'develop', 'city': 'nowhere', 'seq': 0}, follow=True, **self.headers)
        self.assertTrue(any(m['level'] == 'error' for m in response.json()['messages']))
        self.run.refresh_from_db()
        self.assertEqual(self.run.ap_spent, 0)
        self.assertIn('name="seq" value="0"', response.json()['html'])

    def test_normal_post_still_redirects_to_full_page(self):
        response = self.client.post(reverse('community:samguk_act'),
            {'kind': 'develop', 'city': self.city, 'seq': 0})
        self.assertRedirects(response, reverse('community:samguk_home') + '#sg-board')
        full = self.client.get(reverse('community:samguk_home'))
        self.assertTemplateUsed(full, 'base.html')
        self.assertIn('X-Samguk-Partial', full['Vary'])

    def test_partial_header_does_not_bypass_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        view = strict.get(reverse('community:samguk_home'), **self.headers).json()
        data = {'kind': 'develop', 'city': self.city, 'seq': 0}
        self.assertEqual(strict.post(reverse('community:samguk_act'), data, **self.headers).status_code, 403)
        data['csrfmiddlewaretoken'] = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', view['html'])[1]
        self.assertEqual(strict.post(reverse('community:samguk_act'), data, follow=True, **self.headers).json()['screen'], 'home')
        self.assertEqual(SamgukRun.objects.get(pk=self.run.pk).actions.count(), 1)

    def test_tutorial_partial_does_not_create_daily_records(self):
        before = SamgukRun.objects.count()
        response = self.client.post(reverse('community:samguk_tutorial_act'),
            {'kind': 'develop', 'city': 'xuchang', 'seq': 0}, follow=True, **self.headers)
        self.assertEqual(response.json()['screen'], 'tutorial')
        self.assertIn('name="seq" value="1"', response.json()['html'])
        self.assertIn(response.json()['messages'][0]['text'], response.json()['html'])
        self.assertEqual(SamgukRun.objects.count(), before)

    def test_inn_pick_updates_server_card_and_codex(self):
        from community import samguk_manor as M
        inn = M.inn_today(self.user)
        response = self.client.post(reverse('community:samguk_inn_pick'),
            {'code': inn.offers[0]}, follow=True, **self.headers)
        self.assertEqual(response.json()['screen'], 'inn')
        self.assertIn('is-picked', response.json()['html'])
        self.assertTrue(SamgukCodex.objects.filter(user=self.user, general=inn.offers[0], first_recruited__isnull=False).exists())

    def test_mobile_manor_partial_keeps_pc_only_gate(self):
        self.client.cookies['force_version'] = 'mobile'
        response = self.client.get(reverse('community:samguk_manor'), **self.headers)
        self.assertEqual(response.json()['screen'], 'pc_only')
        self.assertIn('PC에서 이용해 주세요', response.json()['html'])

    def test_old_day_action_returns_new_start_without_spending(self):
        tomorrow = self.run.day.date + timedelta(days=1)
        with mock.patch.object(S, 'game_day', return_value=tomorrow):
            response = self.client.post(reverse('community:samguk_act'),
                {'kind': 'develop', 'city': self.city, 'seq': 0}, follow=True, **self.headers)
        self.assertIn('시작 도시를 골라 주세요', response.json()['html'])
        self.assertIn(tomorrow.isoformat(), response.json()['html'])
        self.assertFalse(SamgukRun.objects.filter(user=self.user, day__date=tomorrow).exists())

    def test_manor_setting_partial_uses_authoritative_checkbox(self):
        response = self.client.post(reverse('community:samguk_manor_post'),
            {'what': 'privacy', 'hide': '1'}, follow=True, **self.headers)
        self.assertEqual(response.json()['screen'], 'manor')
        self.assertTrue(SamgukMember.objects.get(user=self.user).hide_from_beggar)
        self.assertIn('name="hide" value="1" checked', response.json()['html'])
        self.client.cookies['force_version'] = 'mobile'
        mobile = self.client.post(reverse('community:samguk_manor_post'),
            {'what': 'privacy'}, follow=True, **self.headers)
        self.assertEqual(mobile.json()['screen'], 'pc_only')
        self.assertTrue(SamgukMember.objects.get(user=self.user).hide_from_beggar)

    def test_beggar_reply_is_inline_and_rumor_moves_to_quests(self):
        from community.models import SamgukRumor
        SamgukMember.objects.filter(user=self.user).update(fame=30)
        manor = reverse('community:samguk_manor')
        response = self.client.post(reverse('community:samguk_manor_post'),
            {'what': 'beggar', 'alms': '1'}, follow=True, **self.headers).json()
        rumor = SamgukRumor.objects.get(user=self.user)
        self.assertIn('data-sg-beggar-reply', response['html'])
        self.assertIn(rumor.text, response['html'])
        self.assertIn('form="sg-beggar-talk"', response['html'])
        self.assertEqual(response['messages'], [])
        self.assertNotContains(self.client.get(manor), rumor.text)
        self.client.cookies['force_version'] = 'mobile'
        game = self.client.get(reverse('community:samguk_home'))
        self.assertTemplateUsed(game, 'base_mobile.html')
        self.assertContains(game, '전설 퀘스트')
        self.assertContains(game, rumor.text)
