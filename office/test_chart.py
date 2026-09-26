"""차트 렌더링 회귀 테스트.

배경: 긴 한글 항목명 7개를 세로 막대에 그려 x축 라벨이 전부 겹쳐 읽을 수 없는
차트가 칼럼에 실렸다(2026-09-26). 항목명이 길면 가로 막대로 돌리고, 계열이 하나면
범례를 빼고, 사이트와 같은 Pretendard 를 쓴다.
"""
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from office.services import _wrap_label, effective_chart_type, render_chart

LONG = ['Copilot 보안취약점 포함률', 'GPT 오답률을 그럴듯하다고 판별', 'METR 실제 작업시간 증가',
        'AI 호의적 응답', 'AI 정확성 신뢰 응답', 'AI 매우 신뢰 응답']
SHORT = ['1분기', '2분기', '3분기', '4분기']


class WrapLabelTests(TestCase):
    def test_short_label_is_untouched(self):
        self.assertEqual(_wrap_label('AI 호의적 응답', 18), 'AI 호의적 응답')

    def test_long_label_breaks_into_two_lines(self):
        wrapped = _wrap_label('GPT 오답률을 그럴듯하다고 판별한 비율', 10)
        self.assertEqual(wrapped.count('\n'), 1)
        self.assertTrue(all(len(line) <= 10 for line in wrapped.split('\n')))

    def test_very_long_label_is_elided(self):
        self.assertTrue(_wrap_label('가' * 60, 10).endswith('…'))


class ChartTypeTests(TestCase):
    """세로 막대에서 겹칠 항목명은 가로 막대로 돌아가야 한다."""

    def test_long_korean_labels_become_horizontal(self):
        self.assertEqual(effective_chart_type('bar', LONG), 'hbar')

    def test_many_medium_labels_become_horizontal(self):
        """6자를 넘는 이름이 5개 이상이면 세로로는 비좁다."""
        self.assertEqual(effective_chart_type('bar', ['상반기 총매출', '하반기 총매출', '전년 대비율',
                                                      '목표 달성률', '업계 평균치']), 'hbar')

    def test_a_few_medium_labels_stay_vertical(self):
        self.assertEqual(effective_chart_type('bar', ['상반기 매출', '하반기 매출', '전년 대비']), 'bar')

    def test_short_labels_stay_vertical(self):
        self.assertEqual(effective_chart_type('bar', SHORT), 'bar')
        self.assertEqual(effective_chart_type('bar', ['2023', '2024', '2025']), 'bar')

    def test_explicit_type_is_respected(self):
        self.assertEqual(effective_chart_type('line', LONG), 'line')
        self.assertEqual(effective_chart_type('hbar', SHORT), 'hbar')


class RenderChartTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _render(self, spec, stem='t'):
        with override_settings(MEDIA_ROOT=self.tmp):
            return render_chart(spec, stem)

    def test_long_labels_produce_a_readable_file(self):
        rel, err = self._render({
            'type': 'bar', 'title': '비교', 'labels': LONG, 'unit': '%',
            'series': [{'name': '비율', 'values': [40, 52, 39, 19, 72, 43]}]})
        self.assertEqual(err, '')
        self.assertTrue((Path(self.tmp) / rel).exists())

    def test_mismatched_value_count_is_rejected_with_a_reason(self):
        rel, err = self._render({'type': 'bar', 'labels': SHORT,
                                 'series': [{'name': 'v', 'values': [1, 2]}]})
        self.assertIsNone(rel)
        self.assertIn('개수', err)

    def test_non_numeric_values_are_rejected_with_a_reason(self):
        rel, err = self._render({'type': 'bar', 'labels': SHORT,
                                 'series': [{'name': 'v', 'values': [1, 'N/A', 3, 4]}]})
        self.assertIsNone(rel)
        self.assertIn('숫자', err)

    def test_empty_spec_is_rejected(self):
        rel, err = self._render({'type': 'bar', 'labels': [], 'series': []})
        self.assertIsNone(rel)
        self.assertTrue(err)

    def test_line_and_hbar_types_render(self):
        for kind in ('line', 'hbar'):
            rel, err = self._render({'type': kind, 'title': kind, 'labels': SHORT, 'unit': '%',
                                     'series': [{'name': 'v', 'values': [1, 2, 3, 4]}]}, kind)
            self.assertEqual(err, '', kind)
            self.assertTrue((Path(self.tmp) / rel).exists(), kind)


COLUMN_BODY = """## 숫자로 보는 현황

본문 설명 문단입니다.

![AI 코딩 도구 관련 주요 통계 비교](/media/columns/20260926_coding_010402.png)

**AI 코딩 도구 관련 주요 통계 비교** (단위: %)

| 항목 | 비율(%) |
|---|---|
| Copilot 보안취약점 포함률 | 40 |
| ChatGPT 오답률 | 52 |
| SO 매우 신뢰 응답 | 3 |

*출처: NYU·Calgary 'Asleep at the Keyboard', Stack Overflow 2024 Developer Survey*
"""


class ExtractSpecTests(TestCase):
    """발행된 칼럼 본문에서 차트 spec 복원 — API 없이 다시 그리기 위한 경로."""

    def test_spec_is_rebuilt_from_the_table(self):
        from office.management.commands.redraw_chart import extract_spec

        spec, path = extract_spec(COLUMN_BODY)
        self.assertEqual(path, 'columns/20260926_coding_010402.png')
        self.assertEqual(spec['title'], 'AI 코딩 도구 관련 주요 통계 비교')
        self.assertEqual(spec['labels'],
                         ['Copilot 보안취약점 포함률', 'ChatGPT 오답률', 'SO 매우 신뢰 응답'])
        self.assertEqual(spec['series'][0]['values'], [40, 52, 3])
        self.assertEqual(spec['unit'], '%')
        self.assertIn('Stack Overflow', spec['source'])

    def test_separator_row_is_not_read_as_data(self):
        from office.management.commands.redraw_chart import extract_spec

        spec, _ = extract_spec(COLUMN_BODY)
        self.assertNotIn('---', spec['labels'])

    def test_multi_series_table(self):
        from office.management.commands.redraw_chart import extract_spec

        body = COLUMN_BODY.replace('| 항목 | 비율(%) |', '| 항목 | 대기업 | 중소기업 |') \
                          .replace('|---|---|', '|---|---|---|') \
                          .replace('| Copilot 보안취약점 포함률 | 40 |', '| 항목1 | 40 | 12 |') \
                          .replace('| ChatGPT 오답률 | 52 |', '| 항목2 | 52 | 25 |') \
                          .replace('| SO 매우 신뢰 응답 | 3 |', '| 항목3 | 3 | 9 |')
        spec, _ = extract_spec(body)
        self.assertEqual([s['name'] for s in spec['series']], ['대기업', '중소기업'])
        self.assertEqual(spec['series'][1]['values'], [12, 25, 9])

    def test_body_without_a_chart_is_reported(self):
        from office.management.commands.redraw_chart import extract_spec

        spec, reason = extract_spec('## 머리말\n\n표도 그림도 없는 본문.')
        self.assertIsNone(spec)
        self.assertTrue(reason)


class AuditChartTests(TestCase):
    """검수 단계가 차트 내용을 판단할 수 있게 하는 자동 점검."""

    BODY = ('본문에 40%, 52%, 3% 수치가 있습니다. 출처는 Stack Overflow 2024 입니다.')
    OK_SPEC = {'type': 'bar', 'title': '비교', 'labels': ['가', '나', '다'], 'unit': '%',
               'source': 'Stack Overflow 2024', 'series': [{'name': '비율', 'values': [40, 52, 3]}]}

    def _audit(self, spec=None, body=None, chart_rel='columns/x.png'):
        from office.services import audit_chart
        return audit_chart(spec or dict(self.OK_SPEC), body if body is not None else self.BODY, chart_rel)

    def test_clean_chart_has_no_findings(self):
        errors, warns, report = self._audit()
        self.assertEqual(errors, [])
        self.assertEqual(warns, [])
        self.assertIn('이상 없음', report)

    def test_report_lists_actual_labels_and_values(self):
        """검수자가 '차트가 있다'가 아니라 실제 내용을 보고 판단할 수 있어야 한다."""
        _, _, report = self._audit()
        self.assertIn('가=40', report)
        self.assertIn('다=3', report)
        self.assertIn('Stack Overflow 2024', report)

    def test_values_absent_from_the_body_are_fatal(self):
        spec = dict(self.OK_SPEC, series=[{'name': '비율', 'values': [40, 52, 99]}])
        errors, _, _ = self._audit(spec)
        self.assertTrue(any('본문에 없습니다' in e for e in errors))

    def test_identical_values_are_fatal(self):
        spec = dict(self.OK_SPEC, series=[{'name': '비율', 'values': [40, 40, 40]}])
        errors, _, _ = self._audit(spec, body='40% 뿐입니다')
        self.assertTrue(any('아무것도 보여' in e for e in errors))

    def test_too_few_categories_is_fatal(self):
        spec = dict(self.OK_SPEC, labels=['가', '나'], series=[{'name': '비율', 'values': [40, 52]}])
        errors, _, _ = self._audit(spec)
        self.assertTrue(any('비교 항목' in e for e in errors))

    def test_duplicate_labels_are_fatal(self):
        spec = dict(self.OK_SPEC, labels=['가', '가', '다'])
        errors, _, _ = self._audit(spec)
        self.assertTrue(any('중복' in e for e in errors))

    def test_missing_unit_and_source_are_warnings_not_fatal(self):
        spec = dict(self.OK_SPEC, unit='', source='')
        errors, warns, _ = self._audit(spec)
        self.assertEqual(errors, [])
        self.assertEqual(len(warns), 2)

    def test_extreme_value_range_is_a_warning(self):
        spec = dict(self.OK_SPEC, labels=['가', '나', '다'],
                    series=[{'name': '비율', 'values': [1, 40, 52]}])
        _, warns, _ = self._audit(spec, body='1, 40, 52')
        self.assertEqual(warns, [])          # 52배는 허용 범위
        spec2 = dict(self.OK_SPEC, series=[{'name': '비율', 'values': [1, 40, 5200]}])
        _, warns2, _ = self._audit(spec2, body='1, 40, 5200')
        self.assertTrue(any('차이가 너무' in w for w in warns2))


class ReviewUsesChartReportTests(TestCase):
    """자동 점검에서 치명 결함이 나오면 모델 점수와 무관하게 보류되어야 한다."""

    def test_fatal_chart_finding_forces_visual_broken(self):
        from unittest.mock import patch

        from office import pipeline as P

        content = '## 숫자로 보는 현황\n\n' + ('내용 ' * 1200) + '\n\n| 항목 | 값 |\n|---|---|\n| 가 | 1 |\n'
        fake_qa = {'scores': {k: 5 for k in P.RUBRIC}, 'fatal': [], 'issues': [], 'notes': ''}
        report = '차트: x\n자동 점검 — 치명: 차트 수치 99이(가) 본문에 없습니다'
        with patch.object(P, 'ask_agent_json', return_value=fake_qa):
            qa = P.step_review('제목', content, {'verdict': 'ok'}, 'columns/x.png', report)
        self.assertIn('visual_broken', qa['fatal'])
        self.assertEqual(qa['verdict'], 'major')
        self.assertTrue(any('차트 결함' in i for i in qa['issues']))

    def test_clean_report_does_not_add_fatal(self):
        from unittest.mock import patch

        from office import pipeline as P

        content = '## 숫자로 보는 현황\n\n' + ('내용 ' * 1200) + '\n\n| 항목 | 값 |\n|---|---|\n| 가 | 1 |\n'
        fake_qa = {'scores': {k: 5 for k in P.RUBRIC}, 'fatal': [], 'issues': [], 'notes': ''}
        with patch.object(P, 'ask_agent_json', return_value=fake_qa):
            qa = P.step_review('제목', content, {'verdict': 'ok'}, 'columns/x.png', '자동 점검: 이상 없음')
        self.assertNotIn('visual_broken', qa['fatal'])


class ChartFontTests(TestCase):
    def test_pretendard_ttf_is_available_for_matplotlib(self):
        """matplotlib 은 woff2 를 못 읽는다 — TTF 인스턴스가 저장소에 있어야 한다."""
        from django.conf import settings

        fonts = Path(settings.BASE_DIR) / 'static' / 'fonts'
        self.assertTrue((fonts / 'Pretendard-Regular.ttf').exists())
        self.assertTrue((fonts / 'Pretendard-Bold.ttf').exists())

    def test_chart_font_resolves_to_pretendard(self):
        from matplotlib import font_manager

        from office.services import _chart_font
        self.assertIn('Pretendard', _chart_font(font_manager))
