"""초안 자동 점검 게이트와 집필 기준 전달 — 첫 원고 품질을 떠받치는 장치들.

배경: 한 번에 통과한 칼럼이 한 편도 없었다. 원인은 집필자가 심사 기준을 모른 채 쓰고,
기계로 판별되는 결함(분량·문체·섹션·수치)이 팩트체크·평론·편집 심사를 다 거친 뒤에야
드러난 데 있다. 기준은 집필 단계에 주고, 기계 검사는 초안 직후에 끝낸다.
"""
from unittest.mock import patch

from django.test import TestCase

from office import pipeline as P

BODY_OK = (
    '리드 문단입니다. ' * 4 + '\n\n'
    '## 왜 지금인가\n\n' + ('지금 이 문제를 다뤄야 하는 이유를 설명합니다. ' * 40) + '\n\n'
    '## 숫자로 보는 현황\n\n'
    '- **70%** — Gallup 조사: 관리자 영향력 비중\n'
    '- **21%** — Gallup 보고서: 동기부여 인식 비율\n'
    '- **82%** — CMI 조사: 무자격 관리자 비율\n\n'
    + ('이 수치들이 보여 주는 바를 풀어서 설명합니다. ' * 40) + '\n\n'
    '## 현장의 변화\n\n' + ('현장 사례를 살펴봅니다. ' * 45) + '\n\n'
    '## 시사점: 우리가 갖춰야 할 것\n\n' + ('실행 방법을 제안합니다. ' * 40) + '\n\n'
    '## 맺음말\n\n' + ('핵심을 다시 짚습니다. ' * 20) + '\n\n'
    '## 참고 자료\n\n- Gallup, 「State of the American Manager」\n'
)


class PrecheckDraftTests(TestCase):
    def test_clean_draft_passes(self):
        self.assertEqual(P.precheck_draft(BODY_OK), [])

    def test_short_draft_is_flagged(self):
        issues = P.precheck_draft('## 왜 지금인가\n\n짧습니다.')
        self.assertTrue(any('하한' in i for i in issues))

    def test_missing_sections_are_named(self):
        body = BODY_OK.replace('## 현장의 변화', '## 엉뚱한 제목')
        issues = P.precheck_draft(body)
        self.assertTrue(any('현장의 변화' in i for i in issues))

    def test_plain_style_is_flagged_with_an_example(self):
        body = BODY_OK.replace('설명합니다.', '설명한다.').replace('살펴봅니다.', '살펴본다.')
        issues = P.precheck_draft(body)
        hit = [i for i in issues if '평서체' in i]
        self.assertTrue(hit)
        self.assertIn('예:', hit[0])

    def test_data_section_without_numbers_is_flagged(self):
        body = BODY_OK.replace('- **70%** — Gallup 조사: 관리자 영향력 비중\n', '') \
                      .replace('- **21%** — Gallup 보고서: 동기부여 인식 비율\n', '')
        issues = P.precheck_draft(body)
        self.assertTrue(any('숫자로 보는 현황' in i for i in issues))

    def test_every_issue_says_how_to_fix_it(self):
        """지적만 던지면 다시 써도 같은 결함이 돌아온다."""
        for issue in P.precheck_draft('## 왜 지금인가\n\n짧습니다.'):
            self.assertGreater(len(issue), 25, issue)


class FixDraftTests(TestCase):
    def test_shrunken_rewrite_is_rejected(self):
        """고치려다 원고를 날려 먹지 않는다."""
        with patch.object(P, 'ask_agent', return_value='TITLE: 제목\n---\n너무 짧아진 본문'):
            subject, content, issues = P.step_fix_draft('hrd', '원래 제목', BODY_OK, ['분량 미달'])
        self.assertEqual(content, BODY_OK)
        self.assertEqual(subject, '원래 제목')

    def test_successful_fix_is_rechecked(self):
        raw = 'TITLE: 고친 제목\n---\n' + BODY_OK
        with patch.object(P, 'ask_agent', return_value=raw):
            subject, content, issues = P.step_fix_draft('hrd', '원래 제목', BODY_OK, ['문체'])
        self.assertEqual(subject, '고친 제목')
        self.assertEqual(issues, [])


class WritingStandardTests(TestCase):
    """집필자가 심사 기준을 미리 받아야 한다 — 보이지 않는 기준은 맞출 수 없다."""

    def _prompt(self):
        captured = {}

        def fake(agent, prompt, **kw):
            captured['p'] = prompt
            return 'TITLE: 제목\n---\n' + BODY_OK

        with patch.object(P, 'ask_agent', side_effect=fake):
            P.step_draft('hrd', None, {'angle': 'x'}, [])
        return captured['p']

    def test_draft_prompt_includes_the_rubric(self):
        p = self._prompt()
        for key in P.RUBRIC:
            self.assertIn(P.RUBRIC[key][1][:12], p, key)

    def test_draft_prompt_states_the_hard_gates(self):
        p = self._prompt()
        self.assertIn(f'{P.MIN_CHARS:,}자', p)
        self.assertIn('존댓말', p)
        self.assertIn('숫자로 보는 현황', p)

    def test_draft_prompt_asks_for_a_self_check(self):
        self.assertIn('자기 점검', self._prompt())


class CheckTextTests(TestCase):
    def test_unverifiable_claims_are_surfaced(self):
        text = P.check_text({'verdict': 'revise', 'claims': [
            {'claim': 'ICF 코치 10만 명', 'status': 'unverifiable', 'note': '원문 미확인'},
            {'claim': 'Gallup 70%', 'status': 'ok'},
        ]})
        self.assertIn('ICF 코치 10만 명', text)
        self.assertIn('unverifiable', text)
        self.assertNotIn('Gallup 70%', text)

    def test_clean_report_says_so(self):
        self.assertIn('없음', P.check_text({'verdict': 'pass', 'claims': []}))

    def test_duplicate_flag_is_shown(self):
        self.assertIn('중복', P.check_text({'verdict': 'pass', 'duplicate': True, 'claims': []}))


class AgentModelTests(TestCase):
    def test_office_agents_use_sonnet_5_5(self):
        from common.services.claude import ClaudeModel
        from office.agents import MODEL
        self.assertEqual(str(MODEL), 'claude-sonnet-5-5')
        self.assertEqual(ClaudeModel.SONNET_5_5.value, 'claude-sonnet-5-5')
