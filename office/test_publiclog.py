"""공개 연구실 활동 피드 — 무엇이 나가고 무엇이 막히는지.

배경: /lab/ 이 WorkLog.text 원문을 그대로 뿌리고 있었다. 운영자가 입력한 수정 지시문,
편집 심사 점수·치명 결함, 정비 백로그와 서버 보안 과제가 전부 공개돼 있었다.
"""
from unittest.mock import patch

from django.test import TestCase

from office.models import WorkLog
from office.publiclog import polish, public_line, public_logs


def log(agent='lead', action='publish', text='발행: 어떤 칼럼', **kw):
    return WorkLog.objects.create(agent=agent, action=action, text=text, **kw)


class PrivateActionsTests(TestCase):
    """공개하면 안 되는 것들 — 하나라도 새면 실패한다."""

    def test_admin_instruction_is_never_public(self):
        wl = log(action='admin_note', text='운영자 수정 지시 접수: 비공식 인터뷰는 삭제해줘')
        self.assertIsNone(public_line(wl))

    def test_maintenance_backlog_is_never_public(self):
        for action, text in (('crew', '정비 백로그 등록 #7: 5xx 오류 및 의심 IP 자동 차단'),
                             ('patch', '1차 수정: 2개 파일'), ('verify', '1차 검증 통과'),
                             ('triage', '분류 P2/bug'), ('scan', '관련 파일 3개'),
                             ('pr', 'PR 생성: https://github.com/x/y/pull/2'),
                             ('issue', 'GitHub 이슈 #1 생성')):
            self.assertIsNone(public_line(log(action=action, text=text)), action)

    def test_failures_are_never_public(self):
        self.assertIsNone(public_line(log(action='fail', text='제작 실패: KeyError')))
        self.assertIsNone(public_line(log(action='reject', text='관리자 반려: 어떤 칼럼')))

    def test_ops_decisions_are_not_public_but_column_decisions_are(self):
        ops = log(action='decision', text='관리자 결정: 운영·보안 점검 과제 → 의심 IP 차단 로그 모니터링')
        col = log(action='decision', text='관리자 결정: 다음 주 프로그래밍 칼럼 주제 → Jujutsu')
        self.assertIsNone(public_line(ops))
        self.assertIsNotNone(public_line(col))

    def test_decision_line_keeps_only_the_chosen_title(self):
        """'안건 → 선택' 표기가 그대로 나가면 내부 문서처럼 보인다."""
        wl = log(action='decision', text='관리자 결정: 이번 주 HRD 칼럼 주제 → 1on1 미팅, 형식만 남는 이유')
        line = public_line(wl)
        self.assertIn('1on1 미팅', line)
        self.assertNotIn('→', line)
        self.assertNotIn('관리자', line)

    def test_unknown_action_defaults_to_private(self):
        """새 action 이 생겨도 기본은 비공개여야 한다."""
        self.assertIsNone(public_line(log(action='some_new_step', text='내부 내용')))


class SanitizedOutputTests(TestCase):
    def test_score_and_reason_are_stripped_from_review_logs(self):
        wl = log(action='qa', text='편집 심사 70/100 (3819자) · 치명결함 overclaim → 보류: 미검증 수치 두 건')
        line = public_line(wl)
        for leaked in ('70', '3819', 'overclaim', '미검증'):
            self.assertNotIn(leaked, line)
        self.assertIn('보완', line)

    def test_character_counts_do_not_leak(self):
        wl = log(agent='hrd', action='draft', text='초안 완성: 1on1의 역설 (3451자)')
        line = public_line(wl)
        self.assertNotIn('3451', line)
        self.assertIn('1on1의 역설', line)

    def test_accepted_review_reads_as_a_pass(self):
        wl = log(action='qa', text='편집 심사 88/100 (3200자) → 발행: 좋습니다')
        self.assertIn('통과', public_line(wl))


class PublicLogsListTests(TestCase):
    def test_duplicate_sentences_are_collapsed(self):
        for _ in range(4):
            log(agent='hrd', action='check', text='팩트체크 pass: 확인 필요 2건')
        rows = public_logs(WorkLog.objects.order_by('-created_at'))
        self.assertEqual(len(rows), 1)

    def test_polished_text_is_preferred_over_the_template_sentence(self):
        wl = log(action='publish', text='발행: 어떤 칼럼')
        wl.public_text = '이번 편, 드디어 내보냈습니다.'
        wl.save(update_fields=['public_text'])
        rows = public_logs(WorkLog.objects.order_by('-created_at'))
        self.assertEqual(rows[0][2], '이번 편, 드디어 내보냈습니다.')

    def test_private_logs_stay_out_even_if_polished(self):
        """비공개 action 은 public_text 가 채워져 있어도 나가면 안 된다."""
        wl = log(action='admin_note', text='운영자 지시: 비밀')
        wl.public_text = '무언가 다듬어진 문장'
        wl.save(update_fields=['public_text'])
        self.assertEqual(public_logs(WorkLog.objects.order_by('-created_at')), [])

    def test_listing_never_calls_the_model(self):
        """페이지가 폴링하므로 조회 경로에서 API 를 부르면 안 된다."""
        log(action='publish', text='발행: 어떤 칼럼')
        with patch('office.services.ask_agent_json', side_effect=AssertionError('API 호출됨')):
            self.assertTrue(public_logs(WorkLog.objects.order_by('-created_at')))


class PolishTests(TestCase):
    ROWS = [(1, '은혜', '분석관·팀장', '칼럼을 발행했습니다 — 1on1의 역설.'),
            (2, '재원', '데이터·차트 담당', '도표를 만들었습니다.')]

    def test_model_output_is_mapped_back_by_id(self):
        fake = {'lines': {'1': '이번 편 내보냈습니다.', '2': '지표 세 개를 한 장에 담았습니다.'}}
        with patch('office.services.ask_agent_json', return_value=fake):
            self.assertEqual(polish(self.ROWS),
                             {1: '이번 편 내보냈습니다.', 2: '지표 세 개를 한 장에 담았습니다.'})

    def test_unknown_ids_from_the_model_are_ignored(self):
        with patch('office.services.ask_agent_json', return_value={'lines': {'99': '엉뚱한 답'}}):
            self.assertEqual(polish(self.ROWS), {})

    def test_malformed_response_is_survivable(self):
        with patch('office.services.ask_agent_json', return_value={}):
            self.assertEqual(polish(self.ROWS), {})

    def test_empty_input_makes_no_call(self):
        with patch('office.services.ask_agent_json', side_effect=AssertionError('API 호출됨')):
            self.assertEqual(polish([]), {})

    def test_prompt_only_receives_sanitized_lines(self):
        """모델에 원문을 주지 않는다 — 입력에 없으면 출력에도 없다."""
        captured = {}

        def fake(agent, prompt, **kw):
            captured['prompt'] = prompt
            return {'lines': {}}

        with patch('office.services.ask_agent_json', side_effect=fake):
            polish(self.ROWS)
        self.assertNotIn('운영자', captured['prompt'])
        self.assertIn('1on1의 역설', captured['prompt'])
