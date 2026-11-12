from django.test import SimpleTestCase
from office import evidence as E
from office import pipeline as P
from office.services import chart_markdown, chart_number, audit_chart
from office.lab_metrics import summarize


class MarkdownNumberLockTests(SimpleTestCase):
    def test_image_alt_sentence_boundary_never_leaves_a_half_image(self):
        image='![그림 1. 총급여 943.3조 원](/media/columns/a.png)'
        result, removed=E.drop_sentences(image,['943.3'])
        self.assertEqual(result,'')
        self.assertEqual(removed,[image])

    def test_links_nested_url_parentheses_and_inline_code_stay_atomic(self):
        for middle in ('[자료 1. 응답 943.3조](https://example.org/a(b))',
                       '[자료 1. 응답 943.3조][source]', '`자료 1. 응답 943.3조`'):
            with self.subTest(middle=middle):
                text='첫 문장입니다. '+middle+' 내용입니다. 마지막 문장입니다.'
                result, removed=E.drop_sentences(text,['943.3'])
                self.assertEqual(result,'첫 문장입니다. 마지막 문장입니다.')
                self.assertEqual(removed,[middle+' 내용입니다.'])

    def test_only_invalid_figure_is_removed_with_its_caption(self):
        bad='![그림 1. 총급여 943.3조 원](/media/columns/bad.png)'
        good='![그림 2. 응답 75%](/media/columns/good.png)'
        text=('도입 문장입니다.\n\n[//]: # (tc-figure)\n\n'+bad+'\n\n**그림 1. 잘못된 도판**\n\n'
              '이 캡션은 해당 도판에 딸려 있습니다.\n\n*단위: 조 원. 출처: 기관.*\n\n'
              '보존해야 하는 중간 문장입니다.\n\n'+good+'\n\n**그림 2. 검증된 도판**\n\n'
              '유효한 캡션입니다.\n\n## 작성자 표\n\n| 기준 | 설명 |\n|---|---|\n| 역할 | 보존 |\n')
        result, removed=P.lock_numbers(text,'원문에서 확인한 응답은 75%입니다.')
        self.assertNotIn('bad.png',result)
        self.assertNotIn('잘못된 도판',result)
        self.assertNotIn('해당 도판에 딸려',result)
        self.assertIn(good,result)
        self.assertIn('유효한 캡션',result)
        self.assertIn('보존해야 하는 중간 문장',result)
        self.assertIn('| 역할 | 보존 |',result)
        self.assertEqual(removed,[bad])

    def test_adjacent_figures_without_markers_do_not_merge(self):
        bad='![그림 1. 수치 943.3조](/media/bad.png)'
        good='![그림 2. 수치 75%](/media/good.png)'
        text=bad+'\n\n**그림 1. 첫 도판**\n\n첫 캡션입니다.\n\n'+good+'\n\n**그림 2. 두 번째**\n\n두 번째 캡션입니다.'
        result=P.strip_visual_block(text,only_images={bad})
        self.assertNotIn(bad,result)
        self.assertIn(good,result)
        self.assertIn('두 번째 캡션',result)

    def test_broken_legacy_image_is_cleaned_before_regeneration(self):
        broken='![그림 1.\n\n**그림 1. 옛 차트**\n\n옛 캡션입니다.\n\n*단위: 조 원. 출처: 기관.*\n\n## 다음 절\n\n본문을 유지합니다.'
        self.assertFalse(P.has_visual(broken))
        result=P.strip_visual_block(broken)
        self.assertNotIn('![그림',result)
        self.assertNotIn('옛 캡션',result)
        self.assertIn('본문을 유지',result)

    def test_code_blocks_are_preserved_when_visuals_are_removed(self):
        code='```python\ntext = "![그림 1. 예시입니다."\n\nprint(text)\n```'
        self.assertIn(code,P.strip_visual_block(code))


class ChartNumberTests(SimpleTestCase):
    def test_numbers_are_not_rounded_to_six_digits_or_shown_in_exponents(self):
        for value, expected in [(943257648,'943,257,648'),(553298294.0,'553,298,294'),
                                (0.0000001234,'0.0000001234'),(53.4,'53.4')]:
            self.assertEqual(chart_number(value),expected)
        spec={'title':'연말정산 비교','labels':['총급여','과세표준','결정세액'],'unit':'백만 원',
              'series':[{'name':'규모','values':[943257648,553298294,65160526]}]}
        markdown=chart_markdown('columns/test.png',spec,'공제액을 세금과 구분해서 읽습니다.')
        self.assertIn('943,257,648백만 원',markdown)
        self.assertNotIn('e+08',markdown)
        body='총급여 943,257,648백만 원, 과세표준 553,298,294백만 원, 결정세액 65,160,526백만 원입니다.'
        errors,*_=audit_chart(spec,body,'columns/test.png','공제액을 세금과 구분해서 읽습니다.')
        self.assertFalse(any('본문에 없습니다' in e for e in errors))

    def test_value_matching_cannot_succeed_by_substring(self):
        spec={'title':'비교','labels':['a','b','c'],'series':[{'values':[40,52,75]}], 'unit':'%'}
        errors,*_=audit_chart(spec,'400%와 52%, 75%입니다.','x.png','비교 가능한 수치를 살펴봅니다.')
        self.assertTrue(any('40' in e and '본문에 없습니다' in e for e in errors))


class RetainedReviewMetricsTests(SimpleTestCase):
    def test_actual_review_in_retained_decision_is_counted_without_qualifying(self):
        rows=[{'run_id':'r','seq':1,'stage':'revision_decision','calls':[{'input_tokens':10,'output_tokens':2}],
               'output':{'status':'retained','review':{'score':88,'verdict':'accept','fatal':[]}}}]
        run=summarize(rows)['runs'][0]
        self.assertEqual(run['reviews'],1)
        self.assertTrue(run['reached_review'])
        self.assertEqual(run['last_score'],88)
        self.assertFalse(run['final_pass'])
        rows.append({'run_id':'r','seq':2,'stage':'review','output':{'score':88,'verdict':'accept'}})
        self.assertEqual(summarize(rows)['runs'][0]['reviews'],1)
