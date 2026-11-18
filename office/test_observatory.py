import json
import re
from pathlib import Path
import tempfile
import uuid
from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone

from office import activity
from office.models import ColumnDraft, JobRequest, StageRun
from office.observatory import snapshot
from office.run_context import run_context

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}


class ObservatoryTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(LAB_ACTIVITY_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.root = Path(directory.name)
        self.user = User.objects.create_superuser('observer', '', 'x')
        self.draft = ColumnDraft.objects.create(topic='coding', subject='재작성 중인 칼럼', content='기존 본문',
                                               status='revising', qa_report={'score': 80})
        self.run_id, self.execution_id = uuid.uuid4(), uuid.uuid4()
        self.job = JobRequest.objects.create(kind='revise', args=['office_revise', '--draft', str(self.draft.pk)],
            draft=self.draft, run_after=timezone.now(), status='started', execution_id=self.execution_id,
            lease_until=timezone.now()+timedelta(minutes=2), checkpoint_run_id=self.run_id)
        self.stage = StageRun.objects.create(run_id=self.run_id, draft=self.draft, seq=1, stage='revision_candidate',
            agent='coding', output={'content': '<script>untrusted()</script>', 'requirements': ['R1']})
        self.payload = {'run_id': str(self.run_id), 'metadata': {'job_id': str(self.job.pk),
            'execution_id': str(self.execution_id)}, 'updated_at': timezone.now().isoformat(),
            'calls': [{'id': 'abc', 'agent': 'editor', 'stage': 'revision_verify', 'model': 'test-model',
                       'state': 'running', 'started_at': timezone.now().isoformat(), 'result': ''}]}
        self.save_activity()

    def save_activity(self):
        (self.root/(str(self.run_id)+'.json')).write_text(json.dumps(self.payload), encoding='utf-8')

    def login(self):
        self.client.force_login(self.user)
        otp = patch('common.views._admin_otp_session_ok', return_value=True)
        otp.start()
        self.addCleanup(otp.stop)

    def test_operator_and_otp_protect_page_state_and_detail(self):
        paths = ['/lab/admin/observatory/', '/lab/admin/observatory/state.json',
                 f'/lab/admin/observatory/detail.json?run={self.run_id}&item=stage-{self.stage.pk}']
        for path in paths:
            self.assertEqual(self.client.get(path, **UA).status_code, 302)
        staff = User.objects.create_user('staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(paths[1], **UA).status_code, 302)
        self.client.force_login(self.user)
        with patch('common.views.admin_otp_gate') as gate:
            from django.http import HttpResponse
            gate.return_value = HttpResponse('재인증', status=403)
            self.assertEqual(self.client.get(paths[1], **UA).status_code, 403)

    def test_snapshot_combines_live_calls_and_persisted_outputs_without_mutating_work(self):
        self.login()
        response = self.client.get('/lab/admin/observatory/state.json', **UA)
        self.assertEqual(response['Cache-Control'], 'no-store')
        work = response.json()['works'][0]
        self.assertEqual(work['job_id'], self.job.pk)
        self.assertEqual({c['agent'] for c in work['calls']}, {'coding', 'editor'})
        self.assertEqual([c for c in work['calls'] if c['id'] == 'call-abc'][0]['state'], 'running')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'started')
        detail = self.client.get('/lab/admin/observatory/detail.json',
                                {'run': str(self.run_id), 'item': f'stage-{self.stage.pk}'}, **UA).json()
        self.assertIn('<script>untrusted()</script>', detail['text'])

    def test_team_is_rendered_in_full_even_when_no_work_is_selected(self):
        from office.agents import AGENTS
        self.login()
        html = self.client.get('/lab/admin/observatory/', **UA).content.decode()
        for key, agent in AGENTS.items():
            self.assertIn(f'data-agent="{key}" data-state="idle"', html)
            self.assertIn(agent['name'], html)
        self.assertIn('data-motion', html)

    def test_transfers_keep_recorded_sender_and_recipient_without_inventing_relationships(self):
        self.stage.sender, self.stage.recipient = 'coding', 'checker'
        self.stage.save(update_fields=['sender', 'recipient'])
        work = next(w for w in snapshot()['works'] if w['id'] == str(self.run_id))
        stage = next(c for c in work['calls'] if c['id'] == f'stage-{self.stage.pk}')
        self.assertEqual((stage['sender'], stage['recipient']), ('coding', 'checker'))
        call = next(c for c in work['calls'] if c['id'] == 'call-abc')
        self.assertNotIn('sender', call)

    def test_polling_does_not_load_full_stage_outputs_or_call_records(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            snapshot()
        table = connection.ops.quote_name('office_stagerun')
        stage_selects = [q['sql'] for q in queries if f'FROM {table}' in q['sql']]
        self.assertTrue(stage_selects)
        for sql in stage_selects:
            for field in ('output', 'calls'):
                self.assertNotRegex(sql, rf'(?:SELECT\s+|,\s*){re.escape(table)}\.{re.escape(connection.ops.quote_name(field))}(?:\s*,|\s+FROM)')
            self.assertNotIn('$."content"', sql)
        self.assertLessEqual(len(queries), 8)

    def test_successful_execution_with_failed_review_is_shown_as_not_passed(self):
        StageRun.objects.create(run_id=self.run_id, draft=self.draft, seq=2, stage='review', agent='editor',
            output={'verdict': 'accept', 'score': 96, 'must_fix': [{'problem': '출처 미확인', 'fix': '원문 대조'}]})
        work = next(w for w in snapshot()['works'] if w['id'] == str(self.run_id))
        saved = next(c for c in work['calls'] if c['stage'] == 'review')
        self.assertEqual(saved['state'], 'done')
        self.assertEqual(saved['outcome']['state'], 'blocked')

    def test_latest_result_only_is_used_for_each_agents_signal(self):
        first = StageRun.objects.create(run_id=self.run_id, seq=2, stage='check', agent='checker',
                                       output={'verdict': 'fail'})
        last = StageRun.objects.create(run_id=self.run_id, seq=3, stage='recheck', agent='checker',
                                      output={'verdict': 'pass', 'claims': []})
        work = next(w for w in snapshot()['works'] if w['id'] == str(self.run_id))
        self.assertIsNone(next(c for c in work['calls'] if c['id'] == f'stage-{first.pk}')['outcome'])
        self.assertEqual(next(c for c in work['calls'] if c['id'] == f'stage-{last.pk}')['outcome']['state'], 'passed')

    def test_final_report_includes_only_the_review_matching_its_digest(self):
        from office.audit import fingerprint
        from office.evidence_bundle import report_payload
        from office.observatory import detail
        qa = {'verdict': 'minor', 'score': 75, 'must_fix': [{'problem': '핵심 출처 누락', 'fix': '원문 링크 추가'}]}
        review = StageRun.objects.create(run_id=self.run_id, seq=2, stage='review', agent='editor', output=qa)
        final = StageRun.objects.create(run_id=self.run_id, seq=3, stage='final', agent='editor',
            output={'verdict': 'minor', 'score': 75, 'review_digest': fingerprint(report_payload(qa))})
        value = detail(str(self.run_id), f'stage-{final.pk}')
        self.assertIn('핵심 출처 누락', json.dumps(value['report'], ensure_ascii=False))
        self.assertNotIn('핵심 출처 누락', value['text'])
        review.output = {**qa, 'notes': '다른 버전의 심사'}
        review.save(update_fields=['output'])
        self.assertNotIn('다른 버전의 심사', json.dumps(detail(str(self.run_id), f'stage-{final.pk}')['report'], ensure_ascii=False))

    def test_completed_and_stale_jobs_never_claim_a_call_is_still_running(self):
        for fields in ({'status': 'completed'}, {'lease_until': timezone.now()-timedelta(seconds=1)}):
            JobRequest.objects.filter(pk=self.job.pk).update(**fields)
            work = next(w for w in snapshot()['works'] if w['id'] == str(self.run_id))
            self.assertEqual(next(c for c in work['calls'] if c['id'] == 'call-abc')['state'], 'unknown')

    def test_pending_job_is_visible_before_first_call_and_bad_file_is_ignored(self):
        job = JobRequest.objects.create(kind='rerun', args=['hold_meeting'], label='편집회의',
                                         status='pending', run_after=timezone.now())
        (self.root/(str(uuid.uuid4())+'.json')).write_text('{', encoding='utf-8')
        work = next(w for w in snapshot()['works'] if w['id'] == f'job-{job.pk}')
        self.assertEqual(work['state'], 'pending')
        self.assertEqual(work['calls'], [])

    def test_two_drafts_in_one_job_keep_their_own_run_titles(self):
        other = ColumnDraft.objects.create(topic='coding', subject='두 번째 유형 칼럼', content='다른 본문')
        JobRequest.objects.filter(pk=self.job.pk).update(draft=other)
        work = next(w for w in snapshot()['works'] if w['id'] == str(self.run_id))
        self.assertEqual(work['title'], self.draft.subject)

    def test_detail_rejects_paths_and_cross_run_ids(self):
        self.login()
        for run in ('../../.env', str(uuid.uuid4())):
            self.assertEqual(self.client.get('/lab/admin/observatory/detail.json',
                {'run': run, 'item': f'stage-{self.stage.pk}'}, **UA).status_code, 404)

    def test_restarted_job_is_not_linked_to_its_old_running_call(self):
        JobRequest.objects.filter(pk=self.job.pk).update(execution_id=uuid.uuid4())
        work = next(w for w in snapshot()['works'] if w['id'] == str(self.run_id))
        self.assertIsNone(work['job_id'])
        self.assertEqual(next(c for c in work['calls'] if c['id'] == 'call-abc')['state'], 'unknown')

    def test_only_otp_authenticated_operator_polling_skips_request_counters(self):
        from django.test import RequestFactory
        from common.middleware import SecurityMiddleware
        middleware = SecurityMiddleware(lambda request: None)
        request = RequestFactory().get('/lab/admin/observatory/state.json', **UA)
        request.user = self.user
        block = patch.object(middleware, 'block_ip')
        block.start()
        self.addCleanup(block.stop)
        with patch.object(middleware, 'is_ip_blocked', return_value=False), \
             patch.object(middleware, 'is_rate_limited', return_value=True) as limited, \
             patch('common.views._admin_otp_session_ok', return_value=True):
            self.assertIsNone(middleware.check_security(request))
            limited.assert_not_called()
        with patch.object(middleware, 'is_ip_blocked', return_value=False), \
             patch.object(middleware, 'is_rate_limited', return_value=True), \
             patch('common.views._admin_otp_session_ok', return_value=False):
            self.assertEqual(middleware.check_security(request).status_code, 429)
        with patch.object(middleware, 'is_ip_blocked', return_value=True):
            self.assertEqual(middleware.check_security(request).status_code, 403)


class ActivityTests(SimpleTestCase):
    def test_polling_uses_short_preview_and_detail_reads_response_only_on_selection(self):
        from office.observatory import detail
        with tempfile.TemporaryDirectory() as directory, override_settings(LAB_ACTIVITY_ROOT=directory), \
             run_context(root=Path(directory)/'checkpoints') as context:
            with activity.observe('checker', 'check', 'test') as row:
                row['result'] = '긴 응답 내용' * 300
            self.assertEqual(len(activity.recent()[0]['calls'][0]['result']), 240)
            self.assertEqual(detail(context.run_id, 'call-'+row['id'])['text'], '긴 응답 내용' * 300)

    def test_observation_records_parallel_calls_and_contains_no_prompt(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        with tempfile.TemporaryDirectory() as directory, override_settings(LAB_ACTIVITY_ROOT=directory), \
             run_context(root=Path(directory)/'checkpoints') as context:
            def call(agent):
                with activity.observe(agent, 'check', 'test') as row:
                    row['result'] = '완료 응답'
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(copy_context().run, call, key) for key in ('checker', 'critic')]
                for future in futures:
                    future.result()
            payload = json.loads((Path(directory)/(context.run_id+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(len(payload['calls']), 2)
            self.assertEqual({c['state'] for c in payload['calls']}, {'done'})
            self.assertNotIn('prompt', payload)

    def test_failed_call_is_not_left_running_and_observation_failure_does_not_block_work(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(LAB_ACTIVITY_ROOT=directory), \
             run_context(root=Path(directory)/'checkpoints') as context:
            with self.assertRaisesRegex(RuntimeError, '호출 실패'):
                with activity.observe('checker', 'check', 'test'):
                    raise RuntimeError('호출 실패')
            self.assertEqual(activity.recent()[0]['calls'][0]['state'], 'failed')
            with patch('office.artifacts.atomic_write', side_effect=OSError('쓰기 실패')):
                with activity.observe('coding', 'draft', 'test'):
                    pass
