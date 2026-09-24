"""
정비반 파이프라인 — 작업 카드 하나를 PR 까지 끌고 간다.

  0) 분류(triage)   윤성이 우선순위·난이도·완료 조건을 정리 (이슈 본문에 쓰인다)
  1) 관련 파일 수집  저장소를 grep 해서 후보 파일을 찾는다 (모델이 탐색에 시간을 쓰지 않게)
  2) 조사·패치      후보 파일 내용을 그대로 주고, 수정안을 구조화된 JSON(edits)으로 받는다
  3) 적용           git worktree(격리 사본)에서만 수정한다. 운영 코드는 건드리지 않는다
  4) 검증           그 사본에서 manage.py check + test 실행. 실패하면 오류를 물려 최대 2회 재시도
  5) PR             브랜치 push → PR 생성 (머지·배포는 사람)

안전장치
  - 수정 대상은 저장소 안의 허용 확장자 파일만. .env·media·secrets·.github/workflows 는 금지
  - 파일 생성/치환만 허용(삭제 없음), 한 번에 최대 8개 파일
  - 운영 서비스는 절대 재시작하지 않는다
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from django.conf import settings
from django.utils import timezone

from .services import ask_agent, ask_agent_json, log

REPO = str(settings.BASE_DIR)
MAX_FILES = 8
MAX_FILE_CHARS = 14000
VERIFY_TIMEOUT = 600

ALLOW_EXT = {'.py', '.html', '.css', '.js', '.txt', '.md', '.json', '.cfg', '.ini'}
DENY_PARTS = ('.env', 'media/', 'staticfiles/', 'secrets', 'db.sqlite3', '.github/workflows',
              'backups/', 'logs/', 'node_modules/', '.git/')

# ───────────────────────────── 프롬프트
TRIAGE_PROMPT = (
    '정비 작업 카드를 분류하세요.\n\n[제목] {title}\n[내용]\n{body}\n[출처] {source}\n\n'
    '출력 JSON: {{"kind": "dev|ops|bug|chore", "priority": "P1|P2|P3", '
    '"summary": "한 문장 요약", "acceptance": ["완료 조건", ...2~4개], '
    '"keywords": ["저장소에서 검색할 키워드(함수명·모델명·URL·템플릿명 등)", ...3~6개], '
    '"risk": "건드릴 때 주의할 점 한 줄"}}\n'
    'P1=서비스 영향/보안, P2=보통, P3=나중에 해도 됨. keywords 는 실제 코드에 있을 법한 식별자로.'
)

PATCH_PROMPT = (
    '당신은 이 저장소의 메인테이너입니다. 아래 작업을 **최소한의 수정**으로 구현하고, '
    '반드시 지정된 출력 형식으로만 답하세요. 설명 문단·마크다운·코드펜스로 답하면 시스템이 처리하지 못합니다.\n\n'
    '[작업] {title}\n[배경·완료 조건]\n{body}\n[주의] {risk}\n\n'
    '[프로젝트 규칙]\n'
    '- Django 5.2 / 앱 네임스페이스는 community (구 pybo 금지) / 템플릿은 base.html 상속\n'
    '- 운영은 MySQL, 로컬·CI 는 SQLite. 모델을 바꾸면 마이그레이션 필요를 표시할 것\n'
    '- 관리자 기능은 common.views.admin_required 사용\n\n'
    '[관련 파일 — 실제 내용]\n{files}\n\n'
    '{feedback}'
    '=== 출력 형식 (이 형식만 사용) ===\n'
    'ROOT_CAUSE: 코드 근거를 들어 원인·수정 방향 2~4문장\n'
    'CODE_ISSUE: yes 또는 no   (코드 수정 대상이 아니면 no)\n'
    'MIGRATION: yes 또는 no\n'
    'TEST_HINT: 사람이 확인하는 방법 한 줄\n'
    '\n'
    '수정할 파일마다 아래 블록을 반복 (최대 {max_files}개):\n'
    '<<<EDIT 저장소기준/상대/경로.py\n'
    '<<<FIND\n'
    '(파일에 정확히 한 번만 나오는 기존 코드 — 공백·들여쓰기까지 원문 그대로)\n'
    '<<<REPLACE\n'
    '(새 코드)\n'
    '>>>END\n'
    '\n'
    '새 파일은:\n'
    '<<<NEW 저장소기준/상대/경로.py\n'
    '(파일 전체 내용)\n'
    '>>>END\n'
    '\n'
    'PR_BODY:\n'
    '(PR 본문 — 무엇을/왜/어떻게 검증했는지, 한국어 마크다운)\n'
    '=== 형식 끝 ===\n\n'
    'CODE_ISSUE 가 no 면 EDIT 블록 없이 ROOT_CAUSE 에 운영 조치를 적으세요.'
)


def parse_patch(raw: str) -> dict:
    """블록 형식 응답을 파싱한다."""
    def field(name, default=''):
        m = re.search(rf'^{name}:[ \t]*(.+)$', raw, flags=re.M)
        return m.group(1).strip() if m else default

    edits = []
    for m in re.finditer(r'<<<EDIT[ \t]+(.+?)[ \t]*\n<<<FIND[ \t]*\n(.*?)\n<<<REPLACE[ \t]*\n(.*?)\n>>>END',
                         raw, flags=re.S):
        edits.append({'path': m.group(1).strip(), 'action': 'replace',
                      'find': m.group(2), 'replace': m.group(3)})
    for m in re.finditer(r'<<<NEW[ \t]+(.+?)[ \t]*\n(.*?)\n>>>END', raw, flags=re.S):
        edits.append({'path': m.group(1).strip(), 'action': 'create', 'content': m.group(2)})

    pr = ''
    mpr = re.search(r'^PR_BODY:[ \t]*\n(.*)$', raw, flags=re.S | re.M)
    if mpr:
        pr = mpr.group(1).split('=== 형식 끝')[0].strip()

    code_issue = field('CODE_ISSUE', 'yes').lower().startswith('y')
    return {
        'root_cause': field('ROOT_CAUSE'),
        'is_code_issue': code_issue if (code_issue or not edits) else True,
        'migration_needed': field('MIGRATION', 'no').lower().startswith('y'),
        'test_hint': field('TEST_HINT'),
        'pr_body': pr,
        'edits': edits,
        'raw_len': len(raw),
    }


# ───────────────────────────── 1) 관련 파일 수집
def collect_hints(task, limit: int = 6) -> list:
    """키워드로 저장소를 훑어 관련 파일 후보를 찾는다 (모델의 탐색 턴을 없애는 단계)."""
    words = [w for w in (task.triage.get('keywords') or []) if len(w) >= 3][:8]
    if not words:
        words = [w for w in re.findall(r'[A-Za-z_][A-Za-z0-9_]{3,}', f'{task.title} {task.body}')][:8]
    score = {}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', 'staticfiles', 'media', 'backups', 'logs', '__pycache__', 'venv', '.venv')]
        for fn in files:
            ext = os.path.splitext(fn)[1]
            if ext not in ALLOW_EXT:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, REPO).replace('\\', '/')
            if any(p in rel for p in DENY_PARTS):
                continue
            try:
                if os.path.getsize(full) > 400_000:
                    continue
                text = open(full, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            s = sum(text.count(w) for w in words)
            if any(w.lower() in rel.lower() for w in words):
                s += 5
            if s:
                score[rel] = s
    return [p for p, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit]]


def read_files(paths: list, budget: int = 45000) -> str:
    out, used = [], 0
    for rel in paths[:MAX_FILES]:
        full = os.path.join(REPO, rel)
        if not os.path.exists(full):
            continue
        text = open(full, encoding='utf-8', errors='ignore').read()
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + f'\n... (생략: 전체 {len(text)}자)'
        if used + len(text) > budget:
            out.append(f'--- {rel} (분량 초과로 생략 — 필요하면 다음 시도에서 요청)')
            continue
        used += len(text)
        out.append(f'--- {rel}\n{text}')
    return '\n\n'.join(out) or '(관련 파일을 찾지 못했습니다. 저장소 구조는 CLAUDE.md 참고)'


# ───────────────────────────── 2) 분류
def step_triage(task) -> dict:
    res = ask_agent_json('coding', TRIAGE_PROMPT.format(
        title=task.title, body=task.body or '(없음)', source=task.get_source_display()), max_tokens=2500)
    task.triage = res
    if res.get('kind') in dict(type(task).KIND_CHOICES):
        task.kind = res['kind']
    if res.get('priority') in ('P1', 'P2', 'P3'):
        task.priority = res['priority']
    task.save(update_fields=['triage', 'kind', 'priority'])
    return res


def issue_body(task) -> str:
    t = task.triage or {}
    lines = [t.get('summary', '') or task.title, '']
    if task.body:
        lines += ['## 배경', task.body, '']
    if t.get('acceptance'):
        lines += ['## 완료 조건'] + [f'- [ ] {a}' for a in t['acceptance']] + ['']
    if t.get('risk'):
        lines += ['## 주의', t['risk'], '']
    if task.decision_id and task.decision:
        m = task.decision.meeting
        lines += ['## 출처', f'{m.week_start} 주차 편집회의 결정 — {task.decision.question}', '']
    if task.finding_id:
        lines += ['## 출처', f'서버 로그 분석 지적사항 #{task.finding_id}', '']
    lines += ['---', '*테크창 연구팀 정비반이 자동 등록했습니다.*']
    return '\n'.join(lines)


# ───────────────────────────── 3) worktree
def make_worktree(task) -> tuple:
    """격리된 작업 사본을 만든다. 반환 (경로, 브랜치, 오류)"""
    branch = f"crew/task-{task.id}-{timezone.localdate():%m%d}"
    base = os.path.join(tempfile.gettempdir(), 'techchang_crew')
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f'task{task.id}')
    if os.path.exists(path):
        run(['git', 'worktree', 'remove', '--force', path])
        shutil.rmtree(path, ignore_errors=True)
    run(['git', 'branch', '-D', branch])
    out = run(['git', 'worktree', 'add', '-b', branch, path, 'HEAD'])
    if out.returncode != 0:
        return None, branch, out.stderr[-300:]
    return path, branch, ''


def run(args, cwd=REPO, timeout=120, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})}, encoding='utf-8', errors='replace')


# ───────────────────────────── 4) 패치 적용
def apply_edits(wt: str, edits: list) -> tuple:
    """worktree 에 수정을 적용. 반환 (적용된 파일 목록, 오류 목록)"""
    done, errs = [], []
    for e in edits[:MAX_FILES]:
        rel = str(e.get('path', '')).replace('\\', '/').lstrip('/')
        full = os.path.normpath(os.path.join(wt, rel))
        if not full.startswith(os.path.normpath(wt) + os.sep):
            errs.append(f'{rel}: 저장소 밖 경로 거부')
            continue
        if os.path.splitext(rel)[1] not in ALLOW_EXT or any(p in rel for p in DENY_PARTS):
            errs.append(f'{rel}: 수정이 허용되지 않는 파일')
            continue
        action = e.get('action', 'replace')
        try:
            if action == 'create':
                os.makedirs(os.path.dirname(full), exist_ok=True)
                open(full, 'w', encoding='utf-8', newline='\n').write(e.get('content', ''))
                done.append(rel)
            else:
                if not os.path.exists(full):
                    errs.append(f'{rel}: 파일 없음')
                    continue
                text = open(full, encoding='utf-8').read()
                find, repl = e.get('find', ''), e.get('replace', '')
                n = text.count(find)
                if not find or n == 0:
                    errs.append(f'{rel}: 찾는 코드가 파일에 없음')
                elif n > 1:
                    errs.append(f'{rel}: 찾는 코드가 {n}번 나타남 — 더 긴 조각 필요')
                else:
                    open(full, 'w', encoding='utf-8', newline='\n').write(text.replace(find, repl))
                    done.append(rel)
        except Exception as ex:  # noqa: BLE001
            errs.append(f'{rel}: {ex}')
    return done, errs


# ───────────────────────────── 5) 검증
def verify(wt: str) -> tuple:
    """worktree 에서 check + test. 반환 (성공, 출력)"""
    py = sys.executable
    env = {'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_DB_ENGINE': 'sqlite3',
           'DJANGO_SECRET_KEY': 'crew-verify-key', 'DEBUG': 'False'}
    outs = []
    for args, label in (([py, 'manage.py', 'check'], 'check'),
                        ([py, 'manage.py', 'test', '--noinput'], 'test')):
        try:
            r = run(args, cwd=wt, timeout=VERIFY_TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            return False, f'{label}: 시간 초과'
        tail = ((r.stdout or '') + (r.stderr or ''))[-1500:]
        outs.append(f'[{label}] exit={r.returncode}\n{tail}')
        if r.returncode != 0:
            return False, '\n\n'.join(outs)
    return True, '\n\n'.join(outs)


# ───────────────────────────── 6) 커밋·PR
def commit_push(wt: str, branch: str, task, files: list) -> tuple:
    run(['git', 'add', '-A'], cwd=wt)
    msg = f"fix: {task.title[:60]}\n\n정비반 자동 수정 (작업 #{task.id}"
    if task.issue_number:
        msg += f", closes #{task.issue_number}"
    msg += ")\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
    r = run(['git', 'commit', '-m', msg], cwd=wt)
    if r.returncode != 0 and 'nothing to commit' in (r.stdout or ''):
        return False, '변경 사항이 없습니다'
    r = run(['git', 'push', '-u', 'origin', branch], cwd=wt, timeout=180)
    if r.returncode != 0:
        return False, f'push 실패: {(r.stderr or "")[-200:]}'
    return True, ''
