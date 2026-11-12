from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from office.revision_requests import RevisionRequests


NOTE = '첫 문장을 바꾸고 둘째 문장은 유지해 주세요.'
BEFORE = '첫 문장은 이전 설명이에요.\n\n둘째 문장은 검증된 근거예요.'
AFTER = BEFORE.replace('이전 설명', '구체적인 선택 기준')


def plan():
    return {'requirements': [
        {'id': 'R1', 'source_quote': '첫 문장을 바꾸고', 'request': '첫 문장 수정',
         'done_when': '구체적인 선택 기준을 제시', 'kind': 'body'},
        {'id': 'R2', 'source_quote': '둘째 문장은 유지', 'request': '둘째 문장 보존',
         'done_when': '기존 근거 문장을 그대로 유지', 'kind': 'body'}],
        'edits': [{'request_ids': ['R1'], 'find': '첫 문장은 이전 설명이에요.',
                   'replace': '첫 문장은 구체적인 선택 기준이에요.'}], 'title': ''}


def verified():
    return {'coverage_complete': True, 'missing_requests': [], 'unrelated_changes': [], 'regressions': [],
            'items': [{'id': 'R1', 'status': 'met', 'evidence': '첫 문장은 구체적인 선택 기준이에요.', 'reason': '기준을 제시했어요.'},
                      {'id': 'R2', 'status': 'met', 'evidence': '둘째 문장은 검증된 근거예요.', 'reason': '근거를 보존했어요.'}]}


class RequestVerificationTests(SimpleTestCase):
    def session(self):
        draft = SimpleNamespace(subject='기존 제목', content=BEFORE, qa_report={'score': 71},
            check_report={'verdict': 'pass'}, chart_path='columns/original.png', chart_note='기존 그림',
            revisions=2, STATUS_HOLD='hold', save=Mock())
        session = RevisionRequests(draft, NOTE, 'hrd', Mock())
        session.commit = nullcontext
        return session

    @patch('office.revision_requests.ask_agent_json')
    def test_exact_patch_preserves_unrequested_text_and_reuses_unchanged_verification(self, ask):
        ask.side_effect = [plan(), verified()]
        session = self.session()
        self.assertEqual(session.generate(), ('기존 제목', AFTER))
        qa = {'score': 74, 'fatal': []}
        self.assertTrue(session.finish('기존 제목', AFTER, qa, {'verdict': 'pass'}))
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(qa['admin_revision']['status'], 'adopted')

    @patch('office.revision_requests.ask_agent_json')
    def test_unmet_request_gets_one_targeted_retry(self, ask):
        missing = verified()
        missing['items'][0]['status'] = 'unmet'
        ask.side_effect = [plan(), missing, plan(), verified()]
        session = self.session()
        self.assertIsNotNone(session.generate())
        self.assertEqual(ask.call_count, 4)
        self.assertIn('미반영', ask.call_args_list[2].args[1])

    @patch('office.revision_requests.ask_agent_json')
    def test_omitted_original_request_is_not_accepted_even_with_all_reported_items_met(self, ask):
        report = verified()
        report.update(coverage_complete=False, missing_requests=['둘째 문장은 유지'])
        ask.side_effect = [plan(), report, plan(), report]
        session = self.session()
        self.assertIsNone(session.generate())
        session.retain()
        self.assertEqual(session.draft.content, BEFORE)
        self.assertEqual(session.draft.qa_report['admin_revision']['status'], 'retained')

    def test_missing_duplicate_forged_evidence_and_truthy_string_are_rejected(self):
        bad_reports = []
        for change in ('missing', 'duplicate', 'forged', 'truthy', 'unrelated', 'regression', 'nonobject'):
            report = verified()
            if change == 'missing':
                report['items'].pop()
            elif change == 'duplicate':
                report['items'][1]['id'] = 'R1'
            elif change == 'forged':
                report['items'][0]['evidence'] = '최종 원고에 없는 문장'
            elif change == 'truthy':
                report['coverage_complete'] = 'true'
            elif change == 'unrelated':
                report['unrelated_changes'] = ['요청 밖의 근거를 삭제했어요.']
            elif change == 'regression':
                report['regressions'] = ['코드가 깨졌어요.']
            else:
                report = []
            bad_reports.append((change, report))
        for change, report in bad_reports:
            with self.subTest(change=change), patch('office.revision_requests.ask_agent_json', return_value=report):
                session = self.session()
                session._parse(plan())
                self.assertFalse(session.verify('기존 제목', AFTER)['verified'])

    def test_invalid_anchor_does_not_leave_partial_edits_or_change_title(self):
        session = self.session()
        value = plan()
        value['edits'].append({'request_ids': ['R1'], 'find': '없는 문장입니다.', 'replace': '추가 문장'})
        with self.assertRaises(ValueError):
            session._parse(value)
        self.assertEqual(session.draft.content, BEFORE)
        value = plan()
        value['title'] = '요청하지 않은 제목'
        with self.assertRaises(ValueError):
            session._parse(value)

    @patch('office.revision_requests.ask_agent_json')
    def test_postprocessing_that_undoes_an_edit_is_rechecked_and_keeps_baseline(self, ask):
        bad = verified()
        bad['items'][0].update(status='unmet', evidence='')
        ask.side_effect = [plan(), verified(), bad]
        session = self.session()
        session.generate()
        self.assertFalse(session.finish('기존 제목', BEFORE, {'score': 90, 'fatal': []}, {'verdict': 'pass'}))
        self.assertEqual(session.draft.content, BEFORE)
        self.assertEqual(ask.call_count, 3)

    @patch('office.revision_requests.ask_agent_json')
    def test_lower_score_keeps_original_reports_and_assets(self, ask):
        ask.side_effect = [plan(), verified()]
        session = self.session()
        session.generate()
        session.draft.chart_path = 'columns/new.png'
        self.assertFalse(session.finish('기존 제목', AFTER, {'score': 66, 'fatal': []}, {'verdict': 'pass'}))
        self.assertEqual(session.draft.content, BEFORE)
        self.assertEqual(session.draft.chart_path, 'columns/original.png')
        self.assertEqual(session.draft.qa_report['score'], 71)
        self.assertEqual(session.draft.qa_report['admin_revision']['candidate_score'], 66)

    def test_new_fatal_fact_failure_and_syntax_failure_cannot_win_by_score(self):
        for kind in ('fatal', 'check', 'syntax', 'memo'):
            with self.subTest(kind=kind), patch('office.revision_requests.ask_agent_json', return_value=verified()):
                session = self.session()
                session._parse(plan())
                content = AFTER
                qa, check = {'score': 95, 'fatal': []}, {'verdict': 'pass'}
                if kind == 'fatal':
                    qa['fatal'] = ['new_failure']
                elif kind == 'check':
                    check['verdict'] = 'revise'
                elif kind == 'syntax':
                    content += '\n```python\nif True\n    pass\n```'
                else:
                    content += '\nTODO: 작성 메모'
                self.assertFalse(session.finish('기존 제목', content, qa, check))
                self.assertEqual(session.draft.content, BEFORE)

    @patch('office.revision_requests.ask_agent_json', side_effect=RuntimeError('provider limit'))
    def test_provider_error_is_not_retried(self, ask):
        with self.assertRaises(RuntimeError):
            self.session().generate()
        self.assertEqual(ask.call_count, 1)

    def test_all_feedback_request_requires_every_referenced_issue_and_exposes_it_to_verifier(self):
        session = self.session()
        session.draft.qa_report = {'score': 71, 'must_fix': [{'where': '도입', 'problem': '약속 불일치',
            'fix': '도입 문장 수정', 'done_when': '본문과 일치'}]}
        session.draft.check_report = {'verdict': 'pass', 'notes': '공식 링크가 열리는지 확인해 주세요.',
            'bad': [{'claim': '연재 코드 동작', 'note': '정의되지 않은 이름을 고쳐 주세요.'}]}
        session = RevisionRequests(session.draft, '편집장 필수 수정과 팩트체크 지적을 모두 반영해 주세요.', 'hrd', Mock())
        value = plan()
        value['requirements'] = [{'id': 'R1', 'source_quote': session.note, 'request': '모두 수정',
            'done_when': '지적 해결', 'kind': 'body'}]
        with self.assertRaisesMessage(ValueError, '누락된 기존 검수 지적'):
            session._parse(value)
        value['requirements'][0]['reference_ids'] = [r['id'] for r in session.references]
        session._parse(value)
        data = session._data(session.subject, AFTER)
        self.assertEqual(len(data['referenced_feedback']), 3)
        self.assertIn('공식 링크', data['referenced_feedback'][-1]['text'])

    @patch('office.revision_requests.ask_agent_json', return_value=verified())
    def test_retained_candidate_still_records_completed_review_call_usage(self, ask):
        session = self.session()
        session._parse(plan())
        usage = {'tags': {'stage': 'review'}, 'input_tokens': 100, 'output_tokens': 10}
        with patch('office.run_context.current', return_value=SimpleNamespace(active_calls=[usage])):
            self.assertFalse(session.finish(session.subject, AFTER, {'score': 60, 'fatal': []}, {'verdict': 'pass'}))
        decision = [c for c in session.stages.record.call_args_list if c.args[0] == 'revision_decision'][0]
        self.assertEqual(decision.kwargs['calls'], [usage])

    @patch('office.revision_requests.ask_agent_json')
    def test_requested_chart_render_is_verified_after_rendering_not_before(self, ask):
        session = self.session()
        session.note = '그림을 새로 그려 주세요.'
        value = {'requirements': [{'id': 'R1', 'source_quote': session.note, 'request': session.note,
            'done_when': '새 그림이 본문에 삽입됨', 'kind': 'visual', 'visual_action': 'render'}], 'edits': [], 'title': ''}
        report = {'coverage_complete': True, 'missing_requests': [], 'unrelated_changes': [], 'regressions': [],
                  'items': [{'id': 'R1', 'status': 'met', 'evidence': '![새 그림](/media/new.png)', 'reason': '삽입됐어요.'}]}
        ask.side_effect = [value, report]
        self.assertIsNotNone(session.generate())
        self.assertEqual(ask.call_count, 1)
        self.assertIsNone(session.cached_verification)
        self.assertTrue(session.finish(session.subject, BEFORE+'\n\n![새 그림](/media/new.png)',
                                       {'score': 80, 'fatal': []}, {'verdict': 'pass'}))
        self.assertEqual(ask.call_count, 2)


class AdminRevisionFlowTests(TestCase):
    def setUp(self):
        from office.models import ColumnDraft
        self.draft = ColumnDraft.objects.create(topic='hrd', status='hold', subject='기존 제목', content=BEFORE,
            qa_report={'score': 71, 'verdict': 'minor', 'issues': []}, check_report={'verdict': 'pass'})

    def run_revision(self, score=74, check_status='pass', note=NOTE, responses=None):
        from office.pipeline import verification_hash
        def check(subject, content, *args, **kwargs):
            return {'verdict': check_status, 'claims': [], 'subject': subject,
                    'verification_hash': verification_hash(content)}
        with patch('office.revision_requests.ask_agent_json', side_effect=responses or [plan(), verified()]), \
             patch('office.pipeline.step_check', side_effect=check), \
             patch('office.pipeline.lock_numbers', side_effect=lambda content, *a, **k: (content, [])), \
             patch('office.pipeline.step_critique', return_value={'verdict': 'recommend', 'issues': []}), \
             patch('office.pipeline.step_review', return_value={'score': score, 'length': 100, 'fatal': [],
                                                               'verdict': 'accept', 'issues': []}), \
             patch('office.pipeline.step_headline') as headline, \
             patch('office.pipeline.step_visual') as visual, \
             patch('office.pipeline.publish_draft') as publish:
            call_command('office_revise', draft=self.draft.pk, note=note, stdout=Mock())
        self.draft.refresh_from_db()
        headline.assert_not_called()
        visual.assert_not_called()
        publish.assert_not_called()

    def test_verified_edit_is_saved_and_still_waits_for_human_approval(self):
        from office.models import StageRun
        self.run_revision()
        self.assertEqual(self.draft.content, AFTER)
        self.assertEqual(self.draft.status, 'hold')
        self.assertEqual(self.draft.qa_report['admin_revision']['status'], 'adopted')
        self.assertTrue(StageRun.objects.filter(draft=self.draft, stage='final').exists())

    def test_lower_score_preserves_database_content_and_records_candidate(self):
        from office.models import StageRun
        self.run_revision(score=66)
        self.assertEqual(self.draft.content, BEFORE)
        self.assertEqual(self.draft.qa_report['score'], 71)
        self.assertFalse(StageRun.objects.filter(draft=self.draft, stage='final').exists())
        candidate = StageRun.objects.get(draft=self.draft, stage='revision_decision')
        self.assertEqual(candidate.output['content'], AFTER)
        self.assertEqual(candidate.output['review']['score'], 66)

    def test_requested_figure_deletion_is_not_undone_by_automatic_generation(self):
        figure = '\n\n[//]: # (tc-figure)\n\n**표 1. 비교**\n\n|항목|값|\n|---|---|\n|A|1|'
        self.draft.content = BEFORE + figure
        self.draft.save(update_fields=['content'])
        note = '표를 삭제해 주세요.'
        value = {'requirements': [{'id': 'R1', 'source_quote': note, 'request': note, 'done_when': '표 삭제',
            'kind': 'visual', 'visual_action': 'remove'}],
            'edits': [{'request_ids': ['R1'], 'find': figure, 'replace': ''}], 'title': ''}
        report = {'coverage_complete': True, 'missing_requests': [], 'unrelated_changes': [], 'regressions': [],
                  'items': [{'id': 'R1', 'status': 'met', 'evidence': '둘째 문장은 검증된 근거예요.', 'reason': '표를 삭제했어요.'}]}
        self.run_revision(note=note, responses=[value, report])
        self.assertEqual(self.draft.content, BEFORE)
        self.assertEqual(self.draft.chart_path, '')

    def test_rejected_requests_cannot_be_approved_even_as_format_exception(self):
        from office.approval import policy
        self.run_revision(score=66)
        for mode in ('normal', 'exception'):
            with self.assertRaisesMessage(ValueError, '수정 요청이 완료되지'):
                policy(self.draft, mode)

    def test_concurrent_edit_is_never_overwritten_by_retention_or_adoption(self):
        from office.models import ColumnDraft
        session = RevisionRequests(self.draft, NOTE, 'hrd', Mock())
        ColumnDraft.objects.filter(pk=self.draft.pk).update(content='작업 도중 관리자가 직접 고친 본문')
        with self.assertRaisesMessage(ValueError, '다른 편집 결과를 덮어쓰지'):
            session.retain()
        with self.assertRaisesMessage(ValueError, '다른 편집 결과를 덮어쓰지'):
            with session.commit():
                self.fail('Stale candidate entered commit')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.content, '작업 도중 관리자가 직접 고친 본문')

    def test_failed_request_is_reported_on_admin_screen_and_escaped(self):
        from django.contrib.auth.models import User
        from django.urls import reverse
        self.run_revision(score=66)
        self.draft.qa_report['admin_revision']['candidate_content'] = '<script>candidateSecret()</script>'
        self.draft.save(update_fields=['qa_report'])
        owner = User.objects.create_superuser('request-owner', '', 'x')
        self.client.force_login(owner)
        response = self.client.get(reverse('office:admin'))
        self.assertContains(response, '수정 요청 반영 결과')
        self.assertContains(response, '기존 원고 유지')
        self.assertContains(response, '66점')
        self.assertContains(response, '미채택 보완본 보기')
        self.assertContains(response, '&lt;script&gt;candidateSecret()&lt;/script&gt;')
        self.assertNotContains(response, '<script>candidateSecret()</script>')
