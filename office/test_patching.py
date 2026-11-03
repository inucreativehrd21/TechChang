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


class UnsupportedEditTests(SimpleTestCase):
    """근거 없는 새 수치·단정을 들이는 편집은 거절한다(2026-10-31 B 파일럿: 수정이 매번 새 결함을 만듦)."""
    PACK = '- 응답자 49,009명 — 원문: "49,009 respondents" (https://survey.example.org/2026)'

    def _patch(self, edits):
        return PT.patch_revise('coding', '제목', DOC, ['고치세요'], who='심사에서', pack=self.PACK,
                               ask_json=lambda *a, **k: {'edits': edits, 'title': ''})

    def test_new_number_outside_pack_is_rejected_but_others_apply(self):
        subject, content, ok, why = self._patch([
            {'find': '대안 없이 막힙니다.', 'replace': '개발자 3,812명이 대안 없이 막혔습니다.'},   # 근거 없음 → 거절
            {'find': '셋째 문단입니다.', 'replace': '셋째 문단에는 응답자 49,009명을 적습니다.'}])  # 묶음에 있음
        self.assertTrue(ok)
        self.assertIn('1건 거절', why)
        self.assertIn('대안 없이 막힙니다.', content)
        self.assertIn('49,009명', content)

    def test_numbers_already_in_the_sentence_and_new_absolutes(self):
        keep = PT.unsupported({'find': '이미 검증된 수치 45%가 들어 있습니다.',
                               'replace': '이미 검증된 수치 45%를 그대로 둡니다.'}, self.PACK)
        self.assertEqual(keep, [])
        over = PT.unsupported({'find': '셋째 문단입니다.', 'replace': '이 방법이 항상 가장 빠릅니다.'}, self.PACK)
        self.assertTrue(over and over[0].startswith('단정'))

    def test_all_blocked_keeps_original(self):
        subject, content, ok, why = self._patch([{'find': '셋째 문단입니다.', 'replace': '매출이 1,234억 원 늘었습니다.'}])
        self.assertFalse(ok)
        self.assertEqual(content, DOC)
        self.assertIn('거절', why)

    def test_without_pack_nothing_is_screened(self):
        subject, content, ok, why = PT.patch_revise(
            'coding', '제목', DOC, ['고치세요'], who='심사에서',
            ask_json=lambda *a, **k: {'edits': [{'find': '셋째 문단입니다.', 'replace': '매출이 1,234억 원입니다.'}]})
        self.assertTrue(ok)


class CodeBreakingEditTests(SimpleTestCase):
    def test_edit_that_breaks_a_code_block_is_reverted(self):
        doc = DOC + '\n```python\nclass T(TestCase):\n    def test_a(self):\n        pass\n```\n'
        edits = [{'find': '    def test_a(self):\n        pass', 'replace': '    def test_a(self):\n      x = 1\n        pass'},
                 {'find': '셋째 문단입니다.', 'replace': '셋째 문단을 고쳤습니다.'}]
        subject, content, ok, why = PT.patch_revise('coding', '제목', doc, ['고치세요'], who='심사에서', pack='',
                                                    ask_json=lambda *a, **k: {'edits': edits})
        self.assertTrue(ok)
        self.assertIn('코드 블록을 깨뜨림 ← 「def test_a(self): pass」', why)      # 무엇이 왜 막혔는지 남긴다
        self.assertIn('        pass\n```', content)
        self.assertIn('셋째 문단을 고쳤습니다.', content)


class HedgeEditTests(SimpleTestCase):
    """근거 없는 문장을 '필자의 추론'으로 약하게 바꾸는 편집은 고친 것이 아니다(2026-11-02 atomic 2차)."""
    def test_new_hedge_is_rejected_but_citation_or_deletion_passes(self):
        find = '콜백이 실패하면 메일 작업은 기록 없이 사라집니다.'
        for repl in ('콜백이 실패하면 메일 작업이 기록 없이 사라질 수 있다는 것이 필자의 추론입니다.',
                     '콜백이 실패하면 기록 없이 사라지는 것으로 보입니다.'):
            with self.subTest(repl=repl):
                self.assertTrue(any(x.startswith('추론으로 약화') for x in PT.unsupported({'find': find, 'replace': repl}, '')))
        cite = ('공식 문서는 robust=True 이면 콜백 예외를 django.db.backends.base 로거에 기록한다고 설명합니다'
                '("logged on the django.db.backends.base logger").')
        self.assertEqual(PT.unsupported({'find': find, 'replace': cite}, ''), [])
        self.assertEqual(PT.unsupported({'find': find, 'replace': ''}, ''), [])

    def test_hedge_already_in_the_sentence_is_not_new(self):
        find = '이것은 필자의 해석입니다. 다만 표를 다시 그렸습니다.'
        self.assertEqual(PT.unsupported({'find': find, 'replace': '이것은 필자의 해석입니다. 표를 다시 그렸습니다.'}, ''), [])


class HedgeInsertionTests(SimpleTestCase):
    """2026-11-03 atomic 5차 — 편집장 요구로 트레이드오프 절을 덧붙인 편집이 '필자의 판단' 때문에 거절됐다."""
    FIND = '커밋 전후 시점을 실제로 관찰해야 할 때만 `TransactionTestCase`를 씁니다.'

    def test_appending_a_labelled_opinion_is_allowed(self):
        repl = self.FIND + '\n\n### 메일이 실패하면 결과가 뒤집힌다\n\n필자의 판단으로는 주문을 살리는 쪽이 낫습니다.'
        self.assertEqual(PT.unsupported({'find': self.FIND, 'replace': repl}, ''), [])

    def test_rewriting_the_sentence_into_a_guess_is_still_rejected(self):
        repl = '커밋 전후를 관찰할 때 TransactionTestCase를 쓰는 것이 필자의 추론입니다.'
        self.assertTrue(PT.unsupported({'find': self.FIND, 'replace': repl}, ''))
