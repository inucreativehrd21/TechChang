"""Claude 구독 → Codex 구독 라우팅. 한도 오류만 전환하며 유료 API를 호출하지 않는다."""
from __future__ import annotations

import os
from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from . import codex
from .cli_errors import ProviderUnavailable
from .cli_lock import codex_lock


def enabled():
    value = os.environ.get('AI_FALLBACK_BACKEND', '').strip().lower()
    if value not in ('', 'codex_cli'):
        raise RuntimeError('AI_FALLBACK_BACKEND는 비우거나 codex_cli로 설정해 주세요.')
    return value == 'codex_cli'


def paid_api_allowed():
    # Codex 폴백을 선택했으면 다른 설정과 무관하게 구독만 사용한다.
    return not enabled() and os.environ.get('AI_ALLOW_PAID_API', 'false').lower() == 'true'


def _states():
    from office.models import AiProviderState
    return AiProviderState.objects


def record_failure(exc):
    _states().get_or_create(provider=exc.provider)
    _states().filter(provider=exc.provider).update(**{
        'retry_at': exc.retry_at, 'failure_kind': exc.kind,
        'reason': str(exc)[:500], 'probe_until': None, 'updated_at': timezone.now(),
        'revision': F('revision') + 1,
    })


def available_after(now=None):
    """작업을 시작할 수 없는 경우에만 다음 확인 시각을 반환한다."""
    now = now or timezone.now()
    states = {s.provider: s for s in _states().all()}
    primary = states.get('claude')
    if not primary or not primary.retry_at or primary.retry_at <= now:
        return None
    if primary.failure_kind != 'limit':
        return primary.retry_at
    secondary = states.get('codex')
    if not secondary or not secondary.retry_at or secondary.retry_at <= now:
        return None
    return min(primary.retry_at, secondary.retry_at)


def _claim(provider, timeout):
    state, _ = _states().get_or_create(provider=provider)
    now = timezone.now()
    if state.retry_at and state.retry_at > now:
        raise ProviderUnavailable(state.reason or f'{provider} 재확인 대기 중이에요.',
                                  provider=provider, kind=state.failure_kind, retry_after=state.retry_at)
    if state.retry_at:
        # 한도 해제 직후 한 워커만 확인한다. 나머지는 Codex로 전환하거나 잠시 대기한다.
        claimed = _states().filter(provider=provider, revision=state.revision).filter(
            Q(probe_until__isnull=True) | Q(probe_until__lte=now)).update(
                probe_until=now + timedelta(seconds=timeout + 30))
        if not claimed:
            raise ProviderUnavailable(f'{provider} 복구를 다른 작업이 확인 중이에요.', provider=provider,
                                      kind=state.failure_kind, retry_after=now + timedelta(seconds=30))
    return state.revision


def _invoke(provider, fn, record, timeout):
    revision = _claim(provider, timeout)
    try:
        out, usage = fn()
    except ProviderUnavailable as exc:
        record_failure(exc)
        record['attempts'].append({'provider': provider, 'ok': False, 'kind': exc.kind})
        raise
    except Exception:
        _states().filter(provider=provider, revision=revision).update(probe_until=None)
        raise
    # 먼저 시작한 성공으로, 뒤에 발생한 다른 워커의 한도 기록을 지우지 않는다.
    _states().filter(provider=provider, revision=revision).update(
        retry_at=None, probe_until=None, failure_kind='', reason='', updated_at=timezone.now())
    record['attempts'].append({'provider': provider, 'ok': True})
    record.update(backend='cli' if provider == 'claude' else 'codex_cli', **usage)
    if provider == 'codex':
        record['model'] = codex.model_name()
    return out


def ask(primary, prompt, *, system, timeout, tools, record, output_schema=None, allow_fallback=True):
    if os.environ.get('CLAUDE_BACKEND', 'cli').lower() != 'cli':
        raise RuntimeError('Codex 폴백에는 CLAUDE_BACKEND=cli가 필요해요. 유료 API는 호출하지 않아요.')
    primary_timeout = timeout or int(os.environ.get('CLAUDE_CLI_TIMEOUT', '1200'))
    secondary_timeout = timeout or int(os.environ.get('CODEX_CLI_TIMEOUT', '1200'))
    try:
        return _invoke('claude', primary, record, primary_timeout)
    except ProviderUnavailable as exc:
        record['fallback'] = str(exc)[:500]
        if exc.kind != 'limit' or not allow_fallback:
            raise
    with codex_lock(timeout=int(os.environ.get('CODEX_LOCK_TIMEOUT', '1200'))):
        record['model'] = codex.model_name()
        return _invoke('codex', lambda: codex.ask(prompt, system=system, timeout=secondary_timeout,
                       tools=tools, output_schema=output_schema), record, secondary_timeout)
