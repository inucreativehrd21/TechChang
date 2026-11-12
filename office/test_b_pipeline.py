"""B안의 실제 단계 통합: 같은 버전의 검증·심사·원고가 발행까지 이어져야 한다."""
from io import StringIO
from unittest import mock
from contextlib import ExitStack
from django.core.management import call_command
from django.test import TestCase, override_settings
import tempfile

from community.models import Category, Question
from office import pipeline as P
from office import review_protocol as R
from office.models import ColumnDraft
from office.model_router import use_profile
from office.test_publish_flow import column


class BPipelineTests(TestCase):
    def run_pipeline(self, bad=False, flaws=None):
        body = column(30).replace('\n\n## 참고 자료', ('\n확인한 문서의 범위에서 해석해요. ' * 100)
                                 + '\n\n| 항목 | 수치 |\n|---|---|\n| 동의 | 30% |\n\n## 참고 자료')
        def check(subject, content, *args, **kwargs):
            return {'verdict': 'revise' if bad else 'pass', 'claims': [],
                    'critical': ['근거 미확인'] if bad else [], 'verification_hash': P.verification_hash(content),
                    'content_hash': '', 'subject': subject}
        def qa(*args, **kwargs):
            return {'scores': {k: 5 for k in P.RUBRIC}, 'fatal': [], 'must_fix': [], 'suggestions': []}
        patches = [mock.patch.object(P, 'step_brief', return_value={'angle': '테스트'}),
                   mock.patch.object(P, 'step_blueprint', return_value=({}, {'pack': '근거'})),
                   mock.patch.object(P, 'step_draft', return_value=('검증할 글', body)),
                   mock.patch.object(P, 'precheck_draft', return_value=flaws or []),
                   mock.patch.object(P, 'step_fix_draft', side_effect=AssertionError('B안은 먼저 지적을 통합해야 해요.')),
                   mock.patch.object(P, 'step_check', side_effect=check),
                   mock.patch.object(P, 'step_author_revise', return_value=('검증할 글', body, False, '패치 실패')),
                   mock.patch.object(P, 'step_critique', return_value={'verdict': 'recommend', 'issues': []}),
                   mock.patch.object(P, 'ask_agent_json', side_effect=qa),
                   mock.patch('office.management.commands.office_publish.patch_revise', return_value=('', '', False, '실패')),
                   mock.patch('office.management.commands.office_publish.call_command'),
                   mock.patch('office.ledger.record'), mock.patch('office.live.mark'), mock.patch('office.live.finish')]
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=tmp), use_profile('b'), ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            call_command('office_publish', topic='data', profile='b', no_chart=True,
                         no_publish=True, stdout=StringIO())
        return ColumnDraft.objects.latest('pk')

    def test_current_version_can_pass_and_publication_is_idempotent(self):
        from common.management.commands.auto_write_columns import TOPICS
        Category.objects.get_or_create(name=TOPICS['data']['category_name'])
        draft = self.run_pipeline()
        self.assertTrue(R.publishable(draft.qa_report), draft.qa_report)
        self.assertEqual(draft.qa_report['review_contract_version'], 2)
        from django.contrib.auth.models import User
        from office.approval import approve
        approve(draft, User.objects.create_user('reviewer', is_staff=True, is_superuser=True))
        with mock.patch('office.live.mark'):
            first = P.publish_draft(draft)
            second = P.publish_draft(draft)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Question.objects.count(), 1)

    def test_editor_cannot_override_failed_independent_check(self):
        draft = self.run_pipeline(bad=True)
        self.assertFalse(R.publishable(draft.qa_report))
        self.assertIn('unverified_data', draft.qa_report['fatal'])
        self.assertFalse(Question.objects.exists())

    def test_precheck_flaws_join_first_review_without_an_early_rewrite(self):
        draft = self.run_pipeline(flaws=['서두의 근거 범위를 수정해요.'])
        self.assertFalse(R.publishable(draft.qa_report))
        self.assertTrue(any('서두' in issue.get('problem', '') for issue in draft.qa_report['must_fix']))
        self.assertFalse(draft.stages.filter(stage='fix').exists())

    def test_content_change_after_review_blocks_publication(self):
        draft = self.run_pipeline()
        draft.content += '\n새로운 사실을 추가했어요.'
        with mock.patch('office.live.mark'), self.assertRaises(ValueError):
            P.publish_draft(draft)
        self.assertFalse(Question.objects.exists())

    def test_manual_flag_without_staff_identity_does_not_bypass_review(self):
        draft = self.run_pipeline(bad=True)
        with mock.patch('office.live.mark'), self.assertRaises(ValueError):
            P.publish_draft(draft, manual=True)

    def test_changed_title_is_not_covered_by_old_body_verification(self):
        draft = self.run_pipeline()
        draft.subject = '검증하지 않은 새 주장'
        with mock.patch('office.live.mark'), self.assertRaises(ValueError):
            P.publish_draft(draft)
