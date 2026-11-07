"""로그 지적사항과 정비 작업의 단일 관리 화면 회귀 검증."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from common.models import LogFinding
from office.models import Task, WorkLog


class MaintenanceReviewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('maintenance-admin', password='x', is_staff=True)
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
