"""장르별 구조·단정 점검·조기 보류·Codex 토큰 상한 (2026-10-31 B 파일럿 후속)."""
from unittest import mock

from django.test import SimpleTestCase

from office import genres as G
from office import pipeline as P
from office import quality
from office.run_context import RunBudgetExceeded, RunContext

TABLE = ('| 관계 | select_related | prefetch_related | 출처 |\n|---|---|---|---|\n'
         '| 정방향 FK | ✓ | ✓ | 공식 문서 QuerySet API |\n| 역방향 FK | ✗ | ✓ | 공식 문서 QuerySet API |\n'
         '| ManyToMany | ✗ | ✓ | 공식 문서 QuerySet API |\n')


def tutorial(body_extra=''):
    sections = ['어디서 막히나', '판단 기준', '동작 원리', '실행 예제', '자주 하는 실수', '체크리스트', '맺음말', '참고 자료']
    parts = ['리드 문단입니다.']
    for s in sections:
        parts.append(f'## {s}\n\n' + (TABLE if s == '판단 기준' else '설명합니다. ' * 60))
    return '\n\n'.join(parts) + body_extra


class GenreChoiceTests(SimpleTestCase):
    def setUp(self):
        self.genre_switch = mock.patch.dict('os.environ', {'OFFICE_GENRES': '1'})
        self.genre_switch.start()
        self.addCleanup(self.genre_switch.stop)

    def test_disabled_defaults_to_existing_data_structure(self):
        with mock.patch.dict('os.environ', {'OFFICE_GENRES': '0'}):
            self.assertEqual(G.genre_for('coding', {'genre': 'tutorial'}), 'data')
            self.assertEqual(G.genre_for('coding', content='## 판단 기준\n표'), 'data')

    def test_priority_brief_then_written_sections_then_topic(self):
        self.assertEqual(G.genre_for('coding'), 'tutorial')
        self.assertEqual(G.genre_for('hrd'), 'data')
        self.assertEqual(G.genre_for('coding', {'genre': 'data'}), 'data')
        self.assertEqual(G.genre_for('coding', {'genre': '모름'}), 'tutorial')
        # 기획서가 없는 재심·운영자 수정은 원고가 따르는 틀을 유지한다(옛 코딩 칼럼은 데이터 틀)
        self.assertEqual(G.genre_for('coding', content='## 숫자로 보는 현황\n표'), 'data')
        self.assertEqual(G.genre_for(content='## 판단 기준\n표'), 'tutorial')

    def test_standard_and_rubric_follow_genre(self):
        std = P.writing_standard(genre='tutorial')
        self.assertIn('어디서 막히나 / 판단 기준', std)
        self.assertNotIn('왜 지금인가', std)
        self.assertIn('왜 지금인가 / 숫자로 보는 현황', P.writing_standard(genre='data'))
        self.assertIn('실행 예제', P.rubric_text('tutorial'))
        self.assertIn('통계를 요구하지 마세요', P.rubric_text('tutorial'))
        self.assertIn('숫자로 보는 현황', G.structure('data'))
        self.assertIn('## 실행 예제', G.structure('tutorial'))


class TutorialPrecheckTests(SimpleTestCase):
    def test_tutorial_passes_without_data_sections(self):
        issues = P.precheck_draft(tutorial(), genre='tutorial')
        self.assertFalse([i for i in issues if '필수 섹션' in i or '판단 기준' in i], issues)

    def test_tutorial_needs_sourced_table_not_statistics(self):
        body = tutorial().replace(TABLE, '개발자 84%, 응답자 49,009명, 기업 12곳이 썼어요.')
        issues = P.precheck_draft(body, genre='tutorial')
        self.assertTrue(any('"판단 기준"에 공식 문서' in i for i in issues), issues)

    def test_data_genre_still_requires_data_sections(self):
        issues = P.precheck_draft(tutorial(), genre='data')
        self.assertTrue(any('필수 섹션' in i and '숫자로 보는 현황' in i for i in issues))


class OverclaimTests(SimpleTestCase):
    def test_flags_absolutes_and_generalizations_from_pilots(self):
        body = ('정방향 FK와 양방향 OneToOne의 결과는 항상 객체 하나입니다. '
                '흔한 소개글은 N+1이 생기면 두 API 중 하나를 붙이라는 설명에서 끝납니다. '
                '공식 예제를 손으로 재현하는 것이 가장 빠른 방법입니다. 단일값 관계는 select_related를 씁니다.\n')
        self.assertEqual(len(quality.overclaims(body)), 3)
        self.assertTrue(any('단정·일반화 3문장' in i for i in quality.precheck_issues(body)))

    def test_advice_negation_code_and_quotes_are_not_claims(self):
        body = ('배포 전에는 반드시 쿼리 수를 확인하세요. 항상 그런 것은 아닙니다.\n'
                '> 공식 문서는 항상 프로파일링하라고 권합니다.\n'
                '```python\n# 항상 JOIN\n```\n## 가장 흔한 실수\n')
        self.assertEqual(quality.overclaims(body), [])


class EarlyHoldTests(SimpleTestCase):
    def test_holds_when_revision_cannot_converge(self):
        bad = [{'status': 'wrong'}] * 6
        self.assertIn('6건', P.early_hold({'score': 75}, {'claims': bad}))
        self.assertIn('60점', P.early_hold({'score': 60}, {'claims': []}))
        self.assertEqual(P.early_hold({'score': 70}, {'claims': bad[:5] + [{'status': 'verified'}]}), '')


class CodexBudgetTests(SimpleTestCase):
    def test_reserve_stops_when_codex_input_reaches_cap(self):
        ctx = RunContext(dry=True, max_codex_tokens=1000)
        ctx.active_calls = [{'direct_provider': 'codex', 'input_tokens': 600},
                            {'direct_provider': 'claude', 'input_tokens': 5000}]
        ctx.reserve()                                   # Claude 호출은 세지 않는다
        ctx.active_calls.append({'backend': 'codex_cli', 'input_tokens': 400})
        with self.assertRaises(RunBudgetExceeded):
            ctx.reserve()

    def test_zero_disables_cap(self):
        ctx = RunContext(dry=True, max_codex_tokens=0)
        ctx.active_calls = [{'direct_provider': 'codex', 'input_tokens': 10 ** 9}]
        ctx.reserve()
