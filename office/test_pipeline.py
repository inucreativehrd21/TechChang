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


FIGURE_NEW = (
    '![그림 1. 협업량 증가와 몰입도 비교](/media/columns/x.png)\n\n'
    '**그림 1. 협업량 증가와 몰입도 비교**\n\n'
    '회의 시간이 늘어난 만큼 몰입도가 따라 오르지는 않았습니다.\n\n'
    '*단위: %. 출처: Microsoft Work Trend Index(2022).*\n\n'
    '| 항목 | 비율 |\n|---|---|\n| 회의시간 증가 | 148 |\n| 직원 몰입도 | 23 |\n'
)
FIGURE_OLD = (
    '![협업 지표](/media/columns/old.png)\n\n'
    '**협업 지표** (단위: %)\n\n'
    '| 항목 | 비율 |\n|---|---|\n| 회의시간 | 148 |\n\n'
    '*출처: Microsoft(2022)*\n'
)


class StripVisualBlockTests(TestCase):
    """도판을 못 지우면 재작성 때 그림이 두 번 실린다 (draft #6 에서 실제로 발생)."""

    def test_new_journal_format_is_removed(self):
        body = '## 숫자로 보는 현황\n\n앞 문단입니다.\n\n' + FIGURE_NEW + '\n## 다음 절\n\n뒷 문단입니다.\n'
        out = P.strip_visual_block(body)
        for leftover in ('그림 1', '![', '| 항목', '단위: %', '회의 시간이 늘어난'):
            self.assertNotIn(leftover, out, leftover)
        self.assertIn('앞 문단입니다.', out)
        self.assertIn('뒷 문단입니다.', out)

    def test_old_format_is_still_removed(self):
        out = P.strip_visual_block('본문입니다.\n\n' + FIGURE_OLD + '\n이어지는 본문입니다.\n')
        self.assertNotIn('|', out)
        self.assertNotIn('![', out)
        self.assertIn('이어지는 본문입니다.', out)

    def test_stripping_twice_is_stable(self):
        body = '본문입니다.\n\n' + FIGURE_NEW
        self.assertEqual(P.strip_visual_block(P.strip_visual_block(body)), P.strip_visual_block(body))

    def test_bold_emphasis_in_prose_is_kept(self):
        """본문 속 **강조**를 도판 제목으로 오인해 문단을 날리면 안 된다."""
        body = '이것은 **핵심 개념**이라고 부르는 것이며 문장이 이어집니다. 두 번째 문장입니다.\n'
        self.assertIn('핵심 개념', P.strip_visual_block(body))


class TruncationTests(TestCase):
    """max_tokens 에 걸려 끊긴 원고를 길이만 보고 통과시키면 안 된다."""

    GOOD = BODY_OK

    def test_complete_draft_is_not_flagged(self):
        self.assertEqual(P.looks_truncated(self.GOOD), '')

    def test_missing_reference_section_is_truncation(self):
        body = self.GOOD.split('## 참고 자료')[0]
        self.assertIn('참고 자료', P.looks_truncated(body))

    def test_sentence_cut_mid_word_is_caught(self):
        body = self.GOOD + '\n\n마지막 불릿이 여기서 끊기면서 역'
        self.assertIn('끝맺지', P.looks_truncated(body))

    def test_safe_rewrite_keeps_previous_when_truncated(self):
        cut = self.GOOD.split('## 맺음말')[0] + '\n\n마지막 문장이 역'
        subject, content, ok, why = P.safe_rewrite(
            'TITLE: 새 제목\n---\n' + cut, '이전 제목', self.GOOD)
        self.assertFalse(ok)
        self.assertEqual(content, self.GOOD)
        self.assertIn('잘려', why)


class AgentModelTests(TestCase):
    def test_office_agents_use_sonnet_5_5(self):
        from common.services.claude import ClaudeModel
        from office.agents import MODEL
        self.assertEqual(str(MODEL), 'claude-sonnet-5-5')
        self.assertEqual(ClaudeModel.SONNET_5_5.value, 'claude-sonnet-5-5')


class SpoolTransportTests(TestCase):
    """이 세션에서 돌릴 때 API 과금이 생기지 않아야 한다 — 호출이 파일로 나가는지 확인."""

    def setUp(self):
        import shutil
        import tempfile
        self.spool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.spool, True)

    def test_spool_mode_writes_a_prompt_and_never_calls_the_api(self):
        import json
        import os
        import threading

        from office import services as S

        def answer():
            import time
            for _ in range(100):
                if os.path.exists(os.path.join(self.spool, 'pending.json')):
                    meta = json.load(open(os.path.join(self.spool, 'pending.json'), encoding='utf-8'))
                    open(os.path.join(self.spool, f'reply.{meta["seq"]}.md'), 'w',
                         encoding='utf-8').write('파일로 받은 답입니다.')
                    return
                time.sleep(0.02)

        with patch.dict(os.environ, {S.SPOOL_ENV: self.spool}), \
                patch.object(S, 'ask', side_effect=AssertionError('API 호출됨')):
            t = threading.Thread(target=answer)
            t.start()
            out = S.ask_agent('lead', '테스트 지시입니다.')
            t.join()
        self.assertEqual(out, '파일로 받은 답입니다.')
        self.assertTrue(os.path.exists(os.path.join(self.spool, 'done.1.prompt.md')))
        body = open(os.path.join(self.spool, 'done.1.prompt.md'), encoding='utf-8').read()
        self.assertIn('테스트 지시입니다.', body)
        self.assertIn('분석관', body)          # 역할(system) 이 함께 실린다

    def test_api_mode_is_unchanged_when_spool_is_not_set(self):
        import os

        from office import services as S
        with patch.dict(os.environ, {}, clear=False), patch.object(S, 'ask', return_value='API 응답'):
            os.environ.pop(S.SPOOL_ENV, None)
            self.assertEqual(S.ask_agent('lead', 'x'), 'API 응답')


class FabricatedDataGateTests(TestCase):
    """지어낸 수치로 근거 섹션을 채우면 차트도 못 만들고 no_evidence 로 반려된다."""

    def test_hypothetical_example_is_flagged(self):
        body = BODY_OK.replace(
            '- **70%** — Gallup 조사: 관리자 영향력 비중',
            '아래는 이해를 돕기 위한 가상의 400명 조직 예시입니다.\n- **61%** 입력률')
        issues = P.precheck_draft(body)
        self.assertTrue(any('지어낸' in i for i in issues), issues)

    def test_real_sourced_numbers_pass(self):
        self.assertEqual(P.precheck_draft(BODY_OK), [])

    def test_the_word_example_alone_is_not_enough_to_fail(self):
        """'예를 들어' 같은 평범한 서술까지 막으면 글을 못 쓴다."""
        body = BODY_OK.replace('이 수치들이 보여 주는 바를 풀어서 설명합니다. ',
                               '예를 들어 설명하면 이렇습니다. ', 1)
        self.assertEqual(P.precheck_draft(body), [])
