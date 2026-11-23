"""칼럼별·단계별 토큰 사용량과 팩트체크 누수 신호(2026-11-23, office.token_usage)."""
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from office import token_usage as T
from office.models import ColumnDraft, StageRun

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}


def call(stage='check', inp=1000, out=200, **extra):
    tags = {'stage': stage, **extra.pop('tags', {})}
    return {'backend': 'cli', 'input_tokens': inp, 'output_tokens': out, 'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0, 'tags': tags, **extra}


class CallTokensTests(SimpleTestCase):
    def test_claude_cache_is_added_but_codex_cache_is_not(self):
        claude = T.call_tokens(call(inp=100, cache_read_input_tokens=900))
        codex = T.call_tokens({'backend': 'codex_cli', 'input_tokens': 1000, 'cached_input_tokens': 900, 'output_tokens': 5})
        self.assertEqual((claude['in'], claude['cache']), (1000, 900))
        self.assertEqual(codex['in'], 1000)

    def test_bloat_needs_a_known_prompt_size(self):
        self.assertTrue(T.bloated(T.call_tokens(call(inp=120_000, prompt_chars=10_000))))
        self.assertFalse(T.bloated(T.call_tokens(call(inp=120_000))))                 # 예전 기록은 판정하지 않아요
        self.assertFalse(T.bloated(T.call_tokens(call(inp=30_000, prompt_chars=20_000))))

    def test_call_tag_beats_the_stage_that_swept_it(self):
        self.assertEqual(T.group_of('revision_decision', call(stage='critique')), 'review')
        self.assertEqual(T.group_of('recheck', {'tags': {}}), 'fact')


class SummarizeTests(SimpleTestCase):
    def test_flags_repeat_many_unmeasured_and_bloat(self):
        run = uuid.uuid4()
        same = {'tags': {'body_hash': 'abc'}}
        rows = [{'run_id': run, 'stage': 'check', 'status': 'ok',
                 'calls': [call(**same), call(**same)] + [call(tags={'body_hash': f'h{i}'}) for i in range(4)]},
                {'run_id': run, 'stage': 'check', 'status': 'ok', 'calls': [call(inp=None)]},
                {'run_id': run, 'stage': 'critique', 'status': 'ok', 'calls': [call('critique', 150_000, prompt_chars=9_000)]}]
        s = T.summarize_draft(rows, body_chars=5000)
        kinds = {f['kind'] for f in s['flags']}
        self.assertEqual(kinds, {'repeat', 'many', 'unmeasured', 'bloat'})
        self.assertEqual(s['fact']['calls'], 7)
        self.assertEqual(s['fact']['per_1k'], round(6000 / 5000 * 1000))

    def test_retained_revision_counts_as_waste_once(self):
        run = uuid.uuid4()
        rows = [{'run_id': run, 'stage': 'revision_candidate', 'status': 'failed', 'calls': [call('revision_candidate', 500, 0)]},
                {'run_id': run, 'stage': 'revision_decision', 'status': 'ok', 'decision_status': 'retained',
                 'calls': [call('review', 300, 0)]}]
        s = T.summarize_draft(rows)
        self.assertEqual((s['retained_tokens'], s['wasted']), (800, 0))

    def test_outlier_against_the_median(self):
        cols = [{'fact': {'per_1k': v}, 'flags': []} for v in (100, 110, 120, 90, 100, 400)]
        T._mark_outliers(cols)
        self.assertEqual([c['flags'][0]['kind'] for c in cols if c['flags']], ['outlier'])
        self.assertEqual(cols[-1]['fact']['vs_median'], 3.8)


class TokenPageTests(TestCase):
    def setUp(self):
        otp = mock.patch('common.views._admin_otp_session_ok', return_value=True)
        otp.start()
        self.addCleanup(otp.stop)
        self.draft = ColumnDraft.objects.create(topic='hrd', subject='토큰을 보는 칼럼', content='가' * 4000, status='hold')
        StageRun.objects.create(run_id=uuid.uuid4(), draft=self.draft, seq=1, stage='check',
                                calls=[call(inp=8000, prompt_chars=6000, web_search_requests=3, num_turns=5)])
        StageRun.objects.create(run_id=uuid.uuid4(), draft=self.draft, seq=1, stage='draft',
                                calls=[call('draft', 12000, 9000)])

    def test_operator_sees_columns_groups_and_detail(self):
        self.client.force_login(User.objects.create_superuser('admin', '', 'x'))
        html = self.client.get(f'/lab/admin/tokens/?draft={self.draft.pk}', **UA).content.decode()
        self.assertIn('토큰을 보는 칼럼', html)
        self.assertIn('팩트체크', html)
        self.assertIn('8,000', html)
        self.assertIn('실행·단계별 호출', html)
        self.assertIn('3회 · 5턴', html)
        self.assertIn('href="/lab/admin/tokens/"', self.client.get('/lab/admin/', **UA).content.decode())

    def test_non_operator_is_refused(self):
        self.client.force_login(User.objects.create_user('member', '', 'x'))
        self.assertNotEqual(self.client.get('/lab/admin/tokens/', **UA).status_code, 200)
