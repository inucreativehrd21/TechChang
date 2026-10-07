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

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from enum import Enum
from typing import Generator

from django.conf import settings

logger = logging.getLogger(__name__)


class ClaudeModel(str, Enum):
    """사용 가능한 Claude 모델 목록. (str 믹스인으로 Python 3.10 호환)"""
    HAIKU  = 'claude-haiku-4-5-20251001'   # 빠르고 저렴 - 단순 응답, Q&A 자동 답변
    SONNET = 'claude-sonnet-4-6'            # 균형 - 칼럼 작성, 분석, 기획
    SONNET_5 = 'claude-sonnet-5'            # (구) 오피스 에이전트 모델
    # 오피스 에이전트 팀(office 앱) 고정 모델. thinking 이 기본 adaptive 로 켜지고
    # effort 기본값이 high 라, 같은 프롬프트에서도 Sonnet 5 보다 초안 완성도가 올라간다.
    SONNET_5_5 = 'claude-sonnet-5-5'
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

    CLAUDE_BACKEND=cli 이면 API 대신 Claude Code CLI(구독)로 먼저 보내고,
    실패(사용량 한도·토큰 만료·CLI 없음)하면 API 로 넘어간다.
    """
    if os.environ.get(BACKEND_ENV, 'api').lower() == 'cli':
        try:
            return _cli_ask(prompt, system=system, model=model)
        except CliUnavailable as exc:
            if os.environ.get(FALLBACK_ENV, 'true').lower() == 'false':
                raise RuntimeError(f'Claude CLI 호출 실패(API 폴백 꺼짐): {exc}') from exc
            logger.warning('claude backend=cli 실패 → api 폴백: %s', exc)

    started = time.monotonic()
    client = _get_client()

    kwargs = dict(
        model=str(model),
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    if system:
        kwargs['system'] = system

    # 출력이 크면 비스트리밍 요청이 10분 제한에 걸린다 → 스트리밍으로 받아 이어 붙인다
    if max_tokens > 8000:
        parts = []
        with client.messages.stream(**kwargs) as stream:
            for chunk in stream.text_stream:
                parts.append(chunk)
        out = ''.join(parts)
    else:
        response = client.messages.create(**kwargs)
        # 최신 모델은 text 앞에 thinking 블록이 올 수 있다 → text 블록만 이어 붙인다
        out = ''.join(
            block.text for block in response.content
            if getattr(block, 'type', '') == 'text'
        )
    logger.info('claude backend=api model=%s %.1fs', model, time.monotonic() - started)
    return out


# ───────────────────────────── Claude Code CLI(구독) 백엔드
BACKEND_ENV = 'CLAUDE_BACKEND'        # 'api'(기본) | 'cli'
FALLBACK_ENV = 'CLAUDE_CLI_FALLBACK'  # 'false' 면 CLI 실패 시 API 로 넘기지 않고 예외
CLI_BIN_ENV = 'CLAUDE_CLI_BIN'        # cron 의 PATH 에 claude 가 없을 때 절대 경로
CLI_TIMEOUT = int(os.environ.get('CLAUDE_CLI_TIMEOUT', '1200'))
# 인자 하나의 길이 상한(Linux MAX_ARG_STRLEN 128KB) 아래로 여유를 둔다
_SYSTEM_ARG_LIMIT = 100_000


class CliUnavailable(Exception):
    """CLI 경로로 답을 받지 못함 — 호출부는 API 로 폴백한다."""


def _cli_ask(prompt: str, *, system: str, model: ClaudeModel | str) -> str:
    """
    `claude -p` 로 1회 호출. Claude Code 기본 시스템 프롬프트·도구·설정·MCP 를 모두 끄고
    빈 임시 디렉터리에서 돌려, API 호출과 같은 '시스템+사용자 메시지 1턴'만 남긴다.
    인증은 CLAUDE_CODE_OAUTH_TOKEN(`claude setup-token`) 또는 로그인 세션.
    """
    binary = os.environ.get(CLI_BIN_ENV) or shutil.which('claude')
    if not binary:
        raise CliUnavailable('claude 실행 파일을 찾을 수 없음')

    if len(system.encode('utf-8')) > _SYSTEM_ARG_LIMIT:
        prompt = f'{system}\n\n---\n\n{prompt}'
        system = ''

    cmd = [
        binary, '-p', '--output-format', 'json', '--model', str(model),
        '--tools', '', '--setting-sources', '', '--strict-mcp-config',
        '--disable-slash-commands', '--no-session-persistence',
    ]
    if system:
        cmd += ['--system-prompt', system]

    env = os.environ.copy()
    # API 키가 보이면 CLI 가 구독 대신 API 키로 과금한다 → 반드시 지운다
    env.pop('ANTHROPIC_API_KEY', None)
    env.pop(BACKEND_ENV, None)

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='claude-cli-') as cwd:
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding='utf-8',
                cwd=cwd, env=env, timeout=CLI_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CliUnavailable(f'실행 오류: {exc}') from exc

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise CliUnavailable(f'exit={proc.returncode} 출력 해석 불가: {(proc.stderr or proc.stdout)[:300]}')

    out = (data.get('result') or '').strip()
    if proc.returncode != 0 or data.get('is_error') or data.get('subtype') != 'success' or not out:
        raise CliUnavailable(f"exit={proc.returncode} subtype={data.get('subtype')} {out[:300]}")

    logger.info('claude backend=cli model=%s %.1fs in=%s out=%s', model, time.monotonic() - started,
                (data.get('usage') or {}).get('input_tokens'), (data.get('usage') or {}).get('output_tokens'))
    return out


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
