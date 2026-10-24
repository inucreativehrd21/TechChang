"""과금 차단·CLI 프로토콜·원 요청 보존·인증 잠금 회귀 검사. 실제 모델은 호출하지 않는다."""
from contextlib import nullcontext
from datetime import timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from common.services import claude, codex, subscriptions
from common.services.cli_errors import ProviderUnavailable, retry_at
from office.models import AiProviderState

ENV = {'CLAUDE_BACKEND': 'cli', 'CLAUDE_CLI_FALLBACK': 'false',
       'AI_FALLBACK_BACKEND': 'codex_cli', 'AI_ALLOW_PAID_API': 'false'}


def stream(*events, code=0, stderr=''):
    return SimpleNamespace(returncode=code, stdout='\n'.join(json.dumps(e) for e in events), stderr=stderr)


def answer(text='결과예요.'):
    return stream({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 40, 'output_tokens': 10}})


class CodexProtocolTests(SimpleTestCase):
    def test_eval_uses_production_json_rules_and_avoids_keyword_false_positives(self):
        from office.subscription_eval import CASES, check
        cases = {c['id']: c for c in CASES}
        self.assertEqual(check(cases['factcheck'], '```json\n{"valid": false, "correction": "100%예요."}\n```'), [])
        self.assertIn('요청한 항목 수 불일치', check(cases['decision'],
                      '{"summary": "N+1 캐시", "options": ["a", "b", "c"]}'))
        self.assertEqual(check(cases['logs'], '권한을 점검해요. chmod 777을 권장하지 않아요. ' * 20), [])

    def test_web_execution_is_recorded_separately_from_a_citation_in_text(self):
        proc = stream({'type': 'item.completed', 'item': {'type': 'web_search'}},
                      {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '확인 결과'}},
                      {'type': 'turn.completed', 'usage': {}})
        self.assertEqual(codex.parse_result(proc)[1]['web_search_calls'], 1)
        self.assertEqual(codex.parse_result(answer('https://docs.djangoproject.com'))[1]['web_search_calls'], 0)

    def test_only_a_completed_nonempty_turn_is_success(self):
        text, usage = codex.parse_result(answer())
        self.assertEqual(text, '결과예요.')
        self.assertEqual(usage['output_tokens'], 10)
        cases = [stream({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '중간'}}),
                 stream({'type': 'turn.completed'}),
                 stream({'type': 'turn.failed', 'error': {'message': 'usage limit reached'}}),
                 answer()]
        cases[-1].returncode = 1
        for proc in cases:
            with self.subTest(proc=proc), self.assertRaises(ProviderUnavailable):
                codex.parse_result(proc)
        with self.assertRaises(ProviderUnavailable):
            codex.parse_result(SimpleNamespace(returncode=0, stdout='not json', stderr=''))

    def test_limit_and_auth_errors_are_distinct(self):
        for message, expected in [('usage_limit_reached', 'limit'), ('rate limit exceeded', 'limit'),
                                  ('authentication failed', 'auth'), ('invalid token', 'auth')]:
            with self.subTest(message=message), self.assertRaises(ProviderUnavailable) as cm:
                codex.parse_result(stream({'type': 'turn.failed', 'error': {'message': message}}))
            self.assertEqual(cm.exception.kind, expected)

    def test_isolated_chatgpt_invocation_preserves_input_and_role(self):
        def run(cmd, **kwargs):
            if 'login' in cmd:
                return SimpleNamespace(returncode=0, stdout='Logged in using ChatGPT', stderr='')
            config = dict(arg.split('=', 1) for i, arg in enumerate(cmd) if i and cmd[i - 1] == '-c')
            self.assertEqual(json.loads(config['forced_login_method']), 'chatgpt')
            self.assertEqual(json.loads(config['model_provider']), 'openai')
            self.assertFalse(json.loads(config['features.shell_tool']))
            self.assertFalse(json.loads(config['features.multi_agent']))
            self.assertEqual(json.loads(config['web_search']), 'live')
            self.assertIn('검증관 역할', Path(json.loads(config['model_instructions_file'])).read_text(encoding='utf-8'))
            self.assertEqual(kwargs['input'], '원래 요청과 근거 묶음')
            self.assertIn('--ignore-user-config', cmd)
            self.assertIn('--strict-config', cmd)
            self.assertIn('--output-schema', cmd)
            for secret in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'DJANGO_DB_PASSWORD'):
                self.assertNotIn(secret, kwargs['env'])
            return answer()
        env = {'CODEX_CLI_BIN': 'codex', 'OPENAI_API_KEY': 'secret', 'CODEX_API_KEY': 'secret',
               'ANTHROPIC_API_KEY': 'secret', 'DJANGO_DB_PASSWORD': 'secret'}
        with mock.patch.dict(os.environ, env), mock.patch.object(codex.subprocess, 'run', side_effect=run):
            codex.ask('원래 요청과 근거 묶음', system='검증관 역할', tools=('WebSearch', 'WebFetch'),
                      output_schema={'type': 'object'})

    def test_no_web_tools_without_permission_and_unknown_tools_fail(self):
        with mock.patch.dict(os.environ, {'CODEX_CLI_BIN': 'codex'}), \
                mock.patch.object(codex, 'require_chatgpt_login'), \
                mock.patch.object(codex.subprocess, 'run', return_value=answer()) as run:
            codex.ask('q')
            self.assertIn('web_search="disabled"', run.call_args.args[0])
            with self.assertRaises(ProviderUnavailable):
                codex.ask('q', tools=('Bash',))
        self.assertEqual(run.call_count, 1)

    def test_missing_or_api_login_never_starts_a_model_request(self):
        for status, code in [('Not logged in', 1), ('Logged in using API key', 0)]:
            with self.subTest(status=status), mock.patch.dict(os.environ, {'CODEX_CLI_BIN': 'codex'}), \
                    mock.patch.object(codex.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=code, stdout=status, stderr='')) as run:
                with self.assertRaises(ProviderUnavailable) as cm:
                    codex.ask('q')
                self.assertEqual(cm.exception.kind, 'auth')
                self.assertEqual(run.call_count, 1)
                self.assertIn('login', run.call_args.args[0])

    def test_api_is_blocked_even_with_keys_and_legacy_fallback_enabled(self):
        env = {'AI_ALLOW_PAID_API': 'false', 'AI_FALLBACK_BACKEND': '', 'CLAUDE_BACKEND': 'api'}
        with mock.patch.dict(os.environ, env), mock.patch.object(claude, '_api_ask') as api:
            with self.assertRaises(RuntimeError):
                claude.ask('q')
            with self.assertRaises(RuntimeError):
                list(claude.ask_stream('q'))
        api.assert_not_called()
        with mock.patch.dict(os.environ, {**ENV, 'AI_ALLOW_PAID_API': 'true'}):
            with self.assertRaises(RuntimeError):
                claude._get_client()

    def test_iso_and_relative_reset_times(self):
        now = timezone.now()
        self.assertEqual(retry_at('try again in 7 minutes', now), now + timedelta(minutes=7))
        self.assertEqual(retry_at('retry_after_seconds: 45', now), now + timedelta(seconds=45))
        at = now + timedelta(hours=3)
        self.assertEqual(retry_at('usage limit; resets ' + at.isoformat(timespec='seconds'), now).replace(microsecond=0), at.replace(microsecond=0))


@mock.patch.dict(os.environ, ENV)
class SubscriptionRoutingTests(TestCase):
    def setUp(self):
        self.patches = [mock.patch.object(claude, '_alert_fallback'),
                        mock.patch('common.services.subscriptions.codex_lock', return_value=nullcontext()),
                        mock.patch.object(claude, '_api_ask')]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.addCleanup(self.mocks[-1].assert_not_called)

    def limit(self, provider='claude', **kwargs):
        return ProviderUnavailable('usage limit reached', provider=provider, **kwargs)

    def test_claude_success_never_calls_codex(self):
        with mock.patch.object(claude, '_cli_ask', return_value=('원래 결과', {})), \
                mock.patch.object(codex, 'ask') as secondary:
            self.assertEqual(claude.ask('q'), '원래 결과')
        secondary.assert_not_called()

    def test_call_scope_can_block_codex_without_allowing_an_api(self):
        with mock.patch.object(claude, '_cli_ask', side_effect=self.limit()), \
                mock.patch.object(codex, 'ask') as secondary:
            with self.assertRaises(ProviderUnavailable):
                claude.ask('masked logs', allow_codex=False)
        secondary.assert_not_called()

    def test_only_failed_call_retried_and_cooldown_shared_between_calls(self):
        with mock.patch.object(claude, '_cli_ask', side_effect=claude.CliUnavailable('session limit reached')) as primary, \
                mock.patch.object(codex, 'ask', return_value=('대체 결과', {})) as secondary, \
                claude.track_calls(alert=False) as calls:
            self.assertEqual(claude.ask('q', system='role', tools=('WebFetch',)), '대체 결과')
            self.assertEqual(claude.ask('next'), '대체 결과')
        self.assertEqual(primary.call_count, 1)
        self.assertEqual(secondary.call_count, 2)
        self.assertEqual(secondary.call_args_list[0].args, ('q',))
        self.assertEqual(secondary.call_args_list[0].kwargs['system'], 'role')
        self.assertEqual(secondary.call_args_list[0].kwargs['tools'], ('WebFetch',))
        self.assertEqual([c['backend'] for c in calls], ['codex_cli', 'codex_cli'])
        self.assertTrue(all(c['model'] == codex.DEFAULT_MODEL for c in calls))

    def test_auth_protocol_timeout_do_not_trigger_codex(self):
        for reason in ('authentication failed', '실행 오류: TimeoutExpired', '출력 해석 불가'):
            AiProviderState.objects.all().delete()
            with self.subTest(reason=reason), \
                    mock.patch.object(claude, '_cli_ask', side_effect=claude.CliUnavailable(reason)), \
                    mock.patch.object(codex, 'ask') as secondary:
                with self.assertRaises(ProviderUnavailable):
                    claude.ask('q')
            secondary.assert_not_called()

    def test_both_exhausted_blocks_until_first_provider_recheck(self):
        with mock.patch.object(claude, '_cli_ask', side_effect=self.limit()), \
                mock.patch.object(codex, 'ask', side_effect=self.limit('codex')):
            with self.assertRaises(ProviderUnavailable):
                claude.ask('q')
        self.assertIsNotNone(subscriptions.available_after())
        AiProviderState.objects.filter(provider='codex').update(retry_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(subscriptions.available_after())

    def test_primary_recovers_and_newer_failure_is_not_erased(self):
        subscriptions.record_failure(self.limit(retry_after=timezone.now() - timedelta(seconds=1)))
        with mock.patch.object(claude, '_cli_ask', return_value=('복귀', {})), mock.patch.object(codex, 'ask') as secondary:
            self.assertEqual(claude.ask('q'), '복귀')
        self.assertIsNone(AiProviderState.objects.get(pk='claude').retry_at)
        secondary.assert_not_called()
        def late_success():
            subscriptions.record_failure(self.limit())
            return '늦은 성공', {}
        rec = {'attempts': []}
        subscriptions._invoke('claude', late_success, rec, 30)
        self.assertIsNotNone(AiProviderState.objects.get(pk='claude').retry_at)

    def test_only_one_recovery_probe_claimed(self):
        subscriptions.record_failure(self.limit(retry_after=timezone.now() - timedelta(seconds=1)))
        subscriptions._claim('claude', 10)
        with self.assertRaises(ProviderUnavailable) as cm:
            subscriptions._claim('claude', 10)
        self.assertEqual(cm.exception.kind, 'limit')

    def test_subscription_mode_rejects_api_primary_even_if_paid_flag_is_true(self):
        with mock.patch.dict(os.environ, {'CLAUDE_BACKEND': 'api', 'AI_ALLOW_PAID_API': 'true'}):
            with self.assertRaises(RuntimeError):
                claude.ask('q')
