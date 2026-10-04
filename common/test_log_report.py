from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from common.management.commands.send_log_report import Command

# 운영 journalctl 에서 실제로 나온 형태의 줄들
OLD_BLOCK = 'Oct 04 10:00:01 host gunicorn[1]: ERROR 2026-10-04 10:00:01,1 middleware IP 1.2.3.4 blocked for 3600 seconds. Reason: Suspicious'
NEW_BLOCK = 'Oct 04 10:00:02 host gunicorn[1]: WARNING 2026-10-04 10:00:02,1 middleware IP 5.6.7.8 blocked for 3600 seconds. Reason: Rate limit'
SCANNER_404 = 'Sep 29 06:16:22 host gunicorn[1]: WARNING 2026-09-29 06:16:22,496 log Not Found: /manager.php/error.php'
SCANNER_403 = 'Oct 04 01:56:01 host gunicorn[1]: WARNING 2026-10-04 01:56:01,232 log Forbidden: /wp-includes/error-protection-sample.php'
DJANGO_500 = 'Oct 04 10:00:03 host gunicorn[1]: ERROR 2026-10-04 10:00:03,1 log Internal Server Error: /broken/'
GUNICORN_ERR = 'Oct 04 10:00:04 host gunicorn[1]: [2026-10-04 10:00:04 +0900] [1] [ERROR] Worker (pid:2) was sent SIGKILL'
EXC_LINE = 'Oct 04 10:00:05 host gunicorn[1]: django.db.utils.OperationalError: database is locked'
INFO_LINE = 'Oct 04 10:00:06 host gunicorn[1]: INFO 2026-10-04 10:00:06,1 log GET /error-guide/ 200'


def fake_journal(*lines):
    return mock.patch(
        'common.management.commands.send_log_report.subprocess.run',
        return_value=SimpleNamespace(returncode=0, stdout='\n'.join(lines)),
    )


class LogClassificationTests(SimpleTestCase):
    def test_ip_blocks_are_counted_separately_from_errors(self):
        with fake_journal(OLD_BLOCK, NEW_BLOCK, DJANGO_500):
            stats = Command()._collect_journal(hours=24)
        self.assertEqual(stats['security_blocks'], 2)
        self.assertEqual(stats['error_count'], 1)
        self.assertTrue(all('blocked for' not in e for e in stats['top_errors']))

    def test_paths_containing_error_are_not_errors(self):
        with fake_journal(SCANNER_404, SCANNER_403, INFO_LINE):
            stats = Command()._collect_journal(hours=24)
        self.assertEqual(stats['error_count'], 0)
        self.assertEqual(stats['warning_count'], 2)

    def test_real_errors_are_still_detected(self):
        with fake_journal(DJANGO_500, GUNICORN_ERR, EXC_LINE):
            stats = Command()._collect_journal(hours=24)
        self.assertEqual(stats['error_count'], 3)

    def test_blocks_and_scanners_alone_do_not_trigger_ai_error_analysis(self):
        with fake_journal(OLD_BLOCK, NEW_BLOCK, SCANNER_404):
            stats = Command()._collect_journal(hours=24)
        self.assertEqual(stats['error_count'], 0)
        with mock.patch('common.services.claude.ask_json') as ask:
            result = Command()._analyze_errors(24, stats)
        self.assertTrue(result.get('skipped'))
        ask.assert_not_called()

    def test_live_tail_colors_follow_the_same_rules(self):
        level = Command._classify_level
        self.assertEqual(level(OLD_BLOCK), 'warn')
        self.assertEqual(level(SCANNER_404), 'warn')
        self.assertEqual(level(INFO_LINE), 'info')
        self.assertEqual(level(DJANGO_500), 'error')
        self.assertEqual(level(GUNICORN_ERR), 'error')
