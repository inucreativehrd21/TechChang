import json
from django.test import SimpleTestCase
from office.observatory_reports import outcome, report


class ManagerReportTests(SimpleTestCase):
    def test_fact_check_pass_label_does_not_hide_outdated_or_unverified_claims(self):
        for status in ('wrong', 'unverifiable', 'outdated'):
            with self.subTest(status=status):
                data = {'verdict': 'pass', 'claims': [{'claim': '기준판', 'status': status, 'note': '현행판으로 수정해 주세요.'}]}
                value = report('check', data)
                self.assertEqual(value['outcome']['state'], 'blocked')
                self.assertIn('현행판으로 수정', json.dumps(value, ensure_ascii=False))

    def test_review_blockers_cannot_be_hidden_by_high_score_or_accept(self):
        for key, value in [('must_fix', [{'problem': '근거 부족'}]), ('fatal', ['unsupported']),
                           ('unresolved_issue_ids', ['issue1']), ('resolved', [False])]:
            with self.subTest(key=key):
                self.assertEqual(outcome('review', {'verdict': 'accept', 'score': 99, key: value})['state'], 'blocked')

    def test_real_pass_and_runtime_completion_are_different(self):
        self.assertEqual(outcome('check', {'verdict': 'pass', 'claims': []})['state'], 'passed')
        self.assertEqual(outcome('review', {'verdict': 'accept', 'score': 81})['state'], 'passed')
        self.assertEqual(outcome('draft', {'subject': '원고'})['state'], 'completed')
        self.assertEqual(outcome('review', {'verdict': 'accept'}, canonical=False)['state'], 'completed')
        self.assertEqual(outcome('review', {'verdict': 'accept'}, 'running')['state'], 'running')
        self.assertEqual(outcome('review', {'verdict': 'accept'}, 'unknown')['state'], 'unknown')

    def test_revision_adoption_retention_and_pending_checks_are_explicit(self):
        self.assertEqual(outcome('revision_decision', {'status': 'retained'})['state'], 'blocked')
        self.assertEqual(outcome('revision_decision', {'status': 'adopted'})['state'], 'passed')
        self.assertEqual(outcome('revision_verify', {'verified': True, 'items': [{'met': None}]})['state'], 'waiting')
        self.assertEqual(outcome('revision_verify', {'verified': True, 'items': [{'met': True}]})['state'], 'passed')

    def test_must_fix_is_a_report_with_location_action_evidence_and_completion_criterion(self):
        value = report('review', {'verdict': 'minor', 'score': 75, 'must_fix': [
            {'where': '비교표', 'problem': '구판 사용', 'fix': '현행판 반영', 'done_when': '표와 결론 일치', 'evidence': '기준판 확인'}]})
        item = next(s for s in value['sections'] if s['title'] == '필수 수정과 완료 기준')['items'][0]
        self.assertEqual(item['title'], '구판 사용')
        self.assertEqual({f['label'] for f in item['fields']}, {'위치', '할 일', '완료 기준', '확인 근거'})

    def test_fenced_model_json_is_readable_but_is_not_a_confirmed_quality_pass(self):
        value = report('check', '```json\n{"verdict":"pass","notes":"주장 대조 완료"}\n```', canonical=False)
        self.assertEqual(value['outcome']['state'], 'completed')
        self.assertIn('주장 대조 완료', json.dumps(value, ensure_ascii=False))
        self.assertNotIn('```', json.dumps(value))

    def test_execution_metadata_and_hashes_do_not_leak_into_manager_report(self):
        value = report('draft', {'subject': '원고', 'content': '본문', 'execution': {'secret_marker': 'hidden'},
                                 'verification_hash': 'internal_digest'})
        serialized = json.dumps(value)
        self.assertNotIn('hidden', serialized)
        self.assertNotIn('internal_digest', serialized)

    def test_team_brief_is_readable_as_questions_evidence_cases_and_limits(self):
        value = report('brief', {'angle': '판단 행동을 비교해요.', 'questions': ['무엇을 재나요?'],
            'data_needed': ['공식 기준판'], 'cases': ['직무 사례'], 'counterpoint': '적용 범위가 달라요.', 'avoid': ['성과 과장']})
        titles = {s['title'] for s in value['sections']}
        self.assertTrue({'집필 방향', '답해야 할 질문', '찾아야 할 근거·지표', '검토할 사례', '반론과 한계', '피해야 할 내용'} <= titles)

    def test_malformed_and_large_outputs_are_bounded_without_false_pass(self):
        self.assertEqual(outcome('check', {'verdict': 'pass', 'claims': 'bad'})['state'], 'unknown')
        value = report('review', {'verdict': 'minor', 'must_fix': [
            {'problem': '문제'*3000, 'fix': '수정'*3000, 'status': ['bad']} for _ in range(100)]})
        self.assertTrue(value['limited'])
        self.assertLess(len(json.dumps(value, ensure_ascii=False)), 30000)
        self.assertIn('해석하지 못했어요', json.dumps(report('draft', '{"broken":'), ensure_ascii=False))

    def test_critique_and_precheck_are_not_final_editorial_approval(self):
        self.assertEqual(outcome('critique', {'verdict': 'revise'})['state'], 'attention')
        self.assertEqual(outcome('precheck', {'issues': []})['state'], 'passed')
        self.assertEqual(outcome('precheck', {'issues': ['출처 부족']})['state'], 'blocked')
