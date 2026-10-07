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
