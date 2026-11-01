"""연구원 모델 선택과 장애 폴백을 분리한다. 환경은 호출 중 변경하지 않는다."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os

_profile = ContextVar('office_model_profile', default=None)


def profile() -> str:
    value = _profile.get() or os.environ.get('OFFICE_MODEL_PROFILE', 'a').strip().lower()
    if value not in ('legacy', 'a', 'b'):
        raise ValueError('OFFICE_MODEL_PROFILE은 legacy, a, b 중 하나여야 해요.')
    return value


@contextmanager
def use_profile(value: str):
    if value not in ('legacy', 'a', 'b'):
        raise ValueError('알 수 없는 연구실 모델 프로필이에요.')
    token = _profile.set(value)
    try:
        yield
    finally:
        _profile.reset(token)


@dataclass(frozen=True)
class Route:
    model: str
    provider: str | None = None
    effort: str | None = None

    def kwargs(self) -> dict:
        result = {'model': self.model}
        if self.provider:
            result.update(provider=self.provider, reasoning_effort=self.effort)
        return result


def route_for(agent: str, *, stage: str = '', purpose: str = '') -> Route:
    selected = profile()
    if selected == 'legacy':
        return Route('claude-sonnet-5-5')
    if selected == 'b':
        # 집필 전 근거 수집(purpose='gather', office.blueprint)은 조사예요. 원고의 독립 검증(check·reverify·중재)은
        # Sol high 가 맡아요. 2026-10-31 파일럿: Astra high 는 오류를 잘 잡았지만 한 편에 Codex 5시간 한도의 절반
        # 가까이를 써서, 20달러 구독에서는 Sol high 로 바꿨어요(운영자 결정). 원문 문장 대조 규칙
        # (evidence._check_item)과 범위 계약은 모델과 무관하게 그대로 적용돼요.
        if agent == 'checker' and purpose == 'gather':
            return Route('gpt-6.1-sol', 'codex', 'medium')
        if agent == 'checker' or stage == 'adjudicate':
            return Route('gpt-6.1-sol', 'codex', 'high')
        if agent in ('research', 'charter'):
            return Route('gpt-6.1-sol', 'codex', 'medium')
        return Route('claude-opus-5-5', 'claude')
    return Route('claude-sonnet-5-5' if agent == 'charter' else 'claude-opus-5-5')
