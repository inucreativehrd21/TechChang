import json
import os
import shutil
import tempfile
import threading
import time
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from office import pipeline as P
from office.models import ColumnDraft, StageRun

REFS = '\n\n## 참고 자료\n- 고용노동부, 2024\n- OECD, 2023\n- Gallup, 2024\n\n*테크창 연구팀*'


def column(pct: int) -> str:
    return ('리드 문단입니다.\n\n## 왜 지금인가\n' + '배경 설명입니다. ' * 80
            + f'\n\n## 숫자로 보는 현황\n응답자의 {pct}%가 동의했습니다. 기업 120곳을 봤습니다. 3배 차이입니다.'
            + '\n\n## 현장의 변화\n' + '사례 설명입니다. ' * 60
            + '\n\n## 시사점\n- 첫째입니다.\n\n## 맺음말\n정리합니다.' + REFS)


def qa(verdict, score):
    return {'verdict': verdict, 'score': score, 'length': 2500, 'fatal': [], 'issues': ['근거 보강'],
            'notes': '', 'scores': {}}


class PublishFlowTests(TestCase):
    """제작 명령의 재작성·재검증·단계 기록 (모델 호출은 가짜)."""

    def run_publish(self, *, editor_raw, reviews, checks=None):
        checks = list(checks or [{'verdict': 'pass', 'claims': []}] * 3)
        check_calls = []

        def fake_check(subject, content, recent):
            check_calls.append(content)
            return checks.pop(0) if checks else {'verdict': 'pass', 'claims': []}

        patches = [
            mock.patch.object(P, 'step_brief', return_value={'angle': '각도'}),
            mock.patch.object(P, 'step_draft', return_value=('제목', column(30))),
            mock.patch.object(P, 'precheck_draft', return_value=[]),
            mock.patch.object(P, 'step_check', side_effect=fake_check),
            mock.patch.object(P, 'step_critique', return_value={'verdict': 'recommend', 'issues': [], 'reason': ''}),
            mock.patch.object(P, 'step_review', side_effect=list(reviews)),
            mock.patch('office.management.commands.office_publish.ask_agent', return_value=editor_raw),
            mock.patch('office.management.commands.office_publish.call_command'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        call_command('office_publish', topic='data', no_chart=True, no_publish=True, stdout=StringIO())
        return ColumnDraft.objects.latest('id'), check_calls

    def test_truncated_editor_rewrite_keeps_previous_text(self):
        truncated = 'TITLE: 새 제목\n---\n잘린 원고입니다 그리고 끝맺지 않'
        draft, checks = self.run_publish(editor_raw=truncated, reviews=[qa('minor', 70)])
        self.assertIn('응답자의 30%', draft.content)
        self.assertEqual(draft.revisions, 0)
        failed = StageRun.objects.get(draft=draft, stage='editor_revise')
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(len(checks), 1)      # 재검증하지 않음

    def test_changed_figures_trigger_a_recheck(self):
        rewritten = 'TITLE: 제목\n---\n' + column(45)
        draft, checks = self.run_publish(editor_raw=rewritten, reviews=[qa('minor', 70), qa('accept', 85)])
        self.assertIn('응답자의 45%', draft.content)
        self.assertEqual(len(checks), 2)       # 최초 + 재작성 후 재검증
        stages = list(StageRun.objects.filter(draft=draft).values_list('stage', flat=True))
        for s in ('brief', 'draft', 'precheck', 'check', 'critique', 'review', 'editor_revise', 'reverify', 'final'):
            self.assertIn(s, stages)
        self.assertEqual(draft.status, ColumnDraft.STATUS_HOLD)   # --no-publish

    def test_unchanged_figures_skip_the_recheck(self):
        rewritten = 'TITLE: 제목\n---\n' + column(30).replace('리드 문단입니다.', '고친 리드입니다.')
        draft, checks = self.run_publish(editor_raw=rewritten, reviews=[qa('minor', 70), qa('accept', 85)])
        self.assertEqual(len(checks), 1)
        self.assertFalse(StageRun.objects.filter(draft=draft, stage='reverify').exists())


class ConcurrentSpoolTests(TestCase):
    def setUp(self):
        self.spool = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.spool, True)

    def test_two_concurrent_requests_get_their_own_replies(self):
        from office import services as S

        stop = threading.Event()

        def answerer():
            answered = set()
            while not stop.is_set():
                for n in os.listdir(self.spool):
                    if n.startswith('req.') and n.endswith('.json'):
                        meta = json.load(open(os.path.join(self.spool, n), encoding='utf-8'))
                        if meta['seq'] in answered:
                            continue
                        answered.add(meta['seq'])
                        open(os.path.join(self.spool, f"reply.{meta['seq']}.md"), 'w',
                             encoding='utf-8').write(f"{meta['agent']} 답")
                time.sleep(0.02)

        results = {}
        with mock.patch.dict(os.environ, {S.SPOOL_ENV: self.spool}), \
                mock.patch.object(S, 'ask', side_effect=AssertionError('API 호출됨')):
            t = threading.Thread(target=answerer)
            t.start()
            workers = [threading.Thread(target=lambda k=k: results.__setitem__(k, S.ask_agent(k, f'{k} 지시')))
                       for k in ('checker', 'critic')]
            for w in workers:
                w.start()
            for w in workers:
                w.join(timeout=20)
            stop.set()
            t.join()
        self.assertEqual(results, {'checker': 'checker 답', 'critic': 'critic 답'})
        done = sorted(n for n in os.listdir(self.spool) if n.endswith('.prompt.md'))
        self.assertEqual(done, ['done.1.prompt.md', 'done.2.prompt.md'])
        self.assertFalse(os.path.exists(os.path.join(self.spool, 'pending.md')))
