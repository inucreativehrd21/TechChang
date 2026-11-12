from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from office.models import ColumnDraft, JobRequest
from office.approval import approve, valid
from office.jobs import enqueue
from office.worker import work
from office.schedule import finish_accepted
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO
from pathlib import Path
import tempfile
import json


class PilotDecisionTests(TestCase):
    def test_freeze_records_source_without_generating_or_overwriting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            call_command('lab_pilot', output=folder, freeze=True, stdout=StringIO())
            source = Path(folder, 'source.json').read_text(encoding='utf-8')
            self.assertEqual(json.loads(source)['version'], 2)
            self.assertFalse(Path(folder, 'human-review.json').exists())
            with patch('office.release.fingerprint_now', return_value='changed'):
                with self.assertRaises(CommandError):
                    call_command('lab_pilot', output=folder, freeze=True, stdout=StringIO())
            self.assertEqual(Path(folder, 'source.json').read_text(encoding='utf-8'), source)

    def test_partial_pilot_resume_preserves_blind_numbers_and_human_ratings(self):
        from office.management.commands.lab_pilot import refresh_blind_review
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            call_command('lab_pilot', output=folder, stdout=StringIO())
            manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest), 12)
            case = manifest[0]
            (root / case['id']).mkdir()
            (root / case['id'] / 'draft.md').write_text('검수할 원고', encoding='utf-8')
            refresh_blind_review(root, manifest)
            review = json.loads((root / 'human-review.json').read_text(encoding='utf-8'))
            review[0].update(approved=True, usefulness=4, major_errors=0, review_minutes=12)
            (root / 'human-review.json').write_text(json.dumps(review), encoding='utf-8')
            call_command('lab_pilot', output=folder, stdout=StringIO())
            refreshed = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            refresh_blind_review(root, refreshed)
            self.assertEqual(manifest, refreshed)
            self.assertEqual(json.loads((root / 'human-review.json').read_text(encoding='utf-8')), review)
            self.assertEqual((root / 'blind' / (case['blind_id']+'.md')).read_text(encoding='utf-8'), '검수할 원고')
            with self.assertRaises(CommandError):
                call_command('lab_pilot', output=folder, rounds=1, stdout=StringIO())
            self.assertEqual(json.loads((root / 'human-review.json').read_text(encoding='utf-8')), review)

    def test_unknown_case_does_not_create_a_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CommandError):
                call_command('lab_pilot', output=folder, case='unknown', stdout=StringIO())
            self.assertFalse(Path(folder, 'manifest.json').exists())

    def test_incomplete_human_review_cannot_recommend_profile_change(self):
        rows = [{'case_id': f'{n}-{p}', 'approved': None} for n in range(1, 4) for p in ('a', 'b')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'review.json')
            path.write_text(json.dumps(rows), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('lab_pilot_report', input=str(path), stdout=StringIO())

    def test_ratings_without_run_artifacts_cannot_qualify(self):
        rows = [{'case_id': f'{n}-{p}', 'approved': True, 'usefulness': 4,
                 'major_errors': 0, 'review_minutes': 10} for n in range(1, 4) for p in ('a', 'b')]
        with tempfile.TemporaryDirectory() as folder:
            path, output = Path(folder, 'review.json'), StringIO()
            path.write_text(json.dumps(rows), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('lab_pilot_report', input=str(path), stdout=output)

    def test_unpaired_or_nonfinite_human_review_cannot_qualify(self):
        rows = [{'case_id': f'{n}-{p}', 'approved': True, 'usefulness': 4,
                 'major_errors': 0, 'review_minutes': 10 if p == 'a' else 5}
                for n in range(1, 4) for p in ('a', 'b')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'review.json')
            for field, value in [('case_id', 'different-b'), ('major_errors', False), ('review_minutes', float('nan'))]:
                invalid = [dict(row) for row in rows]
                invalid[-1][field] = value
                path.write_text(json.dumps(invalid), encoding='utf-8')
                with self.assertRaises(CommandError):
                    call_command('lab_pilot_report', input=str(path), stdout=StringIO())


class ApprovalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reviewer', is_staff=True, is_superuser=True)
        self.draft = ColumnDraft.objects.create(topic='data', status='hold', subject='제목', content='본문',
                                                qa_report={'verdict': 'accept', 'score': 100})
        from office.test_lab_safety import certified
        certified(self.draft)

    def test_model_pass_waits_for_human_and_changed_body_invalidates_approval(self):
        publish = Mock()
        finish_accepted(self.draft, publish)
        publish.assert_not_called()
        self.assertEqual(self.draft.status, 'hold')
        approve(self.draft, self.user, '원문 대조 완료')
        self.assertTrue(valid(self.draft))
        self.draft.content += ' 변경'
        self.assertFalse(valid(self.draft))

    def test_exception_needs_reason_and_model_cannot_forge_approval(self):
        self.draft.check_report['verdict'] = 'revise'
        self.draft.save()
        with self.assertRaises(ValueError):
            approve(self.draft, self.user)
        self.draft.qa_report['human_approval'] = {'actor': self.user.pk}
        self.assertFalse(valid(self.draft))

    def test_concurrent_edit_prevents_approval_of_old_version(self):
        ColumnDraft.objects.filter(pk=self.draft.pk).update(content='다른 운영자의 수정')
        with self.assertRaises(ValueError):
            approve(self.draft, self.user, '원문 확인')


class WorkerTests(TestCase):
    def test_liveness_probe_does_not_terminate_current_process(self):
        import os
        from office.worker import alive
        self.assertTrue(alive(os.getpid()))
    def test_dead_started_job_is_interrupted_without_retry(self):
        job = enqueue(['make_newsletter'])
        job.status, job.process_id = 'started', 123
        job.save()
        with patch('office.worker.alive', return_value=False), patch('office.worker.subprocess.Popen') as popen, \
                patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
        popen.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, 'interrupted')
        self.assertIsNone(job.active_key)

    def test_timeout_marks_failure_and_does_not_repeat(self):
        job = enqueue(['make_newsletter'])
        proc = Mock(pid=123, returncode=-9)
        proc.poll.return_value = None
        with patch('office.worker.subprocess.Popen', return_value=proc), \
                patch('office.worker.time.monotonic', side_effect=[0, 2800]), \
                patch('office.worker_runtime.stop', return_value=True), \
                patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIn('45분', job.note)

    def test_failure_after_spawn_keeps_process_and_blocks_queue(self):
        job = enqueue(['make_newsletter'])
        proc = Mock(pid=123, returncode=None)
        with patch('office.worker.subprocess.Popen', return_value=proc) as popen, \
                patch('office.worker_runtime.identity', side_effect=OSError('identity unavailable')), \
                patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
            work(out=lambda _: None)
        self.assertEqual(popen.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, 'quarantined')
        self.assertEqual(job.process_id, 123)
        self.assertIsNotNone(job.active_key)

    def test_timeout_without_confirmed_stop_blocks_queue(self):
        job = enqueue(['make_newsletter'])
        proc = Mock(pid=123, returncode=None)
        proc.poll.return_value = None
        with patch('office.worker.subprocess.Popen', return_value=proc), \
                patch('office.worker.time.monotonic', side_effect=[0, 2800]), \
                patch('office.worker_runtime.stop', return_value=False), \
                patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
        job.refresh_from_db()
        self.assertEqual(job.status, 'quarantined')
        self.assertIsNotNone(job.active_key)

    def test_start_failure_retries_once(self):
        job = enqueue(['make_newsletter'])
        with patch('office.worker.subprocess.Popen', side_effect=OSError('denied')), \
                patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
            job.refresh_from_db()
            self.assertEqual(job.status, 'pending')
            job.run_after = timezone.now()
            job.save()
            work(out=lambda _: None)
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts), ('failed', 2))
    def test_duplicate_requests_share_one_active_job(self):
        self.assertEqual(enqueue(['make_newsletter']).pk, enqueue(['make_newsletter']).pk)

    def test_forbidden_command_never_starts(self):
        job = JobRequest.objects.create(kind='rerun', args=['crew_work'], run_after=timezone.now())
        with patch('office.worker.subprocess.Popen') as popen, patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
        popen.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIsNone(job.active_key)

    def test_process_finishes_and_is_not_repeated(self):
        job = enqueue(['make_newsletter'])
        proc = Mock(pid=123, returncode=0)
        proc.poll.return_value = 0
        with patch('office.worker.subprocess.Popen', return_value=proc) as popen, \
                patch('office.jobmail.limited_until', return_value=None):
            work(out=lambda _: None)
            work(out=lambda _: None)
        self.assertEqual(popen.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertIsNotNone(job.finished_at)
