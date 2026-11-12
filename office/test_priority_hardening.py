import json
import os
import tempfile
import uuid
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from .models import ColumnDraft, StageRun, JobRequest, Meeting, Decision
from .test_lab_safety import certified
from . import approval
from .execution import LeaseLost
from .recorder import StageRecorder, StagePersistenceError, digest


class EvidenceCompletenessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('owner', '', 'x')
        self.draft = certified(ColumnDraft.objects.create(topic='data', status='hold', subject='검수', content='본문',
                                                         qa_report={'verdict': 'accept', 'score': 90}))

    def test_failed_stage_store_aborts_and_cannot_leave_an_approvable_run(self):
        StageRun.objects.filter(draft=self.draft).delete()
        with patch.object(StageRun.objects, 'create', side_effect=OSError('store unavailable')), \
             patch('office.recorder.logger.exception'):
            with self.assertRaises(StagePersistenceError):
                StageRecorder(draft=self.draft).record('check', output=self.draft.check_report)
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner)

    def test_missing_required_stage_or_final_invalidates_approval(self):
        approval.approve(self.draft, self.owner)
        StageRun.objects.filter(draft=self.draft, stage='check').delete()
        self.assertFalse(approval.valid(self.draft))
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner)

    def test_changed_final_binding_cannot_be_approved(self):
        StageRun.objects.filter(draft=self.draft, stage='final').update(output={'subject': self.draft.subject})
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner)


class AssetIntegrityTests(TestCase):
    def test_asset_change_invalidates_approval_and_original_restores_from_archive(self):
        from .artifacts import atomic_write
        owner = User.objects.create_superuser('owner', '', 'x')
        with tempfile.TemporaryDirectory() as folder, override_settings(BASE_DIR=folder, MEDIA_ROOT=Path(folder, 'media')):
            image = Path(folder, 'media/columns/test.png')
            atomic_write(image, b'approved bytes')
            draft = certified(ColumnDraft.objects.create(topic='data', status='hold', subject='도판',
                content='본문\n\n![도판](/media/columns/test.png)', chart_path='columns/test.png',
                qa_report={'verdict': 'accept', 'score': 90}))
            approval.approve(draft, owner)
            self.assertTrue(approval.valid(draft))
            stored = Path(folder, 'logs/private-lab/artifacts', digest('approved bytes'))
            self.assertEqual(stored.read_bytes(), b'approved bytes')
            image.write_bytes(b'changed bytes')
            self.assertFalse(approval.valid(draft))
            call_command('lab_audit', export=True, restore_check=True, stdout=StringIO())
            export = json.loads(next(Path(folder, 'logs/private-lab').glob('audit-*.json')).read_text(encoding='utf-8'))
            self.assertIn(digest('approved bytes'), export['assets'])
            image.unlink()
            self.assertFalse(approval.valid(draft))
            image.write_bytes(b'approved bytes')
            self.assertTrue(approval.valid(draft))
            stored.unlink()
            self.assertFalse(approval.valid(draft))

    def test_chart_storage_is_immutable_by_content(self):
        from .artifacts import store_chart
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            first, second = store_chart(b'first'), store_chart(b'second')
            self.assertNotEqual(first, second)
            self.assertEqual(Path(folder, first).read_bytes(), b'first')
            self.assertEqual(store_chart(b'first'), first)


class ExecutionBoundaryTests(TestCase):
    def test_failed_agenda_write_rolls_back_entire_meeting(self):
        from .management.commands.hold_meeting import Command
        with patch.object(Decision.objects, 'create', side_effect=RuntimeError('agenda store failed')):
            with self.assertRaises(RuntimeError):
                Command(stdout=StringIO())._save(timezone.localdate(), '', [], {}, 'meeting',
                    [{'kind': 'ops', 'question': 'agenda', 'options': [{'title': 'option'}]}])
        self.assertFalse(Meeting.objects.exists())

    def test_expired_execution_cannot_write_meeting_queryset_or_publish_files(self):
        from .management.commands.hold_meeting import Command
        from .artifacts import atomic_write
        meeting = Meeting.objects.create(week_start=timezone.localdate(), summary='original')
        job = JobRequest.objects.create(kind='rerun', args=['hold_meeting'], status='started',
            run_after=timezone.now(), execution_id=uuid.uuid4(), lease_until=timezone.now()-timedelta(seconds=1))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, 'artifact')
            with patch.dict(os.environ, {'LAB_JOB_ID': str(job.pk), 'LAB_EXECUTION_ID': str(job.execution_id)}):
                for operation in (
                    lambda: Command(stdout=StringIO())._save(timezone.localdate(), '', [], {}, 'expired', []),
                    lambda: Meeting.objects.filter(pk=meeting.pk).update(summary='late'),
                    lambda: Decision.objects.bulk_create([Decision(meeting=meeting, kind='ops', question='late')]),
                    lambda: atomic_write(target, b'late'),
                ):
                    with self.assertRaises(LeaseLost):
                        operation()
            self.assertFalse(target.exists())
        meeting.refresh_from_db()
        self.assertEqual(meeting.summary, 'original')
        self.assertEqual(Meeting.objects.count(), 1)

    @override_settings(LAB_JOB_SUPERVISOR='process')
    def test_watchdog_recovers_native_orphan_after_launcher_exits(self):
        import subprocess
        import sys
        from .job_supervision import identity, active, stop, recover
        code = ("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);print(p.pid,flush=True)")
        parent = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(parent.returncode, 0)
        pid = int(parent.stdout.strip())
        job = JobRequest.objects.create(kind='rerun', args=['hold_meeting'], status='started', run_after=timezone.now(),
             started_at=timezone.now()-timedelta(minutes=5), execution_id=uuid.uuid4(), process_id=pid,
             process_identity=identity(pid), lease_until=timezone.now()-timedelta(seconds=1), active_key='orphan')
        try:
            self.assertTrue(active(job))
            recover(out=lambda _: None)
            job.refresh_from_db()
            self.assertEqual(job.status, 'interrupted')
            self.assertIsNone(job.active_key)
            self.assertFalse(active(job))
        finally:
            stop(job)


def pilot_fixture(root, *, b_minutes=5):
    from .audit import fingerprint
    from .release import code_fingerprint
    from .management.commands.lab_pilot import write_private, refresh_blind_review
    from .pilot_bundle import case_record
    from .model_router import use_profile
    from .pipeline import verification_hash
    call_command('lab_pilot', output=str(root), rounds=1, stdout=StringIO())
    cases = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    source = {'version': 2, 'code_fingerprint': code_fingerprint(), 'manifest_digest': fingerprint(cases)}
    write_private(root / 'source.json', json.dumps(source))
    for case in cases:
        with use_profile(case['profile']):
            recorder = StageRecorder(dry=True)
        content, title = '평가 원고 본문', '평가 제목'
        check = {'verdict': 'pass', 'subject': title, 'verification_hash': verification_hash(content)}
        review = {'verdict': 'accept', 'score': 90, 'verified_subject': title, 'reviewed_full_hash': digest(content)}
        recorder.record('check', output=check, calls=[{'input_tokens': 10, 'output_tokens': 2, 'seconds': 1}])
        recorder.record('review', output=review)
        recorder.complete(title, content, check, review)
        rows = [{**row, 'run_id': str(recorder.run_id)} for row in recorder.stages]
        body = '# '+title+'\n\n'+content
        folder = root / case['id']
        write_private(folder / 'stages.json', json.dumps(rows, ensure_ascii=False))
        write_private(folder / 'draft.md', body)
        write_private(folder / 'case.json', json.dumps(case_record(case, rows, body, source)))
    refresh_blind_review(root, cases)
    path = root / 'human-review.json'
    reviews = json.loads(path.read_text(encoding='utf-8'))
    for row in reviews:
        row.update(approved=True, usefulness=4, major_errors=0,
                   review_minutes=10 if row['case_id'].endswith('-a') else b_minutes)
    write_private(path, json.dumps(reviews))
    return path, cases


class PilotEvidenceTests(TestCase):
    def test_blind_rating_sheet_hides_profiles_and_can_be_evaluated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private, cases = pilot_fixture(root)
            rows = json.loads(private.read_text(encoding='utf-8'))
            blinded = [{key: value for key, value in row.items() if key != 'case_id'} for row in rows]
            path = root / 'blind/review.json'
            path.write_text(json.dumps(blinded), encoding='utf-8')
            self.assertNotIn('case_id', path.read_text(encoding='utf-8'))
            out = StringIO()
            call_command('lab_pilot_report', input=str(path), stdout=out)
            self.assertTrue(json.loads(out.getvalue())['eligible_for_review'])

    def test_failed_attempt_is_kept_and_prevents_b_qualification(self):
        from .audit import fingerprint
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, cases = pilot_fixture(root)
            case = next(case for case in cases if case['profile'] == 'b')
            record_path = root / case['id'] / 'case.json'
            record = json.loads(record_path.read_text(encoding='utf-8'))
            record.update(outcome='failed', draft_digest=digest(''), stages_digest=fingerprint([]))
            text = json.dumps(record)
            record_path.write_text(text, encoding='utf-8')
            (root / case['id'] / 'stages.json').write_text('[]', encoding='utf-8')
            (root / case['id'] / 'draft.md').write_text('', encoding='utf-8')
            (root / 'blind' / (case['blind_id']+'.md')).write_text('', encoding='utf-8')
            rows = json.loads(path.read_text(encoding='utf-8'))
            for row in rows:
                if row['case_id'] == case['id']:
                    row.update(approved=False, artifact_hash=digest(text))
            path.write_text(json.dumps(rows), encoding='utf-8')
            out = StringIO()
            call_command('lab_pilot_report', input=str(path), stdout=out)
            result = json.loads(out.getvalue())
            self.assertFalse(result['eligible_for_review'])
            self.assertEqual(result['usage']['b']['attempts'], 3)
            self.assertEqual(result['completed']['b'], 2)

    def test_complete_bound_bundle_can_be_evaluated_and_time_criterion_is_real(self):
        for minutes, eligible in ((5, True), (10, False)):
            with self.subTest(minutes=minutes), tempfile.TemporaryDirectory() as folder:
                path, cases = pilot_fixture(Path(folder), b_minutes=minutes)
                out = StringIO()
                call_command('lab_pilot_report', input=str(path), stdout=out)
                self.assertEqual(json.loads(out.getvalue())['eligible_for_review'], eligible)

    def test_tampered_draft_missing_case_or_changed_source_is_denied(self):
        for defect in ('draft', 'missing', 'source'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                path, cases = pilot_fixture(root)
                case = cases[0]
                if defect == 'draft':
                    (root / case['id'] / 'draft.md').write_text('different body', encoding='utf-8')
                elif defect == 'missing':
                    (root / case['id'] / 'case.json').unlink()
                else:
                    source = json.loads((root / 'source.json').read_text(encoding='utf-8'))
                    source['code_fingerprint'] = 'different'
                    (root / 'source.json').write_text(json.dumps(source), encoding='utf-8')
                with self.assertRaises(CommandError):
                    call_command('lab_pilot_report', input=str(path), stdout=StringIO())
