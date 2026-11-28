"""운영자 직접 수정 발행(office.manual_edit) — 재작성 두 번 뒤에도 심사 미통과일 때만 열리고, 고친 판 그대로 공개된다."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from community.models import Category, Question
from office import approval, manual_edit
from office.audit import snapshot, fingerprint
from office.models import AuditEvent, ColumnDraft, WorkLog
from office.test_lab_safety import certified

UA = 'Mozilla/5.0'   # 보안 미들웨어가 빈 User-Agent 반복 요청을 막는다


class ManualEditTests(TestCase):
    def setUp(self):
        Category.objects.get_or_create(name='데이터분석')
        self.owner = User.objects.create_superuser('admin', '', 'x')
        # 필수 수정 0건인데 78점이라 일반·예외 승인이 모두 막힌 원고(#74 상황)
        self.draft = certified(ColumnDraft.objects.create(
            topic='data', status='hold', subject='원래 제목', content='원래 본문\n',
            qa_report={'verdict': 'minor', 'score': 78, 'must_fix': [], 'fatal': []}))

    def asked(self, n):
        for i in range(n):
            WorkLog.objects.create(agent='lead', action='admin_note', text=f'운영자 수정 지시 접수: {i}', draft=self.draft)

    def version(self):
        self.draft.refresh_from_db()
        return fingerprint(snapshot(self.draft))

    def test_opens_only_after_two_requests_and_failed_review(self):
        self.assertIn('지금 0번', manual_edit.blocker(self.draft))
        self.asked(1)
        self.assertIn('지금 1번', manual_edit.blocker(self.draft))
        self.asked(1)
        self.assertEqual(manual_edit.blocker(self.draft), '')
        passed = certified(ColumnDraft.objects.create(topic='data', status='hold', subject='통과', content='본문\n',
                                                      qa_report={'verdict': 'accept', 'score': 90}))
        for _ in range(2):
            WorkLog.objects.create(agent='lead', action='admin_note', text='지시', draft=passed)
        self.assertIn('검수 승인', manual_edit.blocker(passed))

    def test_publishes_edited_version_with_audit_trail(self):
        self.asked(2)
        draft = manual_edit.publish(self.draft.pk, self.owner, subject='고친 제목', content='고친 본문\r\n',
                                    reason='E1 직접 반영', expected_snapshot=self.version())
        self.assertEqual(draft.status, ColumnDraft.STATUS_PUBLISHED)
        q = Question.objects.get(pk=draft.question_id)
        self.assertEqual((q.subject, q.content), ('고친 제목', '고친 본문\n'))
        actions = list(AuditEvent.objects.filter(draft_id=draft.pk).values_list('action', flat=True).order_by('sequence'))
        self.assertEqual(actions, ['manual_edited', 'manual_approved', 'release_queued', 'published'])
        self.assertEqual(AuditEvent.objects.get(action='manual_edited').payload['before']['content'], '원래 본문\n')
        self.assertTrue(approval.valid(draft))

    def test_refuses_stale_screen_and_ineligible_draft_without_changes(self):
        self.asked(2)
        with self.assertRaisesMessage(ValueError, '새로고침'):
            manual_edit.publish(self.draft.pk, self.owner, subject='고친 제목', content='고친 본문',
                                reason='', expected_snapshot='old')
        WorkLog.objects.filter(draft=self.draft).delete()
        with self.assertRaisesMessage(ValueError, '재작성 요청을 2번'):
            manual_edit.publish(self.draft.pk, self.owner, subject='고친 제목', content='고친 본문',
                                reason='', expected_snapshot=self.version())
        self.draft.refresh_from_db()
        self.assertEqual((self.draft.subject, self.draft.status), ('원래 제목', 'hold'))
        self.assertFalse(AuditEvent.objects.filter(draft_id=self.draft.pk).exists())

    def test_manual_mode_needs_the_operator_edit_marker(self):
        with self.assertRaisesMessage(ValueError, '직접 수정한 판이 아니에요'):
            approval.approve(self.draft, self.owner, mode='manual')

    def test_views_require_otp_and_regular_form_rejects_manual_mode(self):
        self.asked(2)
        self.client.force_login(self.owner)
        url = reverse('office:draft_manual_publish', args=[self.draft.pk])
        data = {'subject': '고친 제목', 'content': '고친 본문', 'version': self.version()}
        with mock.patch('common.views._admin_otp_session_ok', return_value=True):   # 관리 화면 진입 경계
            with mock.patch('office.views._admin_otp_session_ok', return_value=False):
                self.assertRedirects(self.client.post(url, data, HTTP_USER_AGENT=UA), reverse('common:admin_otp'), fetch_redirect_response=False)
                self.client.post(reverse('office:draft_publish', args=[self.draft.pk]),
                                 {'mode': 'manual', 'version': data['version']}, HTTP_USER_AGENT=UA)
                self.assertContains(self.client.get(reverse('office:admin'), HTTP_USER_AGENT=UA), '재인증하고 수정하기')
            self.draft.refresh_from_db()
            self.assertEqual(self.draft.status, 'hold')
            # 재인증으로 넘어가도 고쳐 쓴 판은 세션에 남아 편집 칸을 다시 채운다
            self.assertEqual(self.client.session[f'manual_edit_{self.draft.pk}']['content'], '고친 본문')
            with mock.patch('office.views._admin_otp_session_ok', return_value=True):
                page = self.client.get(reverse('office:admin'), HTTP_USER_AGENT=UA)
                self.assertContains(page, '지난번에 고쳐 쓴 내용')
                self.assertContains(page, reverse('office:draft_manual_publish', args=[self.draft.pk]))
                self.client.post(url, data, HTTP_USER_AGENT=UA)
        self.draft.refresh_from_db()
        self.assertEqual((self.draft.status, self.draft.subject), ('published', '고친 제목'))
        self.assertNotIn(f'manual_edit_{self.draft.pk}', self.client.session)
