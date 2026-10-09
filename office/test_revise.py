import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from office.models import ColumnDraft

EDITED = '## 왜 지금인가\n\n사람이 교열한 본문입니다.\n\n![그림 1. 전이 비율 — 직후 62%](/media/columns/x.png)\n\n**그림 1. 전이 비율**\n'


class ReviewOnlyTests(TestCase):
    """사람이 직접 교열한 원고는 재작성 없이 심사만 받는다(원고 #8)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / 'edited.md'
        self.file.write_text(EDITED, encoding='utf-8')
        live = override_settings(OFFICE_LIVE_PATH=str(Path(tmp.name) / 'live.json'))
        live.enable()
        self.addCleanup(live.disable)
        self.draft = ColumnDraft.objects.create(topic='hrd', subject='옛 제목', content='옛 본문',
                                                status=ColumnDraft.STATUS_HOLD, chart_path='columns/x.png',
                                                chart_note='차트 삽입: 전이 비율')

    def run_cmd(self, verdict, **extra):
        qa = {'verdict': verdict, 'score': 85 if verdict == 'accept' else 70, 'length': 3000, 'notes': '',
              'issues': [], 'fatal': []}
        with mock.patch('office.management.commands.office_revise.ask_agent') as writer, \
                mock.patch('office.pipeline.step_check', return_value={'verdict': 'pass', 'claims': []}) as check, \
                mock.patch('office.pipeline.step_visual') as visual, \
                mock.patch('office.pipeline.step_critique', return_value={'verdict': 'recommend', 'issues': []}), \
                mock.patch('office.pipeline.step_review', return_value=qa) as review, \
                mock.patch('office.pipeline.publish_draft') as publish:
            call_command('office_revise', draft=self.draft.id, review_only=True,
                         content_file=str(self.file), subject='새 제목', stdout=mock.MagicMock(), **extra)
        return writer, check, visual, review, publish

    def test_no_rewrite_and_edited_text_is_reviewed(self):
        writer, check, visual, review, publish = self.run_cmd('minor')
        writer.assert_not_called()                       # 칼럼니스트를 부르지 않는다
        self.assertEqual(check.call_args.args[:2], ('새 제목', EDITED.strip() + '\n'))
        visual.assert_not_called()                       # 교열본의 기존 그림은 그대로 둔다
        self.assertEqual(review.call_args.args[3], 'columns/x.png')
        publish.assert_not_called()
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ColumnDraft.STATUS_HOLD)
        self.assertEqual(self.draft.subject, '새 제목')
        self.assertIn('사람이 교열한 본문입니다.', self.draft.content)

    def test_accept_publishes(self):
        *_rest, publish = self.run_cmd('accept')
        publish.assert_called_once()

    def test_content_file_requires_review_only(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('office_revise', draft=self.draft.id, note='x', content_file=str(self.file),
                         stdout=mock.MagicMock())
