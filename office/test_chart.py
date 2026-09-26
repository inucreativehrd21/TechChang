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
