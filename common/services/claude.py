"""
테크창 Claude API 공용 클라이언트

프로젝트 어디서든 Claude를 호출할 때 이 모듈을 사용합니다.

사용 예시:
    from common.services.claude import ask, ask_stream

    # 단순 텍스트 생성
    reply = ask("파이썬의 장점을 설명해줘")

    # 시스템 프롬프트 + 모델 지정
    reply = ask(
        prompt="이 Q&A에 답변해줘: ...",
        system="당신은 HRD 전문가입니다.",
        model=ClaudeModel.SONNET,
    )

    # 스트리밍 (제너레이터)
    for chunk in ask_stream("긴 칼럼을 작성해줘"):
        print(chunk, end="", flush=True)
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Generator

from django.conf import settings


class ClaudeModel(str, Enum):
    """사용 가능한 Claude 모델 목록. (str 믹스인으로 Python 3.10 호환)"""
    HAIKU  = 'claude-haiku-4-5-20251001'   # 빠르고 저렴 - 단순 응답, Q&A 자동 답변
    SONNET = 'claude-sonnet-4-6'            # 균형 - 칼럼 작성, 분석, 기획
    OPUS   = 'claude-opus-4-8'             # 최고 성능 - 복잡한 추론, 장문 심층 분석

    def __str__(self):
        return self.value


DEFAULT_MODEL = ClaudeModel.SONNET


def _get_client():
    """Anthropic 클라이언트를 반환. API 키가 없으면 RuntimeError."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            'anthropic 패키지가 설치되어 있지 않습니다.\n'
            'pip install "anthropic>=0.40.0" 를 실행하세요.'
        )

    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '') or os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        raise RuntimeError(
            'ANTHROPIC_API_KEY가 설정되지 않았습니다.\n'
            '.env 파일에 ANTHROPIC_API_KEY=sk-ant-... 를 추가하세요.'
        )

    return anthropic.Anthropic(api_key=api_key)


def ask(
    prompt: str,
    *,
    system: str = '',
    model: ClaudeModel | str = DEFAULT_MODEL,
    max_tokens: int = 2048,
) -> str:
    """
    Claude에게 단일 질문을 보내고 응답 문자열을 반환합니다.

    Args:
        prompt:     사용자 메시지
        system:     시스템 프롬프트 (선택)
        model:      ClaudeModel 열거형 또는 모델 ID 문자열
        max_tokens: 최대 출력 토큰 수

    Returns:
        Claude의 응답 텍스트

    Raises:
        RuntimeError: API 키 미설정 또는 anthropic 패키지 없음
    """
    client = _get_client()

    kwargs = dict(
        model=str(model),
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    if system:
        kwargs['system'] = system

    response = client.messages.create(**kwargs)
    return response.content[0].text


def ask_stream(
    prompt: str,
    *,
    system: str = '',
    model: ClaudeModel | str = DEFAULT_MODEL,
    max_tokens: int = 2048,
) -> Generator[str, None, None]:
    """
    Claude 응답을 스트리밍으로 반환하는 제너레이터입니다.

    사용 예시 (Django view):
        from django.http import StreamingHttpResponse
        from common.services.claude import ask_stream

        def my_view(request):
            return StreamingHttpResponse(
                ask_stream("긴 글을 써줘"),
                content_type='text/plain; charset=utf-8',
            )
    """
    client = _get_client()

    kwargs = dict(
        model=str(model),
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    if system:
        kwargs['system'] = system

    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield text


def ask_json(
    prompt: str,
    *,
    system: str = '',
    model: ClaudeModel | str = DEFAULT_MODEL,
    max_tokens: int = 2048,
) -> dict:
    """
    JSON 응답을 기대하는 요청에 사용합니다.
    Claude가 ```json ... ``` 블록으로 응답하면 자동으로 파싱합니다.

    Raises:
        ValueError: JSON 파싱 실패 시
    """
    import json
    import re

    raw = ask(prompt, system=system, model=model, max_tokens=max_tokens)

    # ```json ... ``` 블록 추출
    match = re.search(r'```(?:json)?\s*([\s\S]+?)```', raw)
    json_str = match.group(1).strip() if match else raw.strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Claude 응답을 JSON으로 파싱할 수 없습니다: {exc}\n원본: {raw[:200]}')
