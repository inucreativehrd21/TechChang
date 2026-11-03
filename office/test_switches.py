"""연구실 기능 스위치 — .env → 관리 화면 설정 → 기본값 순서, 잠금, 관리 화면 저장."""
import os
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from office import switches as SW
from office.models import LabSwitch

CLEAN = {s.env: '' for s in SW.SWITCHES}     # 개발 환경의 .env 값이 섞이지 않게 비운다


@mock.patch.dict(os.environ, CLEAN)
class ResolveTests(TestCase):
    def setUp(self):
        SW.clear_cache()
        self.addCleanup(SW.clear_cache)

    def test_env_then_admin_then_default(self):
        self.assertEqual(SW.resolve('genres'), (False, 'default'))
        SW.set_value('genres', 'on')
        self.assertEqual(SW.resolve('genres'), (True, 'admin'))
        with mock.patch.dict(os.environ, {'OFFICE_GENRES': '0'}):
            self.assertEqual(SW.resolve('genres'), (False, 'env'))
            with self.assertRaises(ValueError):           # .env 로 고정된 값은 화면에서 못 바꾼다
                SW.set_value('genres', 'off')
        SW.reset('genres')
        self.assertEqual(SW.resolve('genres'), (False, 'default'))

    def test_values_are_validated(self):
        with self.assertRaises(ValueError):
            SW.set_value('max_workers', '99')
        with self.assertRaises(ValueError):
            SW.set_value('profile', 'c')
        self.assertEqual(SW.set_value('run_max_codex_tokens', '300,000'), 300000)
        with mock.patch.dict(os.environ, {'OFFICE_MAX_WORKERS': 'many'}):   # 해석 못 하는 .env 는 무시
            self.assertEqual(SW.resolve('max_workers'), (3, 'default'))

    def test_code_run_is_env_only(self):
        with self.assertRaises(ValueError):
            SW.set_value('code_run', 'on')
        LabSwitch.objects.create(key='code_run', value='on')              # DB 에 있어도 쓰지 않는다
        SW.clear_cache()
        self.assertFalse(SW.get('code_run'))
        with mock.patch.dict(os.environ, {'OFFICE_CODE_RUN': '1'}):
            self.assertTrue(SW.get('code_run'))

    def test_consumers_follow_the_admin_value(self):
        from office import concurrency, genres, grounded
        from office.model_router import profile
        SW.set_value('genres', 'on')
        SW.set_value('profile', 'b')
        SW.set_value('grounded_web_max', '2')
        SW.set_value('parallel', 'off')
        self.assertEqual(genres.genre_for('coding'), 'tutorial')
        self.assertEqual(profile(), 'b')
        self.assertEqual(grounded.web_max(), 2)
        self.assertFalse(concurrency.parallel_enabled())

    def test_panel_marks_switches_that_are_not_in_use(self):
        items = {i['spec'].key: i for g in SW.panel() for i in g['items']}
        self.assertIn('B일 때만', items['grounded_check']['idle'])
        self.assertIn('장르별 구성', items['run_first']['idle'])
        self.assertTrue(items['code_run']['locked'])
        SW.set_value('profile', 'b')
        items = {i['spec'].key: i for g in SW.panel() for i in g['items']}
        self.assertEqual(items['grounded_check']['idle'], '')
        self.assertEqual((items['profile']['source'], items['profile']['row'].value), ('admin', 'b'))


@mock.patch.dict(os.environ, CLEAN)
class AdminSwitchViewTests(TestCase):
    def setUp(self):
        SW.clear_cache()
        self.addCleanup(SW.clear_cache)
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pw')
        self.client.force_login(self.admin)

    def test_settings_tab_lists_switches(self):
        r = self.client.get(reverse('office:admin'))
        self.assertContains(r, '장르별 구성(코딩=튜토리얼)')
        self.assertContains(r, 'data-tab="settings"')

    def test_change_and_reset(self):
        url = reverse('office:switch_set', args=['genres'])
        r = self.client.post(url, {'value': 'on'})
        self.assertRedirects(r, reverse('office:admin') + '#settings', fetch_redirect_response=False)
        self.assertEqual(LabSwitch.objects.get(key='genres').updated_by, self.admin)
        self.assertTrue(SW.get('genres'))
        self.client.post(url, {'reset': '1'})
        self.assertFalse(LabSwitch.objects.filter(key='genres').exists())

    def test_locked_and_unknown_switches_are_refused(self):
        self.client.post(reverse('office:switch_set', args=['code_run']), {'value': 'on'})
        self.assertFalse(LabSwitch.objects.filter(key='code_run').exists())
        self.assertEqual(self.client.post(reverse('office:switch_set', args=['nope']), {'value': 'on'}).status_code, 404)

    def test_staff_only(self):
        self.client.logout()
        self.client.force_login(User.objects.create_user('kim', 'kim@example.com', 'pw'))
        self.client.post(reverse('office:switch_set', args=['genres']), {'value': 'on'})
        self.assertFalse(LabSwitch.objects.exists())
