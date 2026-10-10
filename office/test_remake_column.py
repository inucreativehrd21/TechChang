"""remake_column --content-file — 사람 교열본은 재작성 없이 심사만 받고, 통과해야만 제자리 갱신된다."""
import os
import tempfile
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question

CMD = 'office.management.commands.remake_column'
EDITED = ('교육 담당자의 실제 장면으로 시작하는 도입 문단입니다.\n\n## 숫자로 보는 현황\n\n'
          '| 지표 | 값 | 출처 |\n|---|---|---|\n| 실무자 | 122,974명 | ICF 2025 |\n')


def qa(verdict, score):
    return {'verdict': verdict, 'score': score, 'length': 1000, 'fatal': [], 'issues': [], 'must_fix': []}


class HandEditReviewTests(TestCase):
    def setUp(self):
        bot, _ = User.objects.get_or_create(username='techchang연구팀')
        cat, _ = Category.objects.get_or_create(name='HRD')
        self.q = Question.objects.create(author=bot, category=cat, subject='옛 제목', content='옛 본문',
                                         create_date=timezone.now())
        fd, self.path = tempfile.mkstemp(suffix='.md')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(EDITED)
        self.addCleanup(os.remove, self.path)

    def run_cmd(self, review):
        with mock.patch(f'{CMD}.P.step_check', return_value={'verdict': 'pass'}) as check, \
             mock.patch(f'{CMD}.P.step_critique', return_value={'verdict': 'pass', 'issues': []}), \
             mock.patch(f'{CMD}.P.step_review', return_value=review) as rv, \
             mock.patch(f'{CMD}.P.step_visual') as visual, \
             mock.patch(f'{CMD}.ask_agent') as writer, \
             mock.patch('office.patching.patch_revise') as patch, \
             mock.patch(f'{CMD}.log'), mock.patch(f'{CMD}.call_command'):
            call_command('remake_column', question=self.q.pk, content_file=self.path, subject='새 제목',
                         facts='ICF 2025: 122,974명', stdout=StringIO())
        return check, rv, visual, writer, patch

    def test_accepted_edit_replaces_in_place_without_rewriting(self):
        check, rv, visual, writer, patch = self.run_cmd(qa('accept', 82))
        self.q.refresh_from_db()
        self.assertEqual((self.q.subject, self.q.content), ('새 제목', EDITED.strip()))
        writer.assert_not_called()
        visual.assert_not_called()          # 교열본의 표를 그대로 심사
        self.assertEqual(check.call_args.kwargs['verified'], 'ICF 2025: 122,974명')
        self.assertEqual(rv.call_args.kwargs['verified'], 'ICF 2025: 122,974명')

    def test_rejected_edit_keeps_original_and_is_not_rewritten(self):
        _check, _rv, _visual, writer, patch = self.run_cmd(qa('minor', 74))
        self.q.refresh_from_db()
        self.assertEqual((self.q.subject, self.q.content), ('옛 제목', '옛 본문'))
        writer.assert_not_called()
        patch.assert_not_called()
