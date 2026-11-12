from django.test import SimpleTestCase, TestCase
from office.lab_metrics import summarize
from office.adjudication import resolve
from office.model_router import use_profile


class ApprovedUsageTests(TestCase):
    def test_failed_stage_usage_is_kept_without_counting_recorded_calls_twice(self):
        from office.recorder import StageRecorder
        from office.run_context import run_context
        with run_context(dry=True) as context:
            stages = StageRecorder(dry=True)
            first = {'tags': {'stage': 'brief'}, 'input_tokens': 10, 'output_tokens': 1}
            failed = {'tags': {'stage': 'check'}, 'input_tokens': 20, 'output_tokens': 2, 'error': 'provider stopped'}
            context.active_calls.extend([first, failed])
            stages.record('brief', calls=[first])
            stages.record('fail', status='failed', error='check failed')
            stages.record('final')
            self.assertEqual([len(row['calls']) for row in stages.stages], [1, 1, 0])
            self.assertEqual(stages.stages[1]['calls'][0]['input_tokens'], 20)

    def test_approved_usage_includes_old_attempts_and_keeps_unmeasured_drafts(self):
        import json
        import tempfile
        import uuid
        from pathlib import Path
        from io import StringIO
        from datetime import timedelta
        from django.utils import timezone
        from django.core.management import call_command
        from office.models import ColumnDraft, StageRun
        from office.audit import append
        measured = ColumnDraft.objects.create(topic='data', status='hold')
        unknown = ColumnDraft.objects.create(topic='data', status='hold')
        append('approved', draft_id=measured.pk)
        append('approved', draft_id=unknown.pk)
        row = StageRun.objects.create(run_id=uuid.uuid4(), seq=1, draft=measured, stage='failed',
                                      calls=[{'input_tokens': 100, 'output_tokens': 10}])
        StageRun.objects.filter(pk=row.pk).update(created_at=timezone.now()-timedelta(days=60))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'quality.json')
            call_command('lab_quality_report', days=30, output=str(path), stdout=StringIO())
            report = json.loads(path.read_text(encoding='utf-8'))
        by_id = {row['draft_id']: row for row in report['approved_draft_usage']}
        self.assertEqual(by_id[measured.pk]['known_input_tokens'], 100)
        self.assertEqual(by_id[measured.pk]['recorded_calls'], 1)
        self.assertIsNone(by_id[unknown.pk]['known_input_tokens'])
        self.assertFalse(by_id[unknown.pk]['has_call_measurements'])


class MetricsTests(SimpleTestCase):
    def test_missing_usage_is_unknown_even_when_call_record_exists(self):
        report = summarize([{'run_id': 'x', 'seq': 1, 'stage': 'fail', 'output': {},
                            'calls': [{'input_tokens': None, 'output_tokens': None}]}])
        self.assertIsNone(report['runs'][0]['input_tokens'])
        self.assertEqual(report['runs'][0]['measured_usage_calls'], 0)
    def test_failure_before_review_is_in_denominator_and_missing_usage_is_unknown(self):
        report = summarize([{'run_id': 'failed', 'seq': 1, 'stage': 'fail', 'calls': [],
                             'error': 'provider unavailable', 'output': {}}])
        self.assertEqual(report['sample_size'], 1)
        self.assertEqual(report['before_review_failures'], 1)
        self.assertIsNone(report['runs'][0]['input_tokens'])
    def test_no_data_is_unknown_and_high_score_with_blocker_is_not_a_pass(self):
        self.assertIsNone(summarize([])['first_pass_rate'])
        report = summarize([{'run_id': 'x', 'seq': 1, 'stage': 'review', 'calls': [],
                             'output': {'verdict': 'accept', 'score': 100, 'must_fix': [{'problem': '근거 없음'}]}}])
        self.assertEqual(report['first_pass_count'], 0)
        self.assertFalse(report['runs'][0]['has_call_measurements'])

    def test_independent_adjudication_requires_real_quote_and_never_overrides_failed_facts(self):
        calls = []
        def ask(*args, **kwargs):
            calls.append(1)
            return {'uphold': False, 'quote': '원고에 없는 문장입니다.', 'reason': '인용이 맞지 않아요'}
        critique = {'verdict': 'reject', 'reason': '독자에게 도움이 없어요'}
        with use_profile('b'):
            self.assertEqual(resolve('제목', '실제 원고 문장입니다.', {}, {'verdict': 'pass'}, critique,
                                     ask_json=ask, score=100)['verdict'], 'reject')
            resolve('제목', '원고', {}, {'verdict': 'revise'}, critique, ask_json=ask, score=100)
        self.assertEqual(len(calls), 1)
