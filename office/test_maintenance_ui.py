"""로그 지적사항과 정비 작업의 단일 관리 화면 회귀 검증."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from common.management.commands.send_log_report import Command
from common.models import LogAnalysisReport, LogFinding
from office.models import Task, WorkLog


class MaintenanceReviewTests(TestCase):
    def setUp(self):
        from unittest import mock as _otp_mock   # 관리 화면은 모두 OTP 경계 — 여기서는 인증된 운영자로 본다
        _otp = _otp_mock.patch('common.views._admin_otp_session_ok', return_value=True)
        _otp.start()
        self.addCleanup(_otp.stop)
        self.admin = User.objects.create_user('maintenance-admin', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.finding = LogFinding.objects.create(
            fingerprint='maintenance-review-test', title='로그 오류 조사',
            cause='예외 발생', action='로그 확인', severity='심각',
        )

    def test_review_and_backlog_share_one_tab(self):
        response = self.client.get(reverse('office:admin'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '정비·지적사항')
        self.assertContains(response, '로그 오류 조사')
        self.assertContains(response, '승인 → 작업 등록')
        self.assertEqual(response.context['crew_pending'], 1)

    def test_scheduled_report_is_visible_even_when_its_finding_was_already_decided(self):
        finding, _ = LogFinding.record({'title': '502 Bad Gateway'})
        finding.status = LogFinding.STATUS_REJECTED
        finding.save(update_fields=['status'])
        analysis = {
            'available': True,
            'severity': '주의',
            'overview': '주간 <b>오류</b> 대조',
            'findings': [{'title': '502 /map/', 'cause': '업스트림 종료', 'action': '재시작 시각 확인'}],
        }
        cmd = Command()
        with mock.patch('common.management.commands.send_log_report.connection', vendor='mysql'), \
                mock.patch('common.management.commands.send_log_report.send_mail') as mail, \
                mock.patch.object(cmd, '_collect_db_stats'), \
                mock.patch.object(cmd, '_collect_journal', return_value={'status_5xx': 4}), \
                mock.patch.object(cmd, '_collect_security_logs'), \
                mock.patch.object(cmd, '_collect_system_stats'), \
                mock.patch.object(cmd, '_analyze_errors', return_value=analysis), \
                mock.patch.object(cmd, '_render_html', return_value='html'), \
                mock.patch.object(cmd, '_render_text', return_value='text'):
            call_command(cmd, hours=168, to='ops@example.com')
        mail.assert_called_once()
        report = LogAnalysisReport.objects.get(hours=168)
        Command._save_analysis(168, report.period_end - timedelta(minutes=1), {}, {'available': False})
        report.refresh_from_db()
        self.assertEqual(report.analysis, analysis)
        self.assertEqual(report.metrics['status_5xx'], 4)
        self.assertEqual(LogFinding.objects.filter(fingerprint=finding.fingerprint).count(), 1)
        finding.refresh_from_db()
        self.assertEqual(finding.status, LogFinding.STATUS_REJECTED)
        with mock.patch.object(Command, '_analyze_errors') as analyze:
            response = self.client.get(reverse('office:admin'))
        analyze.assert_not_called()
        self.assertContains(response, 'AI 로그 분석관')
        self.assertContains(response, '주간 &lt;b&gt;오류&lt;/b&gt; 대조')
        self.assertContains(response, '재시작 시각 확인')

    def test_approval_creates_one_task_and_returns_to_shared_tab(self):
        url = reverse('common:finding_approve', args=[self.finding.id])
        response = self.client.post(url)
        self.assertEqual(response.url, reverse('office:admin') + '#crew')
        self.finding.refresh_from_db()
        task = Task.objects.get(finding=self.finding)
        self.assertEqual(self.finding.status, LogFinding.STATUS_DISPATCHED)
        self.assertEqual(task.status, Task.ST_BACKLOG)
        self.assertEqual(task.priority, 'P1')
        self.assertEqual(WorkLog.objects.filter(action='crew').count(), 1)

        self.client.post(url)
        self.assertEqual(Task.objects.filter(finding=self.finding).count(), 1)
        self.assertEqual(WorkLog.objects.filter(action='crew').count(), 1)
        response = self.client.get(reverse('office:admin'))
        self.assertEqual(response.context['crew_pending'], 1)
        self.assertContains(response, '작업 #{}'.format(task.id))

    def test_rejected_finding_stays_out_of_backlog(self):
        response = self.client.post(reverse('common:finding_reject', args=[self.finding.id]))
        self.assertEqual(response.url, reverse('office:admin') + '#crew')
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, LogFinding.STATUS_REJECTED)
        self.assertFalse(Task.objects.filter(finding=self.finding).exists())
        response = self.client.get(reverse('office:admin'))
        self.assertEqual(response.context['crew_pending'], 0)
        self.assertContains(response, '최근 지적사항 결정')
