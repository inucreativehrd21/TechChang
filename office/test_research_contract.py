"""수치·주장 계약과 재심 누락은 점수보다 우선한다."""
from unittest import mock
from django.test import SimpleTestCase

from office import evidence as E, blueprint as B, review_protocol as R
from office.model_router import use_profile
from office.research_contract import bind


class ResearchContractTests(SimpleTestCase):
    def test_number_equal_but_units_differ_do_not_support_claim(self):
        self.assertFalse(E.quote_supports('응답 4564명', 'We recorded 4564 cases'))
        self.assertTrue(E.quote_supports('산업 수익 45.64억 달러', 'Revenue reached $4.564 billion'))
        self.assertFalse(E.quote_supports('산업 수익 45.64억 달러', 'Revenue reached $45.64 billion'))
        self.assertFalse(E.quote_supports('증감률 -45.64%', 'growth 45.64%'))
        self.assertFalse(E.quote_supports('측정값 1e3', 'measurement 1e4'))

    def test_unknown_scope_and_unsupported_inference_are_not_verified(self):
        row = {'claim': '2025년 참가자 500명', 'status': 'verified', 'quote': '500 participants in 2022',
               'url': 'https://example.org/report', 'period': '2022', 'population': 'participants',
               'source_locator': 'results', 'entailment': 'supported'}
        self.assertEqual(bind(row, {'claim': row['claim'], 'period': '2025'}, strict=True)['status'], 'unverifiable')
        row['entailment'] = 'insufficient'
        self.assertEqual(bind(row, {'claim': row['claim']}, strict=True)['status'], 'unverifiable')

    def test_internal_metadata_numbers_are_not_evidence(self):
        pack = '확인한 수치 200명 [주장 claim_14591abc; 출처 source_123; 대상 직원; 기간 2025]'
        self.assertTrue(E.unmatched('응답자는 14,591명이에요.', pack))

    def test_empty_pack_is_not_a_numeric_pass_in_b(self):
        with use_profile('b'):
            self.assertTrue(E.unmatched('응답자는 14,591명이에요.', ''))

    def test_explicit_software_version_is_not_a_statistic(self):
        with use_profile('b'):
            self.assertEqual(E.unmatched('Django 5.2 기준이에요.', ''), [])
            self.assertTrue(E.unmatched('Django 5.2에서 응답 시간이 45.64% 줄었어요.', ''))
            self.assertTrue(E.unmatched('Django 45.64% 개선이에요.', ''))

    def test_extra_claims_are_reported_instead_of_silently_discarded(self):
        claims = [{'claim': f'검증할 주장 {i}'} for i in range(18)]
        result = E.gather(claims, ask_json=lambda *a, **kw: {'claims': []})
        self.assertEqual(len(result), 18)
        self.assertTrue(all(c['claim_id'] for c in result))
        self.assertIn('예산 초과', result[-1]['note'])

    def test_wrong_claim_order_cannot_borrow_another_claims_evidence(self):
        result = E.gather([{'claim': '주장 A'}], ask_json=lambda *a, **kw: {'claims': [
            {'claim': '주장 B', 'status': 'verified', 'quote': 'Other claim', 'url': 'https://example.org'}]})
        self.assertEqual(result[0]['status'], 'unverifiable')

    def test_unverified_blueprint_does_not_become_verified_on_failure(self):
        bp = {'thesis': '가설', 'claims': [{'claim': '근거가 없는 주장'}]}
        self.assertIn('쓰면 안 되는 주장', B.block(bp, {}))
        with use_profile('b'), self.assertRaises(RuntimeError):
            B.verify_blueprint(bp, ask_json=lambda *a, **kw: {})


class IssueContractTests(SimpleTestCase):
    def test_no_blockers_does_not_trigger_an_empty_revision_in_b(self):
        with use_profile('b'):
            qa = R.finalize({'verdict': 'minor', 'score': 75, 'must_fix': [], 'fatal': []})
        self.assertTrue(R.publishable(qa))
    def test_high_score_cannot_override_must_fix(self):
        qa = R.normalize({'verdict': 'accept', 'score': 100, 'fatal': [], 'must_fix': [{'where': 'a', 'problem': 'b'}]})
        self.assertFalse(R.publishable(R.finalize(qa)))

    def test_each_previous_issue_requires_its_own_resolution(self):
        previous = R.normalize({'must_fix': [{'where': 'a', 'problem': '틀린 주장', 'fix': '지워요'}]})
        iid = previous['must_fix'][0]['issue_id']
        with use_profile('b'):
            for resolution in ({}, {iid: {'resolved': 'true', 'evidence': '수정'}}, {iid: {'resolved': True}}):
                qa = R.finalize({'verdict': 'accept', 'must_fix': [], 'resolutions': resolution}, previous)
                self.assertFalse(R.publishable(qa))
            qa = R.finalize({'verdict': 'accept', 'must_fix': [],
                             'resolutions': {iid: {'resolved': True, 'evidence': '틀린 문장을 삭제했어요'}}}, previous)
            self.assertTrue(R.publishable(qa))

    def test_ids_survive_normalization_and_prompt_roundtrip(self):
        qa = R.normalize({'must_fix': [{'where': '도입', 'problem': '과장'}]})
        iid = qa['must_fix'][0]['issue_id']
        self.assertIn(iid, R.previous_block(qa))
        self.assertEqual(R.normalize(qa)['must_fix'][0]['issue_id'], iid)
