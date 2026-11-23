"""원고 판별 지적 장부(2026-11-23) — 판을 넘어 지적·해결 근거·강점을 이어 가고, 해결된 지적은 다시 보내지 않아요.

배경: 재작성은 직전 판의 심사만 봐서 초안의 좋은 대목이 두 번째 재작성에서 사라지거나, 해결한 지적이
다른 말로 다시 요청됐어요. 관리 화면 체크 목록도 판마다 번호를 새로 매기고 전부 체크된 채 열렸어요.
"""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase

from office import revision_ledger as RL
from office.models import ColumnDraft, JobRequest, RevisionLedger
from office.revision_requests import RevisionRequests

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}
BODY0 = ('## 도입\n\n신입 교육 만족도는 높지만 현업 적용률은 낮아요. 교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.\n\n'
         '## 근거\n\n전이율은 20%라는 말이 흔해요. 이 숫자는 출처가 불분명해요.')
BODY1 = BODY0.replace('전이율은 20%라는 말이 흔해요. 이 숫자는 출처가 불분명해요.',
                      '전이 연구는 복귀 후 첫 2주의 상사 대화가 적용을 좌우한다고 봐요.')
MUST = {'where': '근거', 'problem': '출처 없는 20% 수치', 'fix': '삭제하거나 출처를 대요', 'done_when': '수치 삭제',
        'issue_id': 'issue_a'}
QA0 = {'score': 70, 'verdict': 'minor', 'must_fix': [MUST], 'suggestions': ['맺음말에 실행 질문을 하나 더해요.'],
       'keep_passages': [{'quote': '교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.', 'why': '문제의 원인을 한 문장으로 짚어요',
                          'source': 'critic'}]}
CHECK0 = {'verdict': 'revise', 'claims': [{'claim': '전이율은 20%라는 말이 흔해요', 'status': 'unverifiable',
                                           'note': '출처 없음'}]}
QA1 = {'score': 78, 'verdict': 'minor', 'must_fix': [], 'suggestions': [],
       'resolutions': {'issue_a': {'resolved': True, 'evidence': '전이 연구는 복귀 후 첫 2주의 상사 대화가 적용을 좌우한다고 봐요.'}}}
CHECK1 = {'verdict': 'pass', 'claims': []}


def two_rounds():
    data = RL.advance({}, subject='제목', content=BODY0, qa=QA0, check=CHECK0)
    return RL.advance(data, subject='제목', content=BODY1, qa=QA1, check=CHECK1)


class AdvanceTests(SimpleTestCase):
    def test_first_round_records_items_and_keeps(self):
        data = RL.advance({}, subject='제목', content=BODY0, qa=QA0, check=CHECK0)
        self.assertEqual([r['label'] for r in data['rounds']], ['초안'])
        self.assertEqual(sorted(i['kind'] for i in data['items']), ['fact', 'must_fix', 'suggestion'])
        self.assertEqual({c['state'] for c in data['current']}, {'new'})
        self.assertEqual(data['keeps'][0]['status'], 'kept')
        self.assertEqual(RL.advance(data, subject='제목', content=BODY0, qa=QA0, check=CHECK0), data)  # 같은 판은 그대로

    def test_resolution_needs_evidence_otherwise_it_is_only_cleared(self):
        items = {i['kind']: i for i in two_rounds()['items']}
        self.assertEqual((items['must_fix']['status'], items['must_fix']['evidence_kind']), ('resolved', 'quote'))
        self.assertEqual((items['fact']['status'], items['fact']['evidence_kind']), ('resolved', 'removed'))
        self.assertEqual(items['suggestion']['status'], 'cleared')          # 근거 없이 사라진 제안은 잠그지 않아요

    def test_reraised_issue_with_live_evidence_is_locked(self):
        data = two_rounds()
        qa2 = dict(QA1, score=77, must_fix=[dict(MUST, problem='출처 없는 20% 수치가 남았어요')])
        data = RL.advance(data, subject='제목', content=BODY1 + '\n\n추가 문단.', qa=qa2, check=CHECK1)
        self.assertEqual(data['current'][0]['state'], 'locked')
        rows = RL.annotate([{'id': 'E1', 'kind': 'must_fix', 'label': '필수 수정', 'text': 'x'}], data, current=True)
        self.assertTrue(rows[0]['locked'])
        self.assertFalse(rows[0]['default'])
        self.assertIn('재작성 1에서 해결', rows[0]['resolved_note'])

    def test_lost_evidence_reopens_as_regression_and_lost_keep_is_offered(self):
        data = two_rounds()
        body2 = BODY1.replace('전이 연구는 복귀 후 첫 2주의 상사 대화가 적용을 좌우한다고 봐요.', '전이는 중요해요.')
        body2 = body2.replace('교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.', '이유는 여러 가지예요.')
        data = RL.advance(data, subject='제목', content=body2, qa=dict(QA1, score=74, resolutions={}), check=CHECK1)
        items = {i['kind']: i for i in data['items']}
        self.assertEqual(items['must_fix']['status'], 'regressed')
        self.assertEqual(data['keeps'][0]['status'], 'lost')
        rows = RL.annotate([], data, current=True)
        self.assertEqual([(r['id'], r['kind'], r['default']) for r in rows], [('G1', 'regressed', True), ('K1', 'keep', True)])

    def test_defaults_pick_required_kinds_but_not_suggestions(self):
        data = RL.advance({}, subject='제목', content=BODY0, qa=QA0, check=CHECK0)
        from office.revision_requests import feedback_references
        rows = RL.annotate(feedback_references(QA0, CHECK0), data, current=True)
        self.assertEqual({r['kind']: r['default'] for r in rows}, {'must_fix': True, 'fact': True, 'suggestion': False})

    def test_guidance_lists_only_live_strengths_and_resolved_items(self):
        g = RL.guidance(two_rounds(), BODY1)
        self.assertEqual([p['quote'] for p in g['preserve_passages']], ['교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.'])
        self.assertEqual(len(g['already_resolved']), 2)
        self.assertIn('지켜야 할 강점', RL.guidance_text(two_rounds(), BODY1))

    def test_lost_passages_ignores_intended_edits(self):
        data = two_rounds()
        after = BODY1.replace('교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.', '')
        self.assertEqual(len(RL.lost_passages(data, BODY1, after)), 1)
        self.assertEqual(RL.lost_passages(data, BODY1, after, ['교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.']), [])


class AdminRevisionEvidenceTests(SimpleTestCase):
    def test_adopted_admin_revision_resolves_the_picked_feedback_with_its_quote(self):
        data = RL.advance({}, subject='제목', content=BODY0, qa=QA0, check=CHECK0)
        report = {'status': 'adopted', 'run_id': 'r1',
                  'selected_feedback': [{'id': 'S1', 'kind': 'suggestion', 'text': '맺음말에 실행 질문을 하나 더해요.'}],
                  'items': [{'id': 'R1', 'met': True, 'reference_ids': ['S1'], 'evidence': '복귀 첫 주에 무엇을 물을까요?'}]}
        body = BODY0 + '\n\n복귀 첫 주에 무엇을 물을까요?'
        data = RL.advance(data, subject='제목', content=body, qa=dict(QA0, score=75, suggestions=[], admin_revision=report),
                          check=CHECK0)
        suggestion = next(i for i in data['items'] if i['kind'] == 'suggestion')
        self.assertEqual((suggestion['status'], suggestion['evidence_kind']), ('resolved', 'quote'))
        self.assertEqual(data['seen_revisions'], ['r1'])


class RevisionGuardTests(SimpleTestCase):
    @mock.patch('office.revision_requests.ask_agent_json')
    def test_candidate_that_drops_a_strength_unasked_is_not_verified(self, ask):
        ledger = RL.advance({}, subject='제목', content=BODY0, qa=QA0, check=CHECK0)
        draft = SimpleNamespace(subject='제목', content=BODY0, qa_report=QA0, check_report=CHECK0, chart_path='',
                                chart_note='', revisions=1, STATUS_HOLD='hold', save=mock.Mock(), admin_note='')
        with mock.patch('office.revision_ledger.ledger_for', return_value=ledger):
            s = RevisionRequests(draft, '근거 문단의 20% 문장을 지워 주세요.', 'hrd', mock.Mock())
        s.commit = nullcontext
        quote = '교육 뒤 3개월 동안 아무도 묻지 않았기 때문이에요.'
        bad = BODY0.replace(' ' + quote, '').replace('전이율은 20%라는 말이 흔해요. ', '')
        ask.return_value = {'coverage_complete': True, 'missing_requests': [], 'unrelated_changes': [], 'regressions': [],
                            'items': [{'id': 'R1', 'status': 'met', 'evidence': '이 숫자는 출처가 불분명해요.', 'reason': '삭제'}]}
        s.requirements = [{'id': 'R1', 'request': '20% 문장 삭제', 'done_when': '삭제', 'kind': 'body'}]
        s.finds = ['전이율은 20%라는 말이 흔해요. ']
        report = s.verify('제목', bad)
        self.assertFalse(report['verified'])
        self.assertTrue(any('사라진 대목' in r for r in report['reasons']))
        payload = s._data('제목', bad)
        self.assertEqual(payload['preserve_passages'][0]['quote'], quote)


class LedgerStorageTests(TestCase):
    def test_review_saves_advance_rounds_but_status_saves_do_not(self):
        d = ColumnDraft.objects.create(topic='hrd', subject='제목', content=BODY0, status='hold',
                                       qa_report=QA0, check_report=CHECK0)
        self.assertEqual(len(RevisionLedger.objects.get(draft=d).data['rounds']), 1)
        d.status = 'revising'
        d.save(update_fields=['status'])
        d.qa_report = dict(QA0, admin_revision={'status': 'retained'})      # 기존 원고 유지 — 새 판이 아니에요
        d.save()
        self.assertEqual(len(RevisionLedger.objects.get(draft=d).data['rounds']), 1)
        d.content, d.qa_report, d.check_report = BODY1, QA1, CHECK1
        d.save(update_fields=['content', 'qa_report', 'check_report'])
        self.assertEqual([r['label'] for r in RevisionLedger.objects.get(draft=d).data['rounds']], ['초안', '재작성 1'])

    def test_receiver_survives_garbage_collection(self):
        import gc
        gc.collect()                    # 수신기를 약한 참조로 쥐므로, 모듈 수준이 아니면 여기서 끊겨요
        d = ColumnDraft.objects.create(topic='hrd', subject='제목', content=BODY0, status='hold',
                                       qa_report=QA0, check_report=CHECK0)
        self.assertTrue(RevisionLedger.objects.filter(draft=d).exists())

    def test_unreviewed_draft_has_no_ledger(self):
        d = ColumnDraft.objects.create(topic='hrd', subject='제목', content=BODY0, status='hold')
        self.assertFalse(RevisionLedger.objects.filter(draft=d).exists())


class LedgerAdminViewTests(TestCase):
    def setUp(self):
        otp = mock.patch('common.views._admin_otp_session_ok', return_value=True)
        otp.start()
        self.addCleanup(otp.stop)
        self.client.force_login(User.objects.create_superuser('admin', '', 'x'))
        self.draft = ColumnDraft.objects.create(topic='hrd', subject='제목', content=BODY0, status='hold',
                                                qa_report=QA0, check_report=CHECK0)
        self.draft.content, self.draft.qa_report, self.draft.check_report = BODY1, QA1, CHECK1
        self.draft.save()
        qa2 = dict(QA1, score=77, must_fix=[dict(MUST, problem='출처 없는 20% 수치가 남았어요')],
                   suggestions=['소제목을 질문형으로 바꿔요.'])
        self.draft.content, self.draft.qa_report = BODY1 + '\n\n추가 문단.', qa2
        self.draft.save()

    def test_card_shows_rounds_resolved_items_and_locked_reopen_box(self):
        html = self.client.get('/lab/admin/', **UA).content.decode()
        self.assertIn('class="dr-rounds"', html)
        self.assertIn(f'name="reopen" value="E1" form="revise-{self.draft.pk}"', html)
        self.assertNotIn(f'name="feedback" value="E1"', html)
        self.assertIn('해결된 지적', html)
        self.assertIn('지켜야 할 강점', html)
        self.assertIn('data-default="0"', html)                         # 제안은 기본으로 고르지 않아요

    def test_locked_feedback_is_refused_unless_reopened(self):
        response = self.client.post(f'/lab/admin/draft/{self.draft.pk}/revise/', {'feedback': ['E1']}, **UA)
        self.assertFalse(JobRequest.objects.filter(draft=self.draft).exists())
        self.assertIn('다시 열기', ' '.join(str(m) for m in get_messages(response.wsgi_request)))
        self.client.post(f'/lab/admin/draft/{self.draft.pk}/revise/', {'reopen': ['E1']}, **UA)
        args = JobRequest.objects.get(draft=self.draft).args
        self.assertEqual(args[args.index('--feedback') + 1], 'E1')
