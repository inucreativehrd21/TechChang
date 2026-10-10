"""패치식 수정·필수 수정 규약 — 지적받은 곳만 고치고, 재심은 직전 필수 수정부터 본다."""
from unittest import mock

from django.test import SimpleTestCase

from office import patching as PT
from office import review_protocol as R

DOC = ('첫 문단입니다. 이미 검증된 수치 45%가 들어 있습니다.\n\n'
       '둘째 문단은 과장이 있습니다. 대안 없이 막힙니다.\n\n'
       '셋째 문단입니다.\n')


class ApplyEditsTests(SimpleTestCase):
    def test_only_unique_matches_are_applied(self):
        out, applied, failed = PT.apply_edits(DOC, [
            {'find': '대안 없이 막힙니다.', 'replace': '공식 문서상 대안 안내가 없습니다.'},
            {'find': '문단', 'replace': 'X'},                          # 여러 곳과 일치 → 실패
            {'find': '원고에 없는 문장입니다.', 'replace': 'Y'}])      # 없음 → 실패
        self.assertEqual((applied, len(failed)), (1, 2))
        self.assertIn('공식 문서상 대안 안내가 없습니다.', out)
        self.assertIn('이미 검증된 수치 45%가 들어 있습니다.', out)     # 나머지는 그대로

    def test_patch_keeps_everything_else_byte_for_byte(self):
        res = {'edits': [{'find': '둘째 문단은 과장이 있습니다. 대안 없이 막힙니다.',
                          'replace': '둘째 문단은 한정했습니다. 공식 문서상 대안 안내가 없습니다.'}], 'title': ''}
        subject, content, ok, why = PT.patch_revise('coding', '제목', DOC, ['과장 한정'], who='심사에서',
                                                    ask_json=lambda *a, **k: res)
        self.assertTrue(ok)
        self.assertEqual(content.replace('둘째 문단은 한정했습니다. 공식 문서상 대안 안내가 없습니다.', ''),
                         DOC.replace('둘째 문단은 과장이 있습니다. 대안 없이 막힙니다.', ''))
        self.assertEqual(subject, '제목')

    def test_mostly_unmatched_patch_falls_back(self):
        res = {'edits': [{'find': '없는 문장 하나', 'replace': 'a'}, {'find': '없는 문장 둘', 'replace': 'b'},
                         {'find': '셋째 문단입니다.', 'replace': '셋째.'}]}
        _s, content, ok, why = PT.patch_revise('coding', '제목', DOC, ['x'], who='', ask_json=lambda *a, **k: res)
        self.assertFalse(ok)
        self.assertEqual(content, DOC)                                    # 실패하면 원고는 그대로
        self.assertIn('일치하지 않음', why)


class ReviewProtocolTests(SimpleTestCase):
    def test_must_fix_and_suggestions_are_separated(self):
        qa = R.normalize({'must_fix': [{'where': '리드', 'problem': '과장', 'fix': '한정', 'done_when': '단정 없음'}],
                          'suggestions': ['사례 하나 더']})
        self.assertEqual(R.revision_notes(qa), ['[리드] 과장 → 한정 (완료 기준: 단정 없음)'])
        self.assertEqual(qa['issues'][-1], '(제안) 사례 하나 더')            # 제안은 재작성으로 넘기지 않는다

    def test_old_style_review_still_works(self):
        qa = R.normalize({'issues': ['표 1이 없음', '도입이 약함']})
        self.assertEqual(R.revision_notes(qa), ['표 1이 없음', '도입이 약함'])

    def test_rereview_is_told_to_judge_previous_must_fix_first(self):
        block = R.previous_block({'must_fix': [{'where': '표 1', 'problem': '없음', 'done_when': '표 실림'}]})
        self.assertIn('직전 심사의 필수 수정', block)
        self.assertIn('"resolved"', block)
        self.assertIn('suggestions 로만', block)
        self.assertEqual(R.previous_block(None), '')
