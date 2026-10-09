from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office.making import _event, _parse_critique, _parse_qa, build_making
from office.models import ColumnDraft, Decision, Meeting, WorkLog

ADMIN_SECRET = '운영자 비밀 지시문: 2023년 6월 공개는 근거가 없습니다'

# 운영 로그(2026-10, 질문 109)와 같은 형식
LOGS = [
    ('lead', 'brief', '집필 의뢰서: 왜 지금 Git 다음을 묻는가를 데이터로 출발한다'),
    ('coding', 'draft', '초안 완성: Git 다음은 뭘까 (3789자)'),
    ('checker', 'check', '팩트체크 revise: 확인 필요 4건, 기존 칼럼과 중복'),
    ('critic', 'critique', "평론 수정 후 재검토 · 지적 3건 — 「핵심은 불만이 추상적 논쟁에 머물지 않고 'jujutsu 」 "
                           "제목이 '검색창'을 전면에 내세우는데도 검색량 추이(예: Google Trends 지수): 제목이 약속한 데이터가 없습니다"),
    ('editor', 'qa', '편집 심사 54/100 (3600자) · 치명결함 unverified_data,visual_broken → 보류(운영자 검수): jj 공개 연도 오류'),
    ('lead', 'hold', '보류(major, 54점): Git 다음은 뭘까 — 운영자 검수 대기'),
    ('lead', 'admin_note', '운영자 수정 지시 접수: ' + ADMIN_SECRET),
    ('coding', 'revise', '운영자 지시 반영해 재작성: Git 20년, GitHub 스타가 먼저 보내는 신호 (3486자)'),
    ('checker', 'check', '팩트체크 pass: 확인 필요 0건'),
    ('editor', 'qa', '재심 100/100 (3623자) → 발행: 팩트체크 전원 verified'),
    ('lead', 'publish', '운영자 지시 반영 후 발행: Git 20년, GitHub 스타가 먼저 보내는 신호 (id=109, 100점)'),
    ('lead', 'crew', '정비반: 이슈 #12 처리'),  # 비공개 action
]


def log(action, text, agent='lead'):
    return SimpleNamespace(action=action, agent=agent, text=text, created_at=timezone.now())


class ParserTests(TestCase):
    def test_qa_line(self):
        qa = _parse_qa(LOGS[4][2])
        self.assertEqual(qa['score'], 54)
        self.assertEqual(qa['verdict'], 'major')
        self.assertEqual(qa['fatal'], ['확인되지 않은 수치', '도표가 아무것도 말해 주지 못함'])
        self.assertEqual(qa['note'], 'jj 공개 연도 오류')

    def test_legacy_ten_point_scale(self):
        self.assertEqual(_parse_qa('QA 5/10 → 보류(관리자 검수): 출처 보강')['score'], 50)

    def test_critique_with_colon_inside_reason(self):
        cr = _parse_critique(LOGS[3][2])
        self.assertEqual(cr['verdict_label'], '수정 후 재검토')
        self.assertEqual(cr['issues'], 3)
        self.assertTrue(cr['quote'].startswith('핵심은 불만이'))
        self.assertTrue(cr['why'].endswith('Google Trends 지수)'))
        self.assertEqual(cr['reason'], '제목이 약속한 데이터가 없습니다')

    def test_admin_note_text_is_never_exposed(self):
        ev = _event(log('admin_note', '운영자 수정 지시 접수: ' + ADMIN_SECRET))
        self.assertEqual(ev['agent']['name'], '운영자')
        self.assertNotIn('비밀', ev['summary'] + ev['detail'])

    def test_private_actions_are_dropped(self):
        for action in ('crew', 'reject', 'fail', 'triage', 'unknown_new_action'):
            self.assertIsNone(_event(log(action, 'x')))

    def test_internal_ids_are_stripped(self):
        ev = _event(log('publish', LOGS[10][2]))
        self.assertNotIn('id=', ev['summary'] + ev['detail'] + ev['badge'])
        self.assertEqual(ev['badge'], '100점')


class BuildAndViewTests(TestCase):
    def setUp(self):
        bot = User.objects.create(username='bot')
        cat = Category.objects.create(name='칼럼')
        self.q = Question.objects.create(author=bot, category=cat, subject='Git 20년', content='본문',
                                         create_date=timezone.now())
        meeting = Meeting.objects.create(week_start=date(2026, 9, 28))
        dec = Decision.objects.create(meeting=meeting, kind='column', topic='coding', question='코딩 칼럼',
                                      options=[{'key': 'a', 'title': 'Jujutsu로 보는 VCS', 'proposed_by': '윤성'}],
                                      chosen_key='a')
        self.draft = ColumnDraft.objects.create(
            topic='coding', decision=dec, subject='Git 20년', status=ColumnDraft.STATUS_PUBLISHED, question=self.q,
            qa_report={'score': 100, 'verdict': 'accept', 'scores': {'structure': 5, 'depth': 4},
                       'strengths': '연혁을 바로잡음', 'issues': []},
            check_report={'claims': [{'claim': 'Git은 2005년에 나왔다', 'status': 'verified'}]})
        start = timezone.now() - timedelta(days=3)
        for i, (agent, action, text) in enumerate(LOGS):
            w = WorkLog.objects.create(agent=agent, action=action, text=text, draft=self.draft)
            WorkLog.objects.filter(id=w.id).update(created_at=start + timedelta(minutes=i))

    def test_build_making_summary(self):
        mk = build_making(self.draft)
        self.assertEqual(mk['score_trail'], [54, 100])
        self.assertEqual(mk['reviews'], 2)
        self.assertEqual(mk['rewrites'], 1)
        self.assertEqual(mk['human_steps'], 1)
        self.assertEqual(mk['events'][0]['action'], 'meeting')
        self.assertEqual(mk['events'][0]['agent']['name'], '윤성')
        # 심사 1회 = 회차 1개, 보류는 그 회차에, 발행은 마지막 회차에
        self.assertEqual(len(mk['rounds']), 2)
        self.assertEqual(mk['rounds'][0]['events'][-1]['action'], 'hold')
        self.assertTrue(mk['rounds'][1]['published'])
        self.assertTrue(mk['rounds'][1]['human'])
        # 초안 가제 → 재집필 때 제목이 바뀐 사실이 남는다
        revise = next(e for e in mk['events'] if e['action'] == 'revise')
        self.assertIn('GitHub 스타가 먼저 보내는 신호', revise['detail'])

    def test_unpublished_draft_has_no_making(self):
        self.draft.status = ColumnDraft.STATUS_HOLD
        self.assertIsNone(build_making(self.draft))

    def test_making_page_renders_without_secrets(self):
        res = self.client.get(f'/lab/making/{self.q.id}/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        for expected in ('Git 20년', '54점', '100점', '확인되지 않은 수치', '핵심은 불만이', '운영자 검토',
                         'Git은 2005년에 나왔다', '연혁을 바로잡음'):
            self.assertIn(expected, body)
        for secret in ('비밀 지시문', '정비반', 'id=109', '#12'):
            self.assertNotIn(secret, body)

    def test_making_page_404_for_hold_draft(self):
        self.draft.status = ColumnDraft.STATUS_HOLD
        self.draft.save()
        res = self.client.get(f'/lab/making/{self.q.id}/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(res.status_code, 404)

    def test_column_detail_shows_card_and_plain_post_does_not(self):
        res = self.client.get(f'/{self.q.id}/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(res, 'mk-card')
        self.assertContains(res, f'/lab/making/{self.q.id}/')
        plain = Question.objects.create(author=self.q.author, category=self.q.category, subject='일반 글',
                                        content='x', create_date=timezone.now())
        res = self.client.get(f'/{plain.id}/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'mk-card')


class SuggestionGistTests(TestCase):
    def test_gist_keeps_first_sentence_without_section_tag(self):
        from office.making import _gist
        self.assertEqual(_gist('[점검의 계단 설계] 핵심 산출물인 시점별 일정표가 없습니다. 아래 표는 없고'),
                         '핵심 산출물인 시점별 일정표가 없습니다.')
        self.assertEqual(_gist('수치가 세 번 반복됨 — 한두 번으로 압축 필요'), '수치가 세 번 반복됨')
        self.assertTrue(_gist('가' * 200).endswith('…'))
