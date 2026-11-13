import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from office.model_router import use_profile
from office.run_context import RunContext, RunBudgetExceeded, run_context
from office.services import ask_agent
from office.review_batch import run as review_batch
from office.delta_review import scope_check


class RunRecoveryTests(SimpleTestCase):
    def test_revision_admission_preserves_hard_cap_and_resume_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RunContext(root=tmp, max_calls=24)
            ctx.data['calls'] = 15
            self.assertTrue(ctx.can_start_revision())
            ctx.data['calls'] = 16
            ctx.save()
            resumed = RunContext(root=tmp, run_id=ctx.run_id)
            self.assertFalse(resumed.can_start_revision())
            self.assertEqual(resumed.budget()['remaining_calls'], 8)
            resumed.reserve()  # 임의로 예산을 늘리거나 호출을 미리 소모하지 않는다
            self.assertEqual(resumed.data['calls'], 17)

    def test_budget_errors_identify_call_or_time_limit(self):
        with self.assertRaisesRegex(RunBudgetExceeded, '호출 예산 0/0회'):
            RunContext(dry=True, max_calls=0).reserve()
        with self.assertRaisesRegex(RunBudgetExceeded, '시간 예산 0초'):
            RunContext(dry=True, max_seconds=0).reserve()
        self.assertFalse(RunContext(dry=True, max_seconds=599).can_start_revision())

    def test_same_request_reuses_completed_response_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp, use_profile('b'), \
                mock.patch('office.services.ask', return_value='검증된 응답') as ask:
            with run_context(root=tmp) as first:
                ask_agent('coding', '같은 요청')
                rid = first.run_id
            with run_context(root=tmp, run_id=rid) as resumed:
                self.assertEqual(ask_agent('coding', '같은 요청'), '검증된 응답')
                self.assertEqual(resumed.data['calls'], 1)
                self.assertEqual(resumed.data['reused'], 1)
                ask_agent('coding', '달라진 요청')
        self.assertEqual(ask.call_count, 2)

    def test_call_budget_survives_resume_and_cache_does_not_consume_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = RunContext(root=tmp, max_calls=1)
            first.reserve()
            again = RunContext(root=tmp, run_id=first.run_id, max_calls=1)
            with self.assertRaises(RunBudgetExceeded):
                again.reserve()

    def test_failed_required_parallel_step_is_not_silently_omitted(self):
        with self.assertRaisesRegex(RuntimeError, 'check'):
            review_batch({'check': ('checker', lambda: (_ for _ in ()).throw(ValueError('failed'))),
                          'critique': ('critic', lambda: {'verdict': 'recommend'})})

    def test_parallel_roles_read_one_version_without_changing_it(self):
        content = '원고 버전 A'
        result = review_batch({'check': ('checker', lambda: content), 'critique': ('critic', lambda: content)})
        self.assertEqual(set(result.values()), {content})


class DeltaScopeTests(SimpleTestCase):
    def test_only_literal_unchanged_claims_are_preserved(self):
        before = '확인된 사실이에요.\n\n' + ('고정 문단이에요.\n\n' * 15) + '옛 표현이에요.'
        after = before.replace('옛 표현', '새 표현')
        previous = {'verdict': 'pass', 'subject': '제목', 'claims': [
            {'claim_id': 'claim_a', 'claim': '확인된 사실이에요.', 'status': 'verified'}]}
        result = scope_check('제목', after, before, previous)
        self.assertIsNotNone(result)
        self.assertEqual(result['metadata']['preserved_claim_ids'], ['claim_a'])
        self.assertIn('새 표현', result['content'])

    def test_source_or_code_change_requires_full_review(self):
        previous = {'verdict': 'pass', 'subject': '제목', 'claims': []}
        self.assertIsNone(scope_check('제목', 'https://b.example', 'https://a.example', previous))
        self.assertIsNone(scope_check('제목', '```python\nx=2\n```', '```python\nx=1\n```', previous))
