"""remake_column --content-file — 사람 교열본을 심사·보완하되, 근거에 없는 수치는 되살아나지 못한다."""
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
          'ICF는 실무자를 122,974명으로 집계했습니다.\n\n'
          '| 지표 | 값 | 출처 |\n|---|---|---|\n| 실무자 | 122,974명 | ICF 2025 |\n')
FACTS = 'ICF 2025: "A record 122,974 coach practitioners worldwide" (https://coachingfederation.org/x)'


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

    def run_cmd(self, reviews, patch_result=None):
        patch_result = patch_result or ('새 제목', EDITED, False, '불일치')
        with mock.patch(f'{CMD}.P.step_check', return_value={'verdict': 'pass'}) as check, \
             mock.patch(f'{CMD}.P.step_critique', return_value={'verdict': 'pass', 'issues': []}), \
             mock.patch(f'{CMD}.P.step_review', side_effect=reviews) as rv, \
             mock.patch(f'{CMD}.P.step_visual') as visual, \
             mock.patch(f'{CMD}.ask_agent', return_value='') as writer, \
             mock.patch('office.patching.patch_revise', return_value=patch_result) as patch, \
             mock.patch(f'{CMD}.log'), mock.patch(f'{CMD}.call_command'):
            call_command('remake_column', question=self.q.pk, content_file=self.path, subject='새 제목',
                         facts=FACTS, stdout=StringIO())
        return check, rv, visual, writer, patch

    def test_accepted_edit_replaces_in_place_without_rewriting(self):
        check, rv, visual, writer, patch = self.run_cmd([qa('accept', 82)])
        self.q.refresh_from_db()
        self.assertEqual((self.q.subject, self.q.content), ('새 제목', EDITED.strip()))
        writer.assert_not_called()
        patch.assert_not_called()
        visual.assert_not_called()          # 교열본의 표를 그대로 심사
        self.assertIn('122,974', check.call_args.kwargs['verified'])
        self.assertIn('122,974', rv.call_args.kwargs['verified'])

    def test_minor_edit_is_patched_and_numbers_from_memory_are_dropped(self):
        # 보완 패치가 근거에 없는 수치(10,035건)를 들여와도 그 문장은 지워지고, 재심 통과면 갱신된다
        patched = EDITED.replace('집계했습니다.', '집계했습니다. 응답은 10,035건이었습니다.')
        _c, rv, visual, _w, patch = self.run_cmd([qa('minor', 74), qa('accept', 83)],
                                                 patch_result=('새 제목', patched, True, '패치 1건'))
        self.q.refresh_from_db()
        patch.assert_called_once()
        self.assertIn('122,974명으로 집계했습니다.', self.q.content)
        self.assertNotIn('10,035', self.q.content)
        visual.assert_not_called()          # 보완 뒤에도 교열본 표를 지킨다
        self.assertEqual(rv.call_args.kwargs['previous_content'].strip(), EDITED.strip())

    def test_still_failing_edit_keeps_original(self):
        self.run_cmd([qa('minor', 74)])                     # 패치·재작성 모두 실패
        self.q.refresh_from_db()
        self.assertEqual((self.q.subject, self.q.content), ('옛 제목', '옛 본문'))
