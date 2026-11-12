from copy import deepcopy
from datetime import timedelta
from unittest import mock
import os
import uuid
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from office.models import ColumnDraft, JobRequest, AuditEvent, StageRun
from office import approval, audit
from office.pipeline import verification_hash
from office.recorder import digest
from office.execution import LeaseLost
from django.core.management import call_command
from io import StringIO
from pathlib import Path
import tempfile


def certified(draft):
    draft.check_report = {'verdict': 'pass', 'subject': draft.subject,
                          'verification_hash': verification_hash(draft.content), 'claims': []}
    draft.qa_report = {**draft.qa_report, 'verified_subject': draft.subject,
                      'verified_content_hash': verification_hash(draft.content),
                      'reviewed_full_hash': digest(draft.content)}
    from office.recorder import StageRecorder
    stages = StageRecorder(draft=draft)
    stages.record('check', output=draft.check_report)
    stages.record('review', output=draft.qa_report)
    stages.complete(draft.subject, draft.content, draft.check_report, draft.qa_report)
    draft.save()
    return draft


class PublicationSafetyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('admin', '', 'x')
        self.draft = certified(ColumnDraft.objects.create(topic='data', status='hold', subject='원고', content='비공개 본문',
                                qa_report={'verdict': 'accept', 'score': 90}))

    def test_normal_approval_binds_evidence_and_review_not_just_body(self):
        approval.approve(self.draft, self.owner)
        self.assertTrue(approval.valid(self.draft))
        self.draft.check_report['claims'] = [{'claim': '새 주장', 'status': 'wrong'}]
        self.assertFalse(approval.valid(self.draft))
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner, '사유가 있어도 사실 실패는 금지', mode='exception')

    def test_review_change_and_source_stage_change_invalidate_approval(self):
        row = StageRun.objects.get(draft=self.draft, stage='check')
        approval.approve(self.draft, self.owner)
        StageRun.objects.filter(pk=row.pk).update(output={'fact': '바뀐 원문'})
        self.assertFalse(approval.valid(self.draft))

    def test_exception_requires_explicit_mode_and_only_format_issues(self):
        self.draft.qa_report.update(verdict='major', fatal=['style_broken'], must_fix=[{'problem': '문체', 'kind': 'style'}])
        certified(self.draft)
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner, '사유만으로 일반 승인 불가')
        approval.approve(self.draft, self.owner, '문체는 운영자가 확인했어요', mode='exception')
        self.assertTrue(approval.valid(self.draft))
        self.assertEqual(AuditEvent.objects.latest('sequence').action, 'exception_approved')

    def test_expired_check_cannot_be_overridden(self):
        self.draft.check_report['verification_hash'] = 'stale'
        self.draft.save()
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner, '운영자 지시', mode='exception')

    def test_approval_form_binds_the_displayed_evidence_version(self):
        self.client.force_login(self.owner)
        self.draft.publish_at = timezone.now()+timedelta(hours=1)
        self.draft.save()
        response = self.client.get('/lab/admin/', HTTP_USER_AGENT='Mozilla/5.0')
        shown = response.context['held'][0].approval_version
        self.assertContains(response, f'name="version" value="{shown}"')
        StageRun.objects.create(run_id=uuid.uuid4(), seq=1, draft=self.draft, stage='check', output={'fact': '새 근거'})
        self.client.post(f'/lab/admin/draft/{self.draft.pk}/publish/', {'version': shown}, HTTP_USER_AGENT='Mozilla/5.0')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'hold')
        self.assertFalse(AuditEvent.objects.filter(action='approved').exists())
        certified(self.draft)
        refreshed = self.client.get('/lab/admin/', HTTP_USER_AGENT='Mozilla/5.0').context['held'][0].approval_version
        self.client.post(f'/lab/admin/draft/{self.draft.pk}/publish/', {'version': refreshed}, HTTP_USER_AGENT='Mozilla/5.0')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'ready')
        self.assertTrue(approval.valid(self.draft))

    def test_approval_post_without_displayed_version_is_denied(self):
        self.client.force_login(self.owner)
        self.client.post(f'/lab/admin/draft/{self.draft.pk}/publish/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertFalse(AuditEvent.objects.filter(action='approved').exists())

    def test_changed_fact_report_cannot_approve_a_stale_object(self):
        ColumnDraft.objects.filter(pk=self.draft.pk).update(check_report={'verdict': 'revise'})
        with self.assertRaises(ValueError):
            approval.approve(self.draft, self.owner)

    def test_approval_audit_is_append_only_and_reconstructs_original(self):
        approval.approve(self.draft, self.owner)
        event = AuditEvent.objects.first()
        self.assertEqual(event.payload['snapshot']['content'], self.draft.content)
        self.assertTrue(audit.verify())
        with self.assertRaises(ValueError):
            AuditEvent.objects.filter(pk=event.pk).update(payload={})
        with self.assertRaises(ValueError):
            event.delete()

    def test_audit_export_is_restored_in_separate_database_with_exact_hashes(self):
        approval.approve(self.draft, self.owner)
        with tempfile.TemporaryDirectory() as folder, override_settings(BASE_DIR=folder):
            call_command('lab_audit', export=True, restore_check=True, stdout=StringIO())
            files = list(Path(folder, 'logs/private-lab').glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertIn('비공개 본문', files[0].read_text(encoding='utf-8'))
        self.assertTrue(audit.verify())

    def test_old_execution_cannot_save_draft_after_lease_expiry(self):
        token = uuid.uuid4()
        job = JobRequest.objects.create(kind='rerun', args=['make_newsletter'], status='started',
                  execution_id=token, run_after=timezone.now(), lease_until=timezone.now()-timedelta(seconds=1))
        with mock.patch.dict(os.environ, {'LAB_JOB_ID': str(job.pk), 'LAB_EXECUTION_ID': str(token)}):
            self.draft.content = '뒤늦게 도착한 이전 결과'
            with self.assertRaises(LeaseLost):
                self.draft.save()


class LabIsolationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('admin', '', 'x')
        self.member = User.objects.create_user('member')
        self.staff = User.objects.create_user('staff', is_staff=True)

    def test_nonoperators_cannot_read_or_trigger_admin_surfaces(self):
        from office.jobmail import make_token
        token = make_token('rerun', ['make_newsletter'], '숨겨야 하는 작업')
        urls = ['/lab/admin/', '/lab/admin/activity.json', '/lab/admin/draft/1/audit.json', f'/lab/job/{token}/']
        for user in (None, self.member, self.staff):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in urls:
                response = self.client.get(url, HTTP_USER_AGENT='Mozilla/5.0')
                self.assertEqual(response.status_code, 302, (user, url))
        self.assertEqual(JobRequest.objects.count(), 0)

    def test_raw_logs_need_otp_even_for_owner(self):
        self.client.force_login(self.owner)
        response = self.client.get('/lab/admin/activity.json', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertIn('otp', response.url)

    def test_django_admin_permissions_cannot_bypass_operator_allowlist(self):
        from django.contrib import admin
        from django.contrib.auth.models import Permission
        from django.test import RequestFactory
        from office.models import HumanReview, Meeting, WorkLog
        self.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label='office'))
        request = RequestFactory().get('/')
        request.user = self.staff
        for model in (ColumnDraft, StageRun, AuditEvent, HumanReview, Meeting, WorkLog):
            registered = admin.site._registry[model]
            self.assertFalse(registered.has_module_permission(request), model.__name__)
            self.assertFalse(registered.has_view_permission(request), model.__name__)
            self.assertFalse(registered.has_add_permission(request), model.__name__)
            self.assertFalse(registered.has_change_permission(request), model.__name__)
            self.assertFalse(registered.has_delete_permission(request), model.__name__)

    def test_mail_link_cannot_be_replayed_after_job_finished(self):
        from office.jobmail import enqueue
        data = {'k': 'rerun', 'a': ['make_newsletter'], 'l': '작업'}
        first, created = enqueue(data)
        first.status = 'completed'
        first.save()
        second, created = enqueue(data)
        self.assertEqual(first.pk, second.pk)
        self.assertFalse(created)

    def test_model_cli_environment_does_not_inherit_database_or_mail_secret(self):
        from office.environment import claude_environment
        with mock.patch.dict(os.environ, {'DB_PASSWORD': 'canary', 'EMAIL_HOST_PASSWORD': 'canary',
                                          'ANTHROPIC_API_KEY': 'canary'}):
            env = claude_environment()
        self.assertNotIn('canary', env.values())

    def test_systemd_transport_environment_reaches_worker_but_not_model_cli(self):
        from office.environment import worker_environment, claude_environment
        transport = {'XDG_RUNTIME_DIR': '/run/user/1001',
                     'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1001/bus'}
        with mock.patch.dict(os.environ, transport):
            worker, cli = worker_environment(), claude_environment()
        for name, value in transport.items():
            self.assertEqual(worker[name], value)
            self.assertNotIn(name, cli)

    def test_public_state_does_not_expose_internal_meeting_or_cached_private_title(self):
        from office.models import Meeting, Decision, WorkLog
        meeting = Meeting.objects.create(week_start=timezone.now().date(), summary='PRIVATE-CANARY',
                    transcript=[{'agent': 'lead', 'text': 'PRIVATE-CANARY'}], public_summary='공개 회의 요약')
        Decision.objects.create(meeting=meeting, kind='ops', question='PRIVATE-CANARY',
                    options=[{'key': 'a', 'title': 'PRIVATE-CANARY'}], chosen_key='a')
        draft = ColumnDraft.objects.create(topic='data', status='hold', subject='PRIVATE-CANARY', content='PRIVATE-CANARY')
        WorkLog.objects.create(draft=draft, agent='data', action='draft', text='PRIVATE-CANARY', public_text='PRIVATE-CANARY')
        response = self.client.get('/lab/state.json', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('PRIVATE-CANARY', response.content.decode())
        self.assertIn('공개 회의 요약', response.json()['meeting']['summary'])

    def test_command_arguments_cannot_inject_global_settings_or_file_paths(self):
        from office.security import validate_args
        for args in (['office_publish', '--settings', 'evil'],
                     ['office_revise', '--content-file', '/etc/passwd'],
                     ['office_revise', '--note', '--settings=evil']):
            with self.assertRaises(ValueError):
                validate_args(args)


class LeaseRecoveryTests(TestCase):
    def job(self):
        return JobRequest.objects.create(kind='rerun', args=['make_newsletter'], status='started',
              run_after=timezone.now(), started_at=timezone.now()-timedelta(minutes=5), execution_id=uuid.uuid4(),
              lease_until=timezone.now()-timedelta(seconds=1), process_id=123, process_identity='old', active_key='active')

    def test_expired_child_is_stopped_before_releasing_queue(self):
        from office.job_supervision import recover
        job = self.job()
        with mock.patch('office.job_supervision.active', return_value=True), \
                mock.patch('office.job_supervision.stop', return_value=True) as stop:
            recover(out=lambda _: None)
        stop.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, 'interrupted')
        self.assertIsNone(job.active_key)

    def test_unknown_stop_result_quarantines_instead_of_starting_another_job(self):
        from office.job_supervision import recover
        job = self.job()
        with mock.patch('office.job_supervision.active', return_value=True), \
                mock.patch('office.job_supervision.stop', return_value=False):
            recover(out=lambda _: None)
        job.refresh_from_db()
        self.assertEqual(job.status, 'quarantined')
        self.assertEqual(job.active_key, 'active')

    def test_reused_pid_is_not_killed(self):
        from office.job_supervision import stop
        job = self.job()
        with mock.patch('office.job_supervision.managed', return_value=False), \
                mock.patch('office.job_supervision.identity', return_value='different'), \
                mock.patch('office.job_supervision.subprocess.run') as run:
            self.assertTrue(stop(job))
        run.assert_not_called()

    @override_settings(LAB_JOB_SUPERVISOR='process')
    def test_native_child_identity_and_stop_are_confirmed(self):
        import subprocess
        import sys
        from office.job_supervision import identity, active, stop
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        try:
            job = self.job()
            job.process_id, job.process_identity = proc.pid, identity(proc.pid)
            self.assertTrue(job.process_identity)
            self.assertTrue(active(job))
            self.assertTrue(stop(job))
            proc.wait(timeout=5)
            self.assertFalse(active(job))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_linux_zombie_is_ended_and_does_not_block_queue(self):
        from office.job_supervision import active, stop
        job = self.job()
        with mock.patch('office.job_supervision.managed', return_value=False), \
                mock.patch('office.job_supervision.identity', return_value='exited-zombie'), \
                mock.patch('office.worker.alive', return_value=True):
            self.assertFalse(active(job))
            self.assertTrue(stop(job))

    def test_cancelled_execution_cannot_overwrite_new_execution(self):
        from office.execution import assert_current
        job = self.job()
        old = str(job.execution_id)
        job.execution_id, job.lease_until = uuid.uuid4(), timezone.now()+timedelta(minutes=2)
        job.save()
        with mock.patch.dict(os.environ, {'LAB_JOB_ID': str(job.pk), 'LAB_EXECUTION_ID': old}):
            with self.assertRaises(LeaseLost):
                assert_current()
