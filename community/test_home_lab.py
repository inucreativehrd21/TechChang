from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from community.views.base_views import _next_column_slot

KST = ZoneInfo('Asia/Seoul')
BRIEFS = {'hrd': 'HRD 주제', 'data': '데이터 주제', 'coding': ''}


def at(*args):
    return mock.patch('community.views.base_views.timezone.localtime',
                      return_value=datetime(*args, tzinfo=KST))


class NextColumnSlotTests(SimpleTestCase):
    def test_same_day_before_ten(self):
        with at(2026, 10, 8, 9, 30):          # 목요일 09:30
            slot = _next_column_slot(BRIEFS)
        self.assertEqual((slot['when'], slot['label'], slot['title']), ('오늘', '데이터분석', '데이터 주제'))

    def test_same_day_after_ten_moves_to_next_slot(self):
        with at(2026, 10, 8, 10, 0):          # 목요일 10:00 정각 = 이미 발행
            slot = _next_column_slot(BRIEFS)
        self.assertEqual((slot['when'], slot['label']), ('토', '프로그래밍'))

    def test_tomorrow_label(self):
        with at(2026, 10, 5, 12, 0):          # 월요일 → 화요일 HRD
            slot = _next_column_slot(BRIEFS)
        self.assertEqual((slot['when'], slot['label']), ('내일', 'HRD'))

    def test_wraps_after_saturday(self):
        with at(2026, 10, 10, 11, 0):         # 토요일 11:00 → 다음 화요일
            slot = _next_column_slot(BRIEFS)
        self.assertEqual((slot['when'], slot['label'], slot['title']), ('화', 'HRD', 'HRD 주제'))

    def test_missing_brief_is_empty_title(self):
        with at(2026, 10, 9, 8, 0):           # 금요일 → 토요일 프로그래밍(주제 미정)
            slot = _next_column_slot(BRIEFS)
        self.assertEqual((slot['when'], slot['title']), ('내일', ''))


class HomeSurvivesLabFailureTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_home_renders_without_lab_block_when_lab_fails(self):
        with mock.patch('office.services.take_column_brief', side_effect=RuntimeError('office down')):
            r = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('tc-lab', r.content.decode())

    def test_home_shows_lab_block(self):
        r = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(r.status_code, 200)
        self.assertIn('tc-lab', r.content.decode())


class HomeModePickerTests(TestCase):
    def test_both_home_templates_follow_live_public_switch_even_with_warm_cache(self):
        from common.models import GameControlState
        from django.urls import reverse
        state = GameControlState.objects.create(overrides={'ROOKIE_EXTREME_ENABLED': True})
        cache.clear()
        for mobile in (False, True):
            ua = 'Mozilla/5.0 (iPhone) Mobile' if mobile else 'Mozilla/5.0 Windows Chrome/130'
            response = self.client.get('/', HTTP_USER_AGENT=ua)
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'community/mobile/question_list.html' if mobile else 'community/question_list.html')
            self.assertContains(response, 'id="tc-mode-picker"', count=1)
            self.assertContains(response, 'data-tc-mode-open', count=1)
            self.assertContains(response, 'js/home-mode-picker.js', count=1)
            for route in ('rookie_home', 'lite_home', 'extreme_home'):
                self.assertContains(response, 'href="'+reverse('community:'+route)+'"')
            self.assertNotContains(response, 'class="tc-ball-modes"')
            self.assertNotContains(response, 'class="tc-mh-ball-modes"')
        state.overrides = {'ROOKIE_EXTREME_ENABLED': False}
        state.save()
        for ua in ('Mozilla/5.0 Windows Chrome/130', 'Mozilla/5.0 (iPhone) Mobile'):
            self.assertNotContains(self.client.get('/', HTTP_USER_AGENT=ua), 'href="'+reverse('community:extreme_home')+'"')
