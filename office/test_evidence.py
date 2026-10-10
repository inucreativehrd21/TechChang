"""근거 묶음과 수치 잠금 — 원문 문장으로 확인한 수치만 본문에 남는다(office.evidence)."""
from django.test import SimpleTestCase

from office import evidence as E
from office import pipeline as P
from office import review_protocol as R

PACK = ('- 코칭 실무자 122,974명(2023년 대비 15% 증가) — 원문: "A record 122,974 coach practitioners worldwide '
        '(up 15% from 2023)." (https://coachingfederation.org/x)\n'
        '- 산업 수익 53.4억 달러 — 원문: "Industry revenue soared to $5.34 billion USD" (https://coachingfederation.org/x)\n'
        '- 수익 45.64억 달러 — 원문: "grew to $4.564 billion (USD)" (https://coachingfederation.org/y)\n'
        '- 실무자 10만 명 이상 — 원문: "surpasses the milestone of 100,000 practitioners" (https://coachingfederation.org/y)')


class NumberKeyTests(SimpleTestCase):
    def test_same_value_across_units_and_notation(self):
        self.assertEqual(E.key('45.64'), E.key('4.564'))           # 억 달러 ↔ billion
        self.assertEqual(E.key('53.4'), E.key('5.34'))
        self.assertEqual(E.key('122,974'), '122974')
        self.assertEqual(E.key('10'), E.key('100,000'))            # 만 ↔ thousand

    def test_quote_must_contain_the_claimed_number(self):
        self.assertTrue(E.quote_supports('산업 수익 53.4억 달러', 'Industry revenue soared to $5.34 billion'))
        self.assertFalse(E.quote_supports('응답 10,035건', 'insights from more than 10,000 coaches'))


class UnmatchedTests(SimpleTestCase):
    def test_memory_numbers_are_caught_and_sourced_ones_pass(self):
        body = ('ICF 2025년 판은 실무자를 122,974명으로 집계했고 수익은 53.4억 달러였습니다. '
                '조사는 14,591명이 응답했습니다.\n')
        self.assertEqual([n for n, _ in E.unmatched(body, PACK)], ['14,591'])

    def test_years_dates_figures_small_counts_and_derived_values_are_not_checked(self):
        body = ('2025년 9월 15일 공개된 표 1을 보면 2007, 2012, 2016년 조사에 이어 다섯 번째입니다. '
                '3개월 뒤 5점 척도로 잽니다. 불신이 신뢰보다 13%p 많고 약 2배입니다. '
                '필자 제안으로 30분을 리뷰에 씁니다.\n```python\nx = 9999\n```\n## 참고 자료\n- 2026, 1-18쪽 777\n')
        self.assertEqual(E.unmatched(body, PACK), [])

    def test_no_pack_means_no_check(self):
        self.assertEqual(E.unmatched('14,591명이 응답했습니다.', ''), [])

    def test_drop_sentences_removes_only_that_sentence_and_keeps_tables(self):
        body = ('앞 문장입니다. 조사는 14,591명이 응답했습니다. 뒤 문장입니다.\n\n'
                '| 지표 | 값 |\n|---|---|\n| 응답 | 14,591명 |\n')
        new, removed = E.drop_sentences(body, ['14,591'])
        self.assertEqual(removed, ['조사는 14,591명이 응답했습니다.'])
        self.assertIn('앞 문장입니다. 뒤 문장입니다.', new)
        self.assertIn('| 응답 | 14,591명 |', new)                  # 표는 사람이 보게 남긴다(자동 점검이 지적)


class GatherTests(SimpleTestCase):
    def test_claims_are_split_into_batches_and_unsupported_verified_is_downgraded(self):
        calls = []

        def ask_json(key, prompt, **kw):
            calls.append(prompt)
            claims = [ln.split('. ', 1)[1] for ln in prompt.split('[확인할 주장]\n')[1].split('\n\n')[0].splitlines()]
            out = []
            for c in claims:
                if '53.4' in c:
                    out.append({'claim': c, 'status': 'verified', 'value': '53.4억 달러',
                                'quote': 'Industry revenue soared to $5.34 billion', 'url': 'https://x.org/a'})
                else:      # 모델은 verified 라고 했지만 원문 문장에 값이 없다
                    out.append({'claim': c, 'status': 'verified', 'quote': 'more than 10,000 coaches',
                                'url': 'https://x.org/b'})
            return {'claims': out}

        claims = [{'claim': '산업 수익 53.4억 달러'}] + [{'claim': f'응답 {10_035 + i}건'} for i in range(5)]
        res = E.gather(claims, ask_json=ask_json)
        self.assertEqual(len(calls), 2)                              # 6개 → 4 + 2
        self.assertEqual([r['status'] for r in res], ['verified'] + ['unverifiable'] * 5)
        self.assertIn('53.4억 달러', E.pack_text(res))
        self.assertNotIn('10,035', E.pack_text(res))
        self.assertIn('https://x.org/a', res[0]['note'])            # 검증 원장은 note 의 URL 로 기록

    def test_failed_batch_becomes_unverifiable(self):
        def boom(*a, **k):
            raise RuntimeError('limit')
        res = E.gather([{'claim': 'a 1,234명'}], ask_json=boom)
        self.assertEqual(res[0]['status'], 'unverifiable')


class LockAndReviewTests(SimpleTestCase):
    def test_lock_only_removes_numbers_new_since_baseline(self):
        before = '예전부터 있던 14,591명 문장입니다.\n'
        after = before + '재작성이 들여온 10,035건 문장입니다.\n'
        new, removed = P.lock_numbers(after, PACK, baseline=before)
        self.assertEqual(removed, ['재작성이 들여온 10,035건 문장입니다.'])
        self.assertIn('14,591', new)

    def test_precheck_reports_loose_numbers_when_a_pack_exists(self):
        issues = P.precheck_draft('조사는 14,591명이 응답했습니다.', PACK)
        self.assertTrue(any('근거 묶음' in i and '14,591' in i for i in issues))

    def test_fix_instruction_with_unsourced_number_is_flagged(self):
        qa = R.normalize({'must_fix': [{'where': '표 1', 'problem': '응답 수 오류',
                                        'fix': '10,035건(89%)으로 바꾸세요', 'done_when': ''}]})
        self.assertEqual(R.flag_numbers(qa, PACK), 1)
        self.assertIn('원문 확인된 근거에 없습니다', qa['must_fix'][0]['fix'])

    def test_new_must_fix_on_unchanged_text_is_demoted_to_suggestion(self):
        prev = '표를 위에서 아래로 읽으면 간극이 보입니다. 다른 문장입니다.'
        cur = prev + ' 새 문장입니다.'
        previous = {'must_fix': [{'where': '도입부', 'problem': '장면이 없음', 'fix': '', 'done_when': ''}]}
        qa = R.normalize({'fatal': [], 'must_fix': [
            {'where': "현황 마지막 문단 '표를 위에서 아래로 읽으면 간극이 보입니다'", 'problem': '인과 비약', 'fix': 'x'},
            {'where': "'새 문장입니다'", 'problem': '근거 없음', 'fix': 'y'}]})
        demoted = R.demote_stale(qa, previous, prev, cur)
        self.assertEqual(len(demoted), 1)
        self.assertEqual([m['problem'] for m in qa['must_fix']], ['근거 없음'])   # 이번에 바뀐 곳은 남는다
        self.assertTrue(any('바뀌지 않은 곳' in s for s in qa['suggestions']))

    def test_fatal_review_keeps_all_must_fix(self):
        qa = R.normalize({'fatal': ['unverified_data'], 'must_fix': [
            {'where': "'표를 위에서 아래로 읽으면 간극이 보입니다'", 'problem': 'p', 'fix': 'f'}]})
        prev = '표를 위에서 아래로 읽으면 간극이 보입니다.'
        self.assertEqual(R.demote_stale(qa, {'must_fix': []}, prev, prev), [])


class SeriesStatsOnlyTests(SimpleTestCase):
    def test_series_lock_ignores_versions_ports_and_status_codes(self):
        body = ('Django 5.2 와 Python 3.12 로 8000번 포트에서 띄우면 404 가 납니다. '
                '설문에서 개발자 84%가 AI 를 씁니다. 응답자는 49,009명이었습니다.\n')
        loose = [n for n, _ in E.unmatched(body, PACK, stats_only=True)]
        self.assertEqual(loose, ['84', '49,009'])                   # 통계 단위가 붙은 수치만
        self.assertIn('5.2', [n for n, _ in E.unmatched(body, PACK)])  # 칼럼 모드라면 버전도 걸린다
