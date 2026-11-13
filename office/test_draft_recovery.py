import json
import uuid
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from office.models import ColumnDraft, StageRun, JobRequest, AuditEvent
from office.pipeline import verification_hash
from office.recorder import digest


class DraftRecoveryTests(TestCase):
    def setUp(self):
        self.draft = ColumnDraft.objects.create(topic='coding', status='hold',
                                                qa_report={'admin_revision': {'status': 'retained'}})
        self.body = '마지막으로 심사한 본문이에요.'
        self.run_id = uuid.uuid4()
        self.stage('draft', {'subject': '제목', 'content': self.body})
        self.stage('check', {'subject': '제목', 'verification_hash': verification_hash(self.body), 'verdict': 'pass'})
        self.stage('review', {'verified_subject': '제목', 'reviewed_full_hash': digest(self.body),
                              'score': 73, 'verdict': 'minor', 'human_approval': {'old': True}})
        self.stage('editor_patch', {'subject': '미검수 수정본', 'content': '아직 심사를 안 받은 내용'})

    def stage(self, name, output):
        return StageRun.objects.create(draft=self.draft, run_id=self.run_id,
            seq=self.draft.stages.count()+1, stage=name, output=output)

    def test_preview_does_not_write_and_apply_restores_reviewed_version_without_approval(self):
        out = StringIO()
        call_command('office_recover_draft', draft=self.draft.pk, stdout=out)
        self.assertEqual(json.loads(out.getvalue())['score'], 73)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.content, '')
        self.assertFalse(AuditEvent.objects.filter(action='draft_recovered').exists())
        call_command('office_recover_draft', draft=self.draft.pk, apply=True, stdout=StringIO())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.content, self.body)
        self.assertEqual(self.draft.status, 'hold')
        self.assertNotIn('human_approval', self.draft.qa_report)
        self.assertNotIn('evidence_run_id', self.draft.qa_report)
        event = AuditEvent.objects.get(action='draft_recovered')
        self.assertEqual(event.payload['before']['qa_report']['admin_revision']['status'], 'retained')

    def test_hash_mismatch_or_active_job_blocks_recovery(self):
        review = self.draft.stages.get(stage='review')
        review.output['reviewed_full_hash'] = 'different'
        review.save()
        with self.assertRaisesRegex(CommandError, '지문이 일치'):
            call_command('office_recover_draft', draft=self.draft.pk, apply=True)
        review.output['reviewed_full_hash'] = digest(self.body)
        review.save()
        JobRequest.objects.create(draft=self.draft, args=['office_revise', '--draft', str(self.draft.pk)],
                                  run_after=timezone.now(), status='pending')
        with self.assertRaisesRegex(CommandError, '실행 중 작업'):
            call_command('office_recover_draft', draft=self.draft.pk, apply=True)

    def test_existing_body_is_never_overwritten(self):
        self.draft.content = '운영자가 저장한 원고'
        self.draft.save()
        with self.assertRaisesRegex(CommandError, '비어 있는'):
            call_command('office_recover_draft', draft=self.draft.pk, apply=True)
