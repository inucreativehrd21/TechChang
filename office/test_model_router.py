"""모델 선택은 호출 단위이고 독립 검증의 실패를 같은 모델로 숨기지 않는다."""
import os
from contextlib import nullcontext, suppress
from unittest import mock

from django.test import SimpleTestCase, TestCase

from common.services import claude, codex
from common.services.cli_errors import ProviderUnavailable
from office import model_router as R


class RoutingProfileTests(SimpleTestCase):
    def test_profile_a_upgrades_writers_and_preserves_low_cost_visual_role(self):
        with R.use_profile('a'):
            self.assertEqual(R.route_for('coding').model, 'claude-opus-5-5')
            self.assertEqual(R.route_for('charter').model, 'claude-sonnet-5-5')
            self.assertIsNone(R.route_for('checker').provider)

    def test_profile_b_separates_independent_verification(self):
        with R.use_profile('b'):
            self.assertEqual(R.route_for('coding').provider, 'claude')
            self.assertEqual(R.route_for('checker'), R.Route('gpt-6.1-sol', 'codex', 'high'))
            self.assertEqual(R.route_for('editor', stage='adjudicate').provider, 'codex')
            self.assertEqual(R.route_for('charter').model, 'gpt-6.1-sol')
            # 집필 전 근거 수집은 medium, 원고 독립 검증은 high (2026-10-31 Astra → Sol high)
            self.assertEqual(R.route_for('checker', purpose='gather'), R.Route('gpt-6.1-sol', 'codex', 'medium'))
            for stage in ('blueprint', 'check', 'reverify', 'recheck'):
                self.assertEqual(R.route_for('checker', stage=stage), R.Route('gpt-6.1-sol', 'codex', 'high'))
        with R.use_profile('a'):
            self.assertIsNone(R.route_for('checker', purpose='gather').provider)
        with R.use_profile('legacy'):
            self.assertEqual(R.route_for('checker').model, 'claude-sonnet-5-5')

    def test_blueprint_gathering_uses_research_model_in_worker_threads(self):
        from common.services.claude import _call_tags, call_tags
        from office import blueprint as B
        routes = []

        def ask_json(agent, prompt, **kw):
            tags = _call_tags.get()
            routes.append((tags.get('stage'), R.route_for(agent, stage=tags.get('stage', ''),
                                                          purpose=tags.get('purpose', '')).model))
            if 'thesis' in prompt:
                return {'thesis_ok': True}
            return {'claims': [{'claim': '값은 12.5%예요.', 'status': 'verified', 'value': '12.5%',
                                'quote': 'The value is 12.5%.', 'url': 'https://example.org/a'}]}

        bp = {'thesis': '답', 'claims': [{'claim': '값은 12.5%예요.', 'source': 'https://example.org/a'}]}
        from office.research_contract import ContractIncomplete
        with R.use_profile('b'), call_tags(stage='blueprint'), suppress(ContractIncomplete):
            B.verify_blueprint(bp, ask_json=ask_json)    # 범위 계약 판정은 이 테스트의 대상이 아니에요
        self.assertEqual(len(routes), 2)                  # 근거 수집 + 답 범위 판정
        self.assertEqual(set(routes), {('blueprint', 'gpt-6.1-sol')})   # 단계 집계 표식은 그대로

    def test_invalid_configuration_is_not_silently_downgraded(self):
        with mock.patch.dict(os.environ, {'OFFICE_MODEL_PROFILE': 'typo'}), self.assertRaises(ValueError):
            R.profile()


class DirectSubscriptionTests(TestCase):
    @mock.patch.dict(os.environ, {'CLAUDE_BACKEND': 'cli', 'AI_FALLBACK_BACKEND': 'codex_cli', 'AI_ALLOW_PAID_API': 'false'})
    def test_direct_codex_uses_requested_model_and_no_claude(self):
        with mock.patch('common.services.subscriptions.codex_lock', return_value=nullcontext()), \
                mock.patch.object(codex, 'ask', return_value=('검증 결과', {})) as request, \
                mock.patch.object(claude, '_cli_ask') as primary, \
                mock.patch.object(claude, '_api_ask') as api, claude.track_calls(alert=False) as calls:
            self.assertEqual(claude.ask('검증', provider='codex', model='gpt-6-astra', reasoning_effort='high'), '검증 결과')
        self.assertEqual(request.call_args.kwargs['model'], 'gpt-6-astra')
        self.assertEqual(request.call_args.kwargs['reasoning_effort'], 'high')
        self.assertEqual(calls[0]['model'], 'gpt-6-astra')
        self.assertEqual(calls[0]['requested_provider'], 'codex')
        primary.assert_not_called()
        api.assert_not_called()

    @mock.patch.dict(os.environ, {'CLAUDE_BACKEND': 'cli', 'AI_FALLBACK_BACKEND': 'codex_cli'})
    def test_independent_verification_failure_never_falls_back_to_writer(self):
        with mock.patch('common.services.subscriptions.codex_lock', return_value=nullcontext()), \
                mock.patch.object(codex, 'ask', side_effect=ProviderUnavailable('usage limit reached', provider='codex')), \
                mock.patch.object(claude, '_cli_ask') as primary, self.assertRaises(ProviderUnavailable):
            claude.ask('검증', provider='codex', model='gpt-6-astra')
        primary.assert_not_called()

    def test_direct_route_never_permits_api_or_privacy_bypass(self):
        with mock.patch.dict(os.environ, {'CLAUDE_BACKEND': 'api', 'AI_ALLOW_PAID_API': 'true'}), \
                mock.patch.object(claude, '_api_ask') as api, self.assertRaises(RuntimeError):
            claude.ask('q', provider='codex', model='gpt-6-astra')
        api.assert_not_called()
        with self.assertRaises(RuntimeError):
            claude.ask('q', provider='codex', model='gpt-6-astra', allow_codex=False)
