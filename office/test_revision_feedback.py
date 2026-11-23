"""재작성에 반영할 지적 고르기(2026-11-16).

전에는 재작성에 편집 심사 '필수 수정'만 넘겨서, 운영자가 '지적대로 고쳐 달라'고 해도 편집 제안은 작성자에게
보이지도 않았다(#61: 제안 8건이 그대로 남음). 이제 관리 화면 체크 목록에서 필수 수정·팩트체크·제안을 고르고,
고른 지적은 하나도 빠짐없이 수정 요구로 연결돼야 하며, 요구마다 반영 여부를 검증한다.
"""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase

from office.models import AuditEvent, ColumnDraft, JobRequest
from office.revision_requests import RevisionRequests, feedback_references
from office.security import validate_args

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}
QA = {'score': 79, 'verdict': 'minor',
      'must_fix': [{'where': '도입부', 'problem': '파일 목록이 네 개뿐', 'fix': '다섯 파일로', 'done_when': '다섯 파일'}],
      'suggestions': ["섹션 제목 '다음 편 예고'를 '시리즈를 마치며'로 바꾸세요.", "CSRF 토큰을 '확인 도장' 하나로 통일하세요."],
      'issues': ['[도입부] 파일 목록이 네 개뿐', "(제안) 섹션 제목 '다음 편 예고'를 '시리즈를 마치며'로 바꾸세요."]}
CHECK = {'verdict': 'pass', 'claims': [{'claim': 'Django 5.2 출시일', 'status': 'outdated', 'note': '2025-04-02'}]}
BEFORE = "## 다음 편 예고\n\nCSRF 토큰은 증명서예요. 파일은 네 개예요."
AFTER = "## 시리즈를 마치며\n\nCSRF 토큰은 확인 도장이에요. 파일은 다섯 개예요."


class FeedbackListTests(SimpleTestCase):
    def test_list_has_must_fix_fact_and_suggestions_with_stable_ids(self):
        rows = feedback_references(QA, CHECK)
        self.assertEqual([(r['id'], r['kind']) for r in rows],
                         [('E1', 'must_fix'), ('F1', 'fact'), ('S1', 'suggestion'), ('S2', 'suggestion')])
        self.assertEqual(rows, feedback_references(QA, CHECK))          # 화면과 작업이 같은 목록을 만든다
        self.assertEqual(rows[2]['label'], '편집 제안')

    def test_old_reviews_without_suggestions_field_use_marked_issues(self):
        rows = feedback_references({'issues': ['필수 하나', '(제안) 예시를 하나 더']}, {})
        self.assertEqual([(r['id'], r['text']) for r in rows], [('E1', '필수 하나'), ('S1', ' 예시를 하나 더'.strip())])

    def test_job_argument_accepts_only_feedback_ids(self):
        ok = ['auto_write_series', '--revise-draft', '9', '--note', 'x', '--feedback', 'E1,F2,S10']
        self.assertEqual(validate_args(ok), ok)
        validate_args(['office_revise', '--draft', '9', '--feedback', ''])
        for bad in ('E1;rm', 'X1', 'E1,,S2', 'E1 S2'):
            with self.assertRaises(ValueError):
                validate_args(['office_revise', '--draft', '9', '--feedback', bad])


def plan(refs_for_r1=('E1',), extra=()):
    reqs = [{'id': 'R1', 'source_quote': '파일 목록이 네 개뿐', 'request': '다섯 파일로', 'done_when': '다섯 파일',
             'reference_ids': list(refs_for_r1), 'kind': 'body'}]
    for i, (ref, quote) in enumerate(extra, 2):
        reqs.append({'id': f'R{i}', 'source_quote': quote, 'request': quote, 'done_when': quote,
                     'reference_ids': [ref], 'kind': 'body'})
    return {'requirements': reqs, 'edits': [{'request_ids': ['R1'], 'find': BEFORE, 'replace': AFTER}], 'title': ''}


def verified(n):
    quotes = ['파일은 다섯 개예요.', '## 시리즈를 마치며', 'CSRF 토큰은 확인 도장이에요.']
    return {'coverage_complete': True, 'missing_requests': [], 'unrelated_changes': [], 'regressions': [],
            'items': [{'id': f'R{i}', 'status': 'met', 'evidence': quotes[i - 1], 'reason': '반영'} for i in range(1, n + 1)]}


class SelectedFeedbackTests(SimpleTestCase):
    def session(self, selected):
        draft = SimpleNamespace(subject='9편', content=BEFORE, qa_report=QA, check_report=CHECK, chart_path='',
                                chart_note='', revisions=1, STATUS_HOLD='hold', save=mock.Mock(), admin_note='')
        s = RevisionRequests(draft, '체크한 지적 3건을 빠짐없이 반영해 주세요.', 'hrd', mock.Mock(), selected=selected)
        s.commit = nullcontext
        return s

    def test_without_selection_suggestions_stay_out_as_before(self):
        s = self.session(None)
        self.assertEqual([r['id'] for r in s.references], ['E1', 'F1'])
        self.assertFalse(s.all_feedback)

    def test_selected_suggestions_are_sent_with_their_kind_and_must_all_be_covered(self):
        s = self.session(['E1', 'S1', 'S2', 'Z9'])                     # 모르는 id 는 버린다
        self.assertEqual([(r['id'], r['kind']) for r in s.references],
                         [('E1', 'must_fix'), ('S1', 'suggestion'), ('S2', 'suggestion')])
        self.assertTrue(s.all_feedback)
        self.assertEqual([r['id'] for r in s.report['selected_feedback']], ['E1', 'S1', 'S2'])
        with self.assertRaisesRegex(ValueError, 'S2'):                  # 제안 하나를 빼먹은 계획은 받지 않는다
            s._parse(plan(extra=[('S1', "섹션 제목 '다음 편 예고'를 '시리즈를 마치며'로 바꾸세요.")]))

    @mock.patch('office.revision_requests.ask_agent_json')
    def test_each_requirement_reports_which_feedback_it_covered(self, ask):
        full = plan(extra=[('S1', "섹션 제목 '다음 편 예고'를 '시리즈를 마치며'로 바꾸세요."),
                           ('S2', "CSRF 토큰을 '확인 도장' 하나로 통일하세요.")])
        ask.side_effect = [full, verified(3)]
        s = self.session(['E1', 'S1', 'S2'])
        self.assertEqual(s.generate(), ('9편', AFTER))
        self.assertEqual([i['reference_ids'] for i in s.report['items']], [['E1'], ['S1'], ['S2']])
        self.assertIn('제안도 골랐으면 반드시 반영', ask.call_args_list[0].args[1])

    @mock.patch('office.revision_requests.ask_agent_json')
    def test_unreflected_suggestion_keeps_the_original(self, ask):
        full = plan(extra=[('S1', "섹션 제목 '다음 편 예고'를 '시리즈를 마치며'로 바꾸세요."),
                           ('S2', "CSRF 토큰을 '확인 도장' 하나로 통일하세요.")])
        missing = verified(3)
        missing['items'][2].update(status='unmet', evidence='')
        ask.side_effect = [full, missing, full, missing]
        s = self.session(['E1', 'S1', 'S2'])
        self.assertIsNone(s.generate())
        s.retain()
        self.assertEqual(s.draft.content, BEFORE)
        self.assertEqual(s.draft.qa_report['admin_revision']['items'][2]['status_label'], '미반영·확인 필요')


class FeedbackRequestViewTests(TestCase):
    def setUp(self):
        otp = mock.patch('common.views._admin_otp_session_ok', return_value=True)
        otp.start()
        self.addCleanup(otp.stop)
        self.client.force_login(User.objects.create_superuser('admin', '', 'x'))
        self.draft = ColumnDraft.objects.create(topic='coding', subject='9편', content=BEFORE, status='hold',
                                                series_key='django', episode_number=9, qa_report=QA, check_report=CHECK)

    def post(self, data):
        return self.client.post(f'/lab/admin/draft/{self.draft.pk}/revise/', data, **UA)

    def job(self):
        return JobRequest.objects.get(draft=self.draft)

    def test_checklist_is_shown_with_everything_checked_and_tied_to_the_revise_form(self):
        html = self.client.get('/lab/admin/', **UA).content.decode()
        self.assertIn('재작성에 반영할 지적', html)
        for ref in ('E1', 'F1', 'S1', 'S2'):
            self.assertIn(f'name="feedback" value="{ref}" form="revise-{self.draft.pk}"', html)
        self.assertIn(f'id="revise-{self.draft.pk}"', html)
        self.assertIn('시리즈를 마치며', html)

    def test_picked_feedback_goes_to_the_job_and_audit_without_a_note(self):
        self.post({'feedback': ['E1', 'S1', 'S2', 'Z9']})
        args = self.job().args
        self.assertEqual(args[args.index('--feedback') + 1], 'E1,S1,S2')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.admin_note, '체크한 지적 3건을 빠짐없이 반영해 주세요.')
        event = AuditEvent.objects.get(draft_id=self.draft.pk, action='revision_requested')
        self.assertEqual([r['id'] for r in event.payload['feedback']], ['E1', 'S1', 'S2'])

    def test_note_and_picks_travel_together_and_the_status_panel_counts_them(self):
        self.post({'note': '사례는 국내로', 'feedback': ['E1', 'S1']})
        args = self.job().args
        self.assertEqual(args[args.index('--note') + 1], '사례는 국내로')
        html = self.client.get('/lab/admin/', **UA).content.decode()
        self.assertIn('class="dr-sent-picks"', html)
        self.assertIn('필수 수정 1', html)
        self.assertIn('편집 제안 1', html)
        self.assertNotIn('name="feedback"', html)                       # 대기 중에는 체크 목록도 잠긴다

    def test_nothing_picked_and_no_note_is_refused(self):
        response = self.post({})
        self.assertFalse(JobRequest.objects.filter(draft=self.draft).exists())
        self.assertIn('반영할 지적을 고르거나', ' '.join(str(m) for m in get_messages(response.wsgi_request)))

    def test_too_many_picks_are_refused(self):
        qa = dict(QA, suggestions=[f'제안 {i}번을 반영하세요.' for i in range(25)])
        ColumnDraft.objects.filter(pk=self.draft.pk).update(qa_report=qa)
        ids = [r['id'] for r in feedback_references(qa, CHECK)]
        self.post({'feedback': ids})
        self.assertFalse(JobRequest.objects.filter(draft=self.draft).exists())

    def test_audit_timeline_lists_the_picked_kinds(self):
        from office import audit_timeline
        self.post({'feedback': ['E1', 'S1', 'S2']})
        days = audit_timeline.build(self.draft.pk)['days']
        facts = dict(days[0]['rows'][0]['facts'])
        self.assertEqual(facts['반영할 지적'], '필수 수정 1 · 편집 제안 2')


class SourceQuoteTests(SimpleTestCase):
    """2026-11-23 #69·#70: 작성자가 긴 팩트체크 지적을 줄임표로 이어 인용해 재작성 요청이 모두 실패했어요."""
    NOTE = '해당 산식을 삭제하고 조문 표현으로 바꿔 주세요. 그리고 6,120 ÷ 12 = 510은 가정 예시로 구분하세요.'

    def test_elided_quote_from_one_source_is_accepted(self):
        from office.revision_requests import quote_in_sources
        self.assertTrue(quote_in_sources('해당 산식을 삭제하고 … 6,120 ÷ 12 = 510은 가정 예시로 구분하세요.', [self.NOTE]))

    def test_pieces_from_different_sources_or_too_short_are_refused(self):
        from office.revision_requests import quote_in_sources
        self.assertFalse(quote_in_sources('해당 산식을 삭제하고…다른 지적의 문장이에요', [self.NOTE, '다른 지적의 문장이에요']))
        self.assertFalse(quote_in_sources('해당…구분', [self.NOTE]))
        self.assertFalse(quote_in_sources('지어낸 요구 문장이에요', [self.NOTE]))

    def test_refusal_names_the_requirement_and_why(self):
        draft = SimpleNamespace(subject='9편', content=BEFORE, qa_report=QA, check_report=CHECK, chart_path='',
                                chart_note='', revisions=1, STATUS_HOLD='hold', save=mock.Mock(), admin_note='')
        s = RevisionRequests(draft, '도입을 고쳐 주세요.', 'hrd', mock.Mock())
        bad = plan()
        bad['requirements'][0]['source_quote'] = '지어낸 인용이에요'
        with self.assertRaisesRegex(ValueError, 'R1 — source_quote'):
            s._parse(bad)
        missing = plan()
        missing['edits'][0]['find'] = '원고에 없는 문장이에요'
        missing['requirements'][0]['source_quote'] = '도입을 고쳐 주세요.'
        with self.assertRaisesRegex(ValueError, '편집 1 — find .*0번'):
            s._parse(missing)
