from django.test import SimpleTestCase
from office.lab_metrics import summarize
from office.adjudication import resolve
from office.model_router import use_profile


class MetricsTests(SimpleTestCase):
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
