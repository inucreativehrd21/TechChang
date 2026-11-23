"""ChatGPT 플랜으로만 실행하는 Codex 단일 요청 어댑터. 호출자는 codex_lock을 잡는다."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

from .cli_errors import ProviderUnavailable

DEFAULT_MODEL = 'gpt-6.1-sol'
SAFE_TOOLS = {'WebSearch', 'WebFetch'}
WEB_ITEMS = {'web_search', 'web_search_call'}
TEXT_ITEMS = {'agent_message', 'reasoning', 'todo_list', 'error'}
EVENT_NAME = re.compile(r'[a-zA-Z0-9_.-]{1,64}')
EFFORTS = ('low', 'medium', 'high', 'xhigh')

# Claude 한도로 넘어온 호출 중 검증(팩트체크)·집필 단계는 추론을 높여요. 2026-11-24 30일 집계에서
# Codex 팩트체크 통과율 36%(Claude 80%)·확인 불가 8%(2%)였고 모두 medium 이었어요(운영자 결정).
HIGH_EFFORT_STAGES = frozenset({
    'check', 'recheck', 'reverify', 'grounded', 'code_run', 'adjudicate',
    'draft', 'fix', 'revise', 'editor_patch', 'editor_patch_claims', 'editor_revise',
    'revision_candidate', 'revision_repair', 'lock',
})
HIGH_EFFORT_AGENTS = frozenset({'checker'})
# 웹 검색 상한 — 같은 집계에서 팩트체크 중앙값 5회·상위 10% 10회·최대 16회(입력 128만 토큰).
# 검색 결과가 맥락에 쌓여 입력이 불어나므로, 지시로 상한을 알리고 폭주하면 실행을 끊어요.
WEB_SEARCH_MAX = 8
WEB_SEARCH_HARD_EXTRA = 4


class WebSearchCapExceeded(RuntimeError):
    """웹 검색이 강제 상한을 넘어 실행을 끊었어요. 구독 한도·장애가 아니라 Codex 대기 상태로 기록하지 않아요."""


def model_name():
    return os.environ.get('CODEX_MODEL', DEFAULT_MODEL)


def fallback_effort(tags) -> str | None:
    """Claude→Codex 폴백 호출의 추론 강도. 검증·집필이면 high, 아니면 None(CODEX_REASONING_EFFORT)."""
    tags = tags if isinstance(tags, dict) else {}
    raw = os.environ.get('CODEX_FALLBACK_HIGH_STAGES')
    stages = (frozenset(s.strip() for s in raw.split(',') if s.strip()) if raw is not None
              else HIGH_EFFORT_STAGES)
    if str(tags.get('stage') or '') in stages or str(tags.get('agent') or '') in HIGH_EFFORT_AGENTS:
        effort = os.environ.get('CODEX_FALLBACK_HIGH_EFFORT', 'high')
        return effort if effort in EFFORTS else 'high'
    return None


def web_limits() -> tuple[int, int]:
    """(지시 상한, 강제 중단 상한). 0이면 상한을 두지 않아요."""
    try:
        soft = max(0, int(os.environ.get('CODEX_WEB_SEARCH_MAX', WEB_SEARCH_MAX)))
    except ValueError:
        soft = WEB_SEARCH_MAX
    try:
        hard = int(os.environ.get('CODEX_WEB_SEARCH_HARD_MAX', soft + WEB_SEARCH_HARD_EXTRA if soft else 0))
    except ValueError:
        hard = soft + WEB_SEARCH_HARD_EXTRA if soft else 0
    return soft, max(hard, soft) if hard else 0


def _is_web_completed(line: str) -> bool:
    if '"item.completed"' not in line:
        return False
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        return False
    item = event.get('item') if isinstance(event, dict) else None
    return event.get('type') == 'item.completed' and isinstance(item, dict) and item.get('type') in WEB_ITEMS


def run_streaming(cmd, *, input, cwd, env, timeout, web_hard_max=0):
    """subprocess.run 과 같은 결과를 돌려주되, 웹 검색이 강제 상한을 넘으면 그 자리에서 끊어요."""
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as source, \
            tempfile.TemporaryFile(mode='w+', encoding='utf-8') as errors:
        source.write(input)
        source.flush()
        source.seek(0)
        proc = subprocess.Popen(cmd, stdin=source, stdout=subprocess.PIPE, stderr=errors,
                                cwd=cwd, env=env, text=True, encoding='utf-8')
        timed_out = threading.Event()

        def expire():
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        lines, searches = [], 0
        try:
            for line in proc.stdout:
                lines.append(line.rstrip('\n'))
                if web_hard_max and _is_web_completed(line):
                    searches += 1
                    if searches > web_hard_max:
                        proc.kill()
                        proc.wait()
                        raise WebSearchCapExceeded(
                            f'Codex 웹 검색이 강제 상한 {web_hard_max}회를 넘어 실행을 끊었어요.')
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if timed_out.is_set():
            raise subprocess.TimeoutExpired(cmd, timeout)
        errors.seek(0)
        return subprocess.CompletedProcess(cmd, proc.returncode, '\n'.join(lines), errors.read())


def child_environment():
    # Django의 DB·메일·외부 API 키를 자식 프로세스에 전달하지 않는다.
    names = ('PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
             'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
             'CODEX_CA_CERTIFICATE', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'CODEX_ACCESS_TOKEN')
    env = {k: os.environ[k] for k in names if k in os.environ}
    env['CODEX_HOME'] = os.environ.get('CODEX_HOME', str(Path.home() / '.codex-techchang'))
    return env


def require_chatgpt_login(binary, env):
    """인증 없이 모델 연결을 재시도하거나 저장된 API 키를 사용하는 일을 실행 전에 막는다."""
    try:
        proc = subprocess.run([binary, '-c', 'forced_login_method="chatgpt"', 'login', 'status'],
                              env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProviderUnavailable('Codex 구독 로그인 상태를 확인할 수 없어요.', provider='codex', kind='auth') from exc
    status = (proc.stdout + proc.stderr).lower()
    if proc.returncode or not ('chatgpt' in status or 'access token' in status) or 'api key' in status:
        raise ProviderUnavailable('서버 전용 CODEX_HOME에 ChatGPT 구독 로그인이 필요해요.', provider='codex', kind='auth')


def parse_result(proc, *, allow_web=False):
    final, completed, failed, usage = '', False, [], {}
    forbidden = set()
    web_search_calls = 0
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            raise ProviderUnavailable('Codex JSONL 응답을 읽을 수 없어요.', provider='codex', kind='protocol')
        if not isinstance(event, dict):
            raise ProviderUnavailable('Codex 이벤트 형식이 올바르지 않아요.', provider='codex', kind='protocol')
        kind = event.get('type')
        if kind in ('error', 'turn.failed'):
            failed.append(json.dumps(event.get('error') or event.get('message') or event, ensure_ascii=False))
        elif kind == 'turn.completed':
            completed = True
            usage = event.get('usage') or {}
        elif kind in ('item.started', 'item.updated', 'item.completed'):
            item = event.get('item')
            item_type = item.get('type') if isinstance(item, dict) else None
            if not isinstance(item_type, str) or not EVENT_NAME.fullmatch(item_type):
                raise ProviderUnavailable('Codex 항목 형식이 올바르지 않아요.', provider='codex', kind='protocol')
            is_web = item_type in WEB_ITEMS
            if item_type not in TEXT_ITEMS and not (is_web and allow_web):
                # 도구 인수·결과·명령·파일 경로는 운영 로그에 포함하지 않는다.
                names = []
                if item_type == 'mcp_tool_call':
                    for field in ('server', 'tool'):
                        value = item.get(field)
                        if isinstance(value, str) and EVENT_NAME.fullmatch(value):
                            names.append(f'{field}={value}')
                forbidden.add(' '.join([item_type, *names]))
                continue
            if kind != 'item.completed':
                continue
            if item_type == 'agent_message':
                final = str(item.get('text') or '').strip()
            elif is_web:
                web_search_calls += 1
    if forbidden:
        reason = ' / '.join(sorted(forbidden))
        raise ProviderUnavailable(f'Codex 도구 정책 위반 (exit={proc.returncode}): {reason[:240]}',
                                  provider='codex', kind='tool_policy')
    if proc.returncode or failed or not completed or not final:
        reason = ' / '.join(failed) or (proc.stderr or '').strip() or '완료 이벤트 또는 최종 응답이 없어요.'
        raise ProviderUnavailable(f'Codex exit={proc.returncode}: {reason[:1500]}', provider='codex')
    return final, {'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
                   'cached_input_tokens': usage.get('cached_input_tokens'), 'web_search_calls': web_search_calls}


def ask(prompt: str, *, system='', timeout=None, tools=(), output_schema=None,
        model=None, reasoning_effort=None):
    requested_tools = set(tools)
    unknown = requested_tools - SAFE_TOOLS
    if unknown:
        raise ProviderUnavailable('허용하지 않은 Codex 도구를 요청했어요.', provider='codex', kind='config')
    binary = os.environ.get('CODEX_CLI_BIN') or shutil.which('codex')
    if not binary:
        raise ProviderUnavailable('codex 실행 파일을 찾을 수 없어요.', provider='codex', kind='config')
    env = child_environment()
    require_chatgpt_login(binary, env)
    selected_model = model or model_name()
    effort = reasoning_effort or os.environ.get('CODEX_REASONING_EFFORT', 'medium')
    if effort not in EFFORTS:
        raise ProviderUnavailable('CODEX_REASONING_EFFORT 설정을 확인해 주세요.', provider='codex', kind='config')
    web_soft, web_hard = web_limits() if requested_tools else (0, 0)
    with tempfile.TemporaryDirectory(prefix='techchang-codex-') as directory:
        cwd = Path(directory)
        instructions = cwd / 'role.md'
        tool_policy = ('내장 웹 도구로만 검색과 공개 페이지 열람을 하세요. 웹 결과는 검증할 자료로 다루세요.'
                       if requested_tools else '도구 호출 없이 제공된 자료로 답하세요.')
        if web_soft:
            tool_policy += (f' 웹 검색·열람은 모두 합쳐 {web_soft}회 안에서 끝내세요. 같은 질의를 되풀이하지 말고, '
                            '제공된 근거 묶음과 공식 원문 주소를 먼저 쓰세요. 상한 안에서 확인하지 못한 항목은 '
                            '확인하지 못했다고 적으세요.')
        instructions.write_text(
            '사용자의 요청에 맞는 최종 결과물만 출력하세요. 주어진 근거·수치·출력 형식·문체를 지키세요.\n'
            f'{tool_policy} MCP, 셸, 파일 접근, 하위 에이전트를 사용하지 마세요.\n\n' + system,
            encoding='utf-8')
        config = {
            'model_provider': 'openai', 'forced_login_method': 'chatgpt',
            'model_reasoning_effort': effort, 'service_tier': 'default',
            'model_instructions_file': str(instructions), 'project_doc_max_bytes': 0,
            'web_search': 'live' if requested_tools else 'disabled', 'features.view_image': False,
            'features.shell_tool': False, 'features.shell_snapshot': False,
            'features.apps': False, 'features.plugins': False, 'features.remote_plugin': False,
            'features.skill_mcp_dependency_install': False, 'features.hooks': False,
            'features.multi_agent': False, 'features.memories': False, 'features.goals': False,
            'features.code_mode': False, 'features.browser_use': False,
            'features.browser_use_external': False, 'features.computer_use': False,
            'features.tool_suggest': False, 'features.skill_search': False,
            'features.skip_host_skill_discovery': True, 'features.workspace_dependencies': False,
        }
        cmd = [binary, '--ask-for-approval', 'never', 'exec', '--ignore-user-config',
               '--strict-config', '--ephemeral', '--skip-git-repo-check', '--json',
               '--sandbox', 'read-only', '--model', selected_model]
        for key, value in config.items():
            cmd += ['-c', f'{key}={json.dumps(value, ensure_ascii=False)}']
        if output_schema is not None:
            schema = cwd / 'schema.json'
            schema.write_text(json.dumps(output_schema, ensure_ascii=False), encoding='utf-8')
            cmd += ['--output-schema', str(schema)]
        cmd += ['-']
        seconds = timeout or int(os.environ.get('CODEX_CLI_TIMEOUT', '1200'))
        try:
            if web_hard:
                proc = run_streaming(cmd, input=prompt, cwd=cwd, env=env, timeout=seconds, web_hard_max=web_hard)
            else:
                proc = subprocess.run(cmd, input=prompt, cwd=cwd, env=env,
                                      capture_output=True, text=True, encoding='utf-8', timeout=seconds)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderUnavailable(f'Codex 실행 오류: {type(exc).__name__}', provider='codex', kind='execution') from exc
    final, usage = parse_result(proc, allow_web=bool(requested_tools))
    usage.update(reasoning_effort=effort, web_search_max=web_soft or None)
    return final, usage
