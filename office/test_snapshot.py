from unittest import mock

from django.test import SimpleTestCase

from office import services


def snap(**over):
    base = {
        'today': '2026-10-04',
        'visitors': {'recent': 100, 'previous': 90, 'days': 28},
        'gsc': {'available': True, 'clicks': 10, 'impressions': 289, 'ctr': 0.035, 'position': 14.0,
                'top_queries': [{'k': 'advanced analytics란', 'clicks': 0, 'impr': 57, 'ctr': 0.0},
                                {'k': 'hrd 아카이브', 'clicks': 3, 'impr': 40, 'ctr': 0.075}]},
        'server_log': {'available': True, 'hours': 168, 'status_5xx': 4, 'error_lines': 2, 'security_blocks': 27},
        'recent_columns': [
            {'subject': 'A', 'category': 'HRD', 'date': '2026-10-01', 'views': 40, 'votes': 0},
            {'subject': 'B', 'category': 'HRD', 'date': '2026-09-29', 'views': 60, 'votes': 1},
        ],
        'top_viewed': [], 'series': [], 'pending_findings': [], 'held_drafts': 0, 'last_meeting': [],
    }
    base.update(over)
    return base


class SnapshotTextTests(SimpleTestCase):
    def test_queries_include_impressions_and_ctr(self):
        text = services.snapshot_as_text(snap())
        self.assertIn('advanced analytics란: 클릭 0 / 노출 57 / CTR 0.0%', text)
        self.assertIn('hrd 아카이브: 클릭 3 / 노출 40 / CTR 7.5%', text)

    def test_column_reaction_tracking_line(self):
        text = services.snapshot_as_text(snap())
        self.assertIn('추천 1개 이상 1편', text)
        self.assertIn('추천 합 1 / 조회 합 100', text)
        self.assertIn('100조회당 추천 1.00', text)

    def test_server_log_separates_blocks_from_failures(self):
        text = services.snapshot_as_text(snap())
        self.assertIn('5xx 응답 4건', text)
        self.assertIn('실제 에러 라인 2건', text)
        self.assertIn('IP 자동 차단 27건', text)

    def test_missing_optional_sections_do_not_break(self):
        text = services.snapshot_as_text(snap(server_log={'available': False}, recent_columns=[],
                                              gsc={'available': False}))
        self.assertNotIn('서버 로그', text)
        self.assertNotIn('칼럼 반응 추적', text)

    def test_server_log_collector_failure_is_contained(self):
        with mock.patch('common.management.commands.send_log_report.Command._collect_journal',
                        side_effect=RuntimeError('journal down')):
            self.assertEqual(services._collect_server_log(168)['available'], False)
