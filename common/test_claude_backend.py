import json
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase

from common.services import claude


def cli_result(result='답변', *, returncode=0, is_error=False, subtype='success'):
    payload = {'type': 'result', 'subtype': subtype, 'is_error': is_error, 'result': result,
               'usage': {'input_tokens': 10, 'output_tokens': 3}}
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr='')


def cli_env(**extra):
    env = {'CLAUDE_BACKEND': 'cli', 'CLAUDE_CLI_BIN': '/usr/bin/claude', 'ANTHROPIC_API_KEY': 'sk-ant-test'}
    env.update(extra)
    return mock.patch.dict('os.environ', env)


class CliBackendTests(SimpleTestCase):
    def setUp(self):
        claude._fallback_alerted = False
    def test_cli_answer_is_returned_without_touching_api(self):
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result('서울')) as run, \
                mock.patch('common.services.claude._get_client') as client:
            out = claude.ask('수도는?', system='페르소나', model=claude.ClaudeModel.SONNET_5_5)
        self.assertEqual(out, '서울')
        client.assert_not_called()
        cmd = run.call_args.args[0]
        self.assertIn('--system-prompt', cmd)
        self.assertEqual(cmd[cmd.index('--model') + 1], 'claude-sonnet-5-5')
        self.assertEqual(run.call_args.kwargs['input'], '수도는?')

    def test_api_key_is_never_passed_to_cli(self):
        # 키가 보이면 CLI 가 구독 대신 API 로 과금한다
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result()) as run:
            claude.ask('q')
        self.assertNotIn('ANTHROPIC_API_KEY', run.call_args.kwargs['env'])

    def test_usage_limit_falls_back_to_api_and_alerts_once(self):
        limited = cli_result('Claude AI usage limit reached', returncode=1, is_error=True)
        api = mock.Mock()
        api.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(type='text', text='API답')])
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=limited), \
                mock.patch('common.services.claude._get_client', return_value=api), \
                self.settings(ADMINS=[('Admin', 'admin@example.com')]):
            with claude.track_calls() as calls:
                self.assertEqual(claude.ask('q'), 'API답')
                claude.ask('q2')
        self.assertEqual(len(mail.outbox), 1)  # 같은 작업 안의 두 번째 폴백은 메일 생략
        self.assertIn('API 폴백 발생', mail.outbox[0].subject)
        self.assertIn('usage limit reached', mail.outbox[0].body)
        self.assertEqual([c['backend'] for c in calls], ['api', 'api'])
        self.assertTrue(all(c['fallback'] for c in calls))

    def test_tracker_records_cli_calls(self):
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result()):
            with claude.track_calls() as calls:
                claude.ask('q')
        self.assertEqual(calls[0]['backend'], 'cli')
        self.assertEqual(calls[0]['input_tokens'], 10)
        self.assertEqual(calls[0]['fallback'], '')
        self.assertEqual(len(mail.outbox), 0)

    def test_fallback_can_be_disabled(self):
        limited = cli_result('', returncode=1, is_error=True)
        with cli_env(CLAUDE_CLI_FALLBACK='false'), \
                mock.patch('common.services.claude.subprocess.run', return_value=limited), \
                mock.patch('common.services.claude._get_client') as client:
            with self.assertRaises(RuntimeError):
                claude.ask('q')
        client.assert_not_called()

    def test_oversized_system_prompt_moves_into_message(self):
        big = '가' * 40_000  # UTF-8 120KB → 인자 상한 초과
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result()) as run:
            claude.ask('본문', system=big)
        self.assertNotIn('--system-prompt', run.call_args.args[0])
        self.assertTrue(run.call_args.kwargs['input'].startswith(big))

    def test_default_backend_is_api(self):
        api = mock.Mock()
        api.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(type='text', text='ok')])
        with mock.patch.dict('os.environ', {}, clear=False), \
                mock.patch('common.services.claude.subprocess.run') as run, \
                mock.patch('common.services.claude._get_client', return_value=api):
            import os
            os.environ.pop('CLAUDE_BACKEND', None)
            self.assertEqual(claude.ask('q'), 'ok')
        run.assert_not_called()


class CliToolsTests(SimpleTestCase):
    def setUp(self):
        claude._fallback_alerted = False

    def test_no_tools_disables_everything(self):
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result()) as run:
            claude.ask('q')
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')
        self.assertNotIn('--allowedTools', cmd)

    def test_web_tools_are_enabled_and_allowed(self):
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result()) as run:
            claude.ask('q', tools=('WebSearch', 'WebFetch'))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index('--tools') + 1], 'WebSearch,WebFetch')
        i = cmd.index('--allowedTools')
        self.assertEqual(cmd[i + 1:i + 3], ['WebSearch', 'WebFetch'])

    def test_unsafe_tools_are_never_enabled(self):
        # 에이전트에게 파일 수정·셸 실행은 열지 않는다
        with cli_env(), mock.patch('common.services.claude.subprocess.run', return_value=cli_result()) as run:
            claude.ask('q', tools=('Bash', 'Edit', 'WebSearch'))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index('--tools') + 1], 'WebSearch')
        self.assertNotIn('Bash', cmd)
        self.assertNotIn('Edit', cmd)


class StandardModelTests(SimpleTestCase):
    def test_default_model_is_sonnet_5_5(self):
        self.assertEqual(str(claude.DEFAULT_MODEL), 'claude-sonnet-5-5')

    def test_empty_api_answer_is_retried_with_bigger_budget(self):
        calls = []

        def fake(prompt, *, system, model, max_tokens):
            calls.append(max_tokens)
            return ('' if len(calls) == 1 else '본문'), {}
        with mock.patch.dict('os.environ', {'CLAUDE_BACKEND': 'api'}), \
                mock.patch('common.services.claude._api_ask', side_effect=fake):
            self.assertEqual(claude.ask('q', max_tokens=3000), '본문')
        self.assertEqual(calls, [3000, 6000])
