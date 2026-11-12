"""운영 DB의 실제 행 잠금으로 검사한다. SQLite 결과를 대신 사용하지 않는다."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from office.models import AuditHead, AuditEvent
from office.audit import append, verify


@skipUnlessDBFeature('has_select_for_update')
class AuditConcurrencyTests(TransactionTestCase):
    def test_two_connections_append_distinct_ordered_events(self):
        AuditHead.objects.create(pk=1)
        barrier = Barrier(2)
        def writer(number):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return append('concurrent_test', payload={'number': number}).sequence
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            seq = list(executor.map(writer, [1, 2]))
        self.assertEqual(sorted(seq), [1, 2])
        self.assertEqual(AuditEvent.objects.count(), 2)
        self.assertTrue(verify())

    def test_concurrent_publication_creates_one_question_and_one_event(self):
        from unittest.mock import patch
        from django.contrib.auth.models import User
        from community.models import Category, Question
        from office.models import ColumnDraft
        from office.test_lab_safety import certified
        from office.approval import approve
        from office.pipeline import publish_draft
        from common.management.commands.auto_write_columns import TOPICS
        Category.objects.get_or_create(name=TOPICS['data']['category_name'])
        owner = User.objects.create_superuser('owner', '', 'x')
        draft = certified(ColumnDraft.objects.create(topic='data', status='hold', subject='동시 발행', content='검증한 본문',
            qa_report={'verdict': 'accept', 'score': 90}))
        approve(draft, owner)
        barrier = Barrier(2)
        def writer(_):
            close_old_connections()
            try:
                current = ColumnDraft.objects.get(pk=draft.pk)
                barrier.wait(timeout=10)
                return publish_draft(current).pk
            finally:
                close_old_connections()
        with patch('office.live.mark'), ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(writer, [1, 2]))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='published').count(), 1)

    def test_cancel_committed_in_another_connection_blocks_late_meeting_write(self):
        import os
        import uuid
        from unittest.mock import patch
        from datetime import timedelta
        from django.utils import timezone
        from office.models import JobRequest, Meeting
        from office.job_control import cancel
        from office.execution import LeaseLost
        job = JobRequest.objects.create(kind='rerun', args=['hold_meeting'], status='started', run_after=timezone.now(),
             execution_id=uuid.uuid4(), lease_until=timezone.now()+timedelta(minutes=2))
        def cancel_elsewhere():
            close_old_connections()
            try:
                with patch('office.job_supervision.stop', return_value=True):
                    cancel(job.pk)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(cancel_elsewhere).result(timeout=15)
        with patch.dict(os.environ, {'LAB_JOB_ID': str(job.pk), 'LAB_EXECUTION_ID': str(job.execution_id)}):
            with self.assertRaises(LeaseLost):
                Meeting.objects.create(week_start=timezone.localdate())
