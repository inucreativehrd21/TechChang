from django.test import SimpleTestCase

from office import pipeline as P
from office import quality as Q

REF = '\n\n## 참고 자료\n- 고용노동부, 2024 조사\n- OECD, Skills Outlook 2023\n- Gallup, 2024\n'


class QualityDetectorTests(SimpleTestCase):
    def test_figure_repetition_counts_prose_but_not_tables_or_references(self):
        body = ('응답자의 62%가 그렇다고 답했습니다. 62%는 높은 수치입니다. 다시 말해 62%입니다.\n\n'
                '| 항목 | 값 |\n|---|---|\n| 동의 | 62% |\n')
        self.assertEqual(Q.figure_repetition(body + REF), [('62%', 3)])
        self.assertEqual(Q.figure_repetition('62%입니다. 62%였습니다.\n| a | 62% |\n'), [])

    def test_precheck_flags_only_four_or_more_repeats(self):
        three = '44%입니다. 44%였습니다. 결국 44%입니다.' + REF
        four = three.replace('결국 44%입니다.', '결국 44%입니다. 또 44%입니다.')
        self.assertEqual(Q.precheck_issues(three), [])
        self.assertTrue(any('44%' in i for i in Q.precheck_issues(four)))

    def test_orphan_reference_to_missing_table(self):
        body = '아래 표에서 보듯 격차가 큽니다.' + REF
        self.assertEqual(Q.orphan_refs(body), ['아래 표'])
        with_table = '아래 표에서 보듯 격차가 큽니다.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n' + REF
        self.assertEqual(Q.orphan_refs(with_table), [])

    def test_title_overclaim_needs_assertive_title_and_hedged_body(self):
        hedged = ' '.join(['효과가 있을 수 있습니다.'] * 3 + ['자료가 있습니다.'])
        self.assertIsNotNone(Q.title_overclaim('교육은 반드시 바뀌어야 한다', hedged))
        self.assertIsNone(Q.title_overclaim('교육은 어떻게 바뀌는가', hedged))

    def test_source_count(self):
        self.assertEqual(Q.source_count('본문' + REF), 3)
        self.assertEqual(Q.source_count('참고 자료 없음'), 0)

    def test_recency_flags_stale_data_section_but_ignores_forecast_years(self):
        stale = ('리드\n\n## 숫자로 보는 현황\n2019년 조사에서 40%, 2030년 전망은 70%입니다.\n\n## 시사점\n- a'
                 + REF)
        r = Q.recency(stale, now=2026)
        self.assertEqual(r['data_latest'], 2019)       # 2030 전망치는 자료 시점이 아니다
        self.assertTrue(any('2019년' in i for i in Q.recency_issues(stale, now=2026)))
        fresh = stale.replace('2019년', '2025년')
        self.assertEqual(Q.recency_issues(fresh, now=2026), [])

    def test_recency_allows_classics_when_recent_sources_exist(self):
        refs = '\n\n## 참고 자료\n- Goodhart, 1975\n- OECD, 2025\n'
        self.assertEqual(Q.recency_issues('본문' + refs, now=2026), [])
        old_only = '\n\n## 참고 자료\n- Goodhart, 1975\n- OECD, 2018\n'
        issues = Q.recency_issues('본문' + old_only, now=2026)
        self.assertEqual(len(issues), 1)
        self.assertIn('2018', issues[0])

    def test_recency_rule_reaches_every_prompt(self):
        rule = P.recency_rule()
        self.assertIn('이후 자료부터', rule)
        self.assertIn(rule, P.writing_standard())
        for tpl in (P.BRIEF_PROMPT, P.METRICS_PROMPT, P.CHECK_PROMPT):
            self.assertIn('{recency}', tpl)
        self.assertIn('outdated', P.BAD_CLAIMS)

    def test_new_numeric_sentences_detects_changed_figures_only(self):
        old = '전체의 30%가 이탈했습니다. 맥락이 중요합니다.'
        same = '맥락이 중요합니다. 전체의 30%가 이탈했습니다.'
        changed = '전체의 35%가 이탈했습니다. 맥락이 중요합니다.'
        self.assertEqual(P.new_numeric_sentences(old, same), [])
        self.assertEqual(P.new_numeric_sentences(old, changed), ['전체의 35%가 이탈했습니다.'])


class DurationIsNotAFigureTests(SimpleTestCase):
    def test_months_are_not_counted_as_repeated_figures(self):
        from office.quality import figure_repetition
        text = '복귀 6개월 점검, 3~6개월 점검, 6개월 뒤, 6개월 안에, 6개월 동안 묻습니다. 지표는 6개입니다.'
        self.assertEqual(figure_repetition(text), [])

    def test_real_repetition_still_caught(self):
        from office.quality import figure_repetition
        self.assertTrue(figure_repetition('62% 62% 62% 62%'))


class MetaNotesTests(SimpleTestCase):
    """작성 과정 메모 — #36 끝에 '[운영자 확인 요청 — 발행 전 삭제]' 블록이 남아 매번 보류됐다."""

    def test_operator_notes_and_process_remarks_are_caught(self):
        for text in ('[운영자 확인 요청 — 발행 전 삭제]', '이 판을 정리한 환경에서는 jj를 실행하지 못해 싣지 못했습니다.',
                     '<!-- 편집 메모: 교체 -->', '완성 예제 저장소(링크는 게시 시 삽입)', 'TODO: 캡처'):
            self.assertTrue(Q.meta_notes(text), text)

    def test_honest_reader_facing_sentences_are_not_flagged(self):
        for text in ('국내 도입 사례는 공개 자료로 확인되지 않아, 문서에서 확인되는 흐름만 짚습니다.',
                     '```bash\n# TODO 는 코드 주석이라 괜찮습니다\n```'):
            self.assertEqual(Q.meta_notes(text), [], text)

    def test_numbered_reference_needs_that_numbered_title(self):
        self.assertEqual(Q.orphan_refs('| 기준 | 점수 |\n|---|---|\n| A | 1 |\n\n표 1과 대조하세요.'), ['표 1'])
        self.assertEqual(Q.orphan_refs('### 표 1. 점수\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n표 1과 대조하세요.'), [])


class StyleAuditIgnoresCodeTests(SimpleTestCase):
    def test_code_lines_are_not_counted_as_plain_style(self):
        from office.services import audit_style
        body = ('진단 스크립트를 돌려 보세요. 결과를 표와 대조하면 됩니다.\n\n'
                '```bash\necho "[ok] .gitattributes 없음"\necho "[!] 훅 있음"\n# 줄 수를 기록함\n```\n\n'
                '두 결과가 같으면 훅이 실행되지 않은 것입니다.\n')
        offenders, st = audit_style(body)
        self.assertEqual((st['plain'], offenders), (0, []))
