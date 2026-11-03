"""코드 예제 점검 — 칼럼의 파이썬 코드를 문서가 아니라 코드로 확인한다.

왜(2026-10-31 B 파일럿 2회): 코딩 칼럼의 반복 결함은 assertNumQueries 가 감싸는 범위, 클래스 밖으로 빠진
테스트 메서드, '필자 예상값'으로 적은 쿼리 수였다. 검증관은 공식 문서를 읽어 판정하므로 이런 결함은
매 수정마다 새로 생기고, 편집장은 '직접 실행해 확인하라'고 요구하지만 파이프라인에는 실행 단계가 없었다.

- static_issues(): 항상 켠다. 파싱 실패와 클래스 밖 테스트 메서드를 자동 점검 지적으로 돌린다.
- run_examples(): OFFICE_CODE_RUN=1 일 때만. 본문의 모델·테스트 블록을 임시 앱으로 묶어 메모리 SQLite 에서
  별도 프로세스로 실행하고, 결과를 근거 묶음의 [코드 실행 확인] 블록으로 넘긴다. 모델이 쓴 코드를 실행하므로
  운영 서버에서는 기본으로 끈다(환경변수에 비밀값을 넘기지 않고, 프로젝트 경로를 sys.path 에 넣지 않는다).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

BLOCK = re.compile(r'```(?:python|py)[^\n]*\n(.*?)```', re.S | re.I)
HEADING = '[코드 실행 확인]'
ITEM = '- [실행] '
TIMEOUT = 90
# 본문 오류가 아니라 임시 실행 환경과의 차이(URL·템플릿·외부 앱)로 보는 실패
# NameError 는 대개 본문 밖(공식 문서·독자 프로젝트)의 모델을 가리킨다 — 오타일 수도 있지만 단정하지 않는다
ENV_ERRORS = ('ImportError', 'ModuleNotFoundError', 'NoReverseMatch', 'TemplateDoesNotExist',
              'ImproperlyConfigured', 'LookupError', 'Resolver404', 'NameError')


def enabled() -> bool:
    return os.environ.get('OFFICE_CODE_RUN', '').strip().lower() in ('1', 'true', 'yes', 'on')


def blocks(content: str) -> list[str]:
    return [textwrap.dedent(b) for b in BLOCK.findall(content or '')]


def _is_testcase(node: ast.ClassDef) -> bool:
    return any(isinstance(b, (ast.Name, ast.Attribute)) and (getattr(b, 'id', '') or getattr(b, 'attr', '')).endswith('TestCase')
               for b in node.bases)


def _is_model(node: ast.ClassDef) -> bool:
    return any(isinstance(b, ast.Attribute) and b.attr == 'Model' for b in node.bases)


def static_issues(content: str) -> list[str]:
    """실행 없이 잡히는 코드 결함. 반환: 자동 점검 지적 문장."""
    issues = []
    for n, code in enumerate(blocks(content), 1):
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            issues.append(f'{n}번째 파이썬 코드 블록이 파싱되지 않아요({e.lineno}행: {e.msg}). 그대로 복사해 실행할 수 '
                          '있게 고치고, 일부를 생략했다면 `...`이나 주석으로 표시하세요.')
            continue
        seen_test_class = False
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and _is_testcase(node):
                seen_test_class = True
            elif (seen_test_class and isinstance(node, ast.FunctionDef) and node.name.startswith('test')
                  and node.args.args and node.args.args[0].arg == 'self'):
                issues.append(f'{n}번째 코드 블록의 {node.name}()이 테스트 클래스 밖에 있어요. 들여쓰기가 빠져 테스트 '
                              '러너가 수집하지 않으므로 클래스 안으로 넣으세요.')
    return issues


def _num_queries(func: ast.FunctionDef) -> list[int]:
    out = []
    for node in ast.walk(func):
        if (isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'assertNumQueries'
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int)):
            out.append(node.args[0].value)
    return out


# 보조 모듈 블록은 첫 줄이 '# shop/services.py' 같은 경로 머리글이다. 모델·테스트 블록과 같은 앱 안의 모듈로 옮긴다
_HEADER = re.compile(r'^#\s*(?:([A-Za-z_]\w*)/)?([A-Za-z_]\w*)\.py\s*$')
_RESERVED = ('models', 'tests', 'settings', 'manage', 'urls', 'views', 'admin', 'apps', 'wsgi', 'asgi', 'conftest')


def _path(code: str) -> tuple[str, str] | None:
    """첫 줄이 정확히 '# 앱/모듈.py' 인 블록의 (앱, 모듈). '# shop/tests_wrong.py — 잘못된 예'처럼 설명이 붙은 발췌는 None."""
    first = next((ln for ln in code.splitlines() if ln.strip()), '')
    m = _HEADER.match(first.strip())
    return (m.group(1) or '', m.group(2)) if m else None


def _header(code: str) -> tuple[str, str] | None:
    p = _path(code)
    return p if p and p[1] not in _RESERVED else None


def _is_test_module(name: str) -> bool:
    return name == 'tests' or name.startswith('test_')


def app_label(content: str) -> str:
    """본문 경로 머리글의 앱 이름 — 임시 앱을 같은 이름으로 만들어 mock.patch('shop.services.x') 같은 경로가 맞게 한다.
    쓸 수 없는 이름(표준 라이브러리·Django·실행 파일과 겹침)이면 colapp."""
    from collections import Counter
    apps = Counter(p[0] for p in map(_path, blocks(content)) if p and p[0])
    for name, _n in apps.most_common():
        if (name.isidentifier() and name not in sys.stdlib_module_names
                and name not in ('django', 'rest_framework', 'colsettings', 'tests', 'test')):
            return name
    return 'colapp'


def support_modules(content: str) -> dict[str, tuple[str, str]]:
    """{모듈 이름: (앱 이름, 소스)} — 같은 이름이 여러 번이면 마지막 정의. 파싱되지 않는 블록은 뺀다."""
    found = {}
    for code in blocks(content):
        head = _header(code)
        if not head:
            continue
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        if any(isinstance(n, ast.ClassDef) and (_is_model(n) or _is_testcase(n)) for n in tree.body):
            continue
        found[head[1]] = (head[0], code)
    return found


def _local_import(node, support: dict):
    """같은 앱의 보조 모듈을 가리키는 import(.services · shop.services)를 임시 앱 기준 상대 import 로 바꾼다."""
    if not isinstance(node, ast.ImportFrom) or not support:
        return None
    mod = node.module or ''
    if node.level == 1 and mod.split('.')[0] in support:
        return node
    if node.level == 1 and not mod and all(a.name in support for a in node.names):     # from . import services
        return node
    for name, (app, _src) in support.items():
        if not node.level and app and mod.split('.')[:2] == [app, name]:
            return ast.ImportFrom(module='.'.join(mod.split('.')[1:]), names=node.names, level=1)
        if not node.level and app and mod == app and all(a.name in support for a in node.names):   # from shop import services
            return ast.ImportFrom(module=None, names=node.names, level=1)
    return None


def _importable(node) -> bool:
    """임시 앱에서도 같은 뜻인 import 만 — 표준 라이브러리·Django·DRF. 독자 프로젝트 경로·상대 경로는 뺀다
    (모델은 임시 앱의 .models 로 대신하고, 시리얼라이저 같은 다른 모듈은 본문에 없으니 실행하지 않는다)."""
    if isinstance(node, ast.ImportFrom):
        if node.level:
            return False
        names = [node.module or '']
    else:
        names = [a.name for a in node.names]
    return all(n.split('.')[0] in ('django', 'rest_framework') or n.split('.')[0] in sys.stdlib_module_names
               for n in names)


def assemble(content: str) -> tuple[str, str, dict] | None:
    """본문 블록에서 models.py·tests.py 를 만든다. 모델과 테스트가 둘 다 없으면 None.
    모델·테스트가 든 블록만 쓴다(뷰 예시 블록은 독자 프로젝트에 기대므로 뺀다). 테스트 블록의 보조 함수는
    함께 옮긴다. 같은 이름이 여러 번 나오면(개선 전/후) 마지막 정의를 쓴다."""
    imports, local_imports, models, tests, helpers = [], [], {}, {}, {}
    support = support_modules(content)
    # 정확한 경로 머리글(# shop/tests.py)이 있으면 그 파일만 실행 대상 — '# shop/tests_wrong.py — 잘못된 예' 같은
    # 일부러 실패하는 예시·발췌 블록은 빼야 한다(2026-11-03 atomic 3차: 섞여서 오류 14건)
    paths = [_path(c) for c in blocks(content)]
    exact_tests = any(p and _is_test_module(p[1]) for p in paths)
    exact_models = any(p and p[1] == 'models' for p in paths)
    for code, path in zip(blocks(content), paths):
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        has_model, has_test = any(map(_is_model, classes)), any(map(_is_testcase, classes))
        if not (has_model or has_test):
            continue
        if has_test and exact_tests and not (path and _is_test_module(path[1])):
            continue
        if has_model and not has_test and exact_models and not (path and path[1] == 'models'):
            continue
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                local = _local_import(node, support)
                if local is not None:
                    local_imports.append(ast.unparse(local))     # models.py 에는 넣지 않는다(보조 모듈이 models 를 가져와 순환)
                elif _importable(node):
                    imports.append(ast.unparse(node))
            elif isinstance(node, ast.ClassDef) and _is_model(node):
                models[node.name] = node
            elif isinstance(node, ast.ClassDef) and _is_testcase(node):
                tests[node.name] = node
            elif has_test and isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                helpers[node.name] = node        # 클래스 밖으로 빠진 test 메서드도 여기 — 러너가 수집하지 않는다
    if not models or not tests:
        return None
    head = '\n'.join(dict.fromkeys(['from django.db import models', 'from django.conf import settings',
                                    'from django.contrib.auth import get_user_model', *imports]))
    models_py = head + '\n\n' + '\n\n'.join(ast.unparse(m) for m in models.values()) + '\n'
    tests_py = (head + '\nfrom django.test import TestCase\nfrom django.db.models import Prefetch\nfrom .models import *\n'
                + '\n'.join(dict.fromkeys(local_imports)) + '\n\n'
                + '\n\n'.join(ast.unparse(n) for n in [*helpers.values(), *tests.values()]) + '\n')
    expected = {f.name: _num_queries(f) for t in tests.values() for f in t.body
                if isinstance(f, ast.FunctionDef) and f.name.startswith('test')}
    return models_py, tests_py, expected


SETTINGS = '''SECRET_KEY = "column-check"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "__APP__"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
'''

RUNNER = '''import io, json, re, sys, unittest
sys.path.insert(0, sys.argv[1])
import django
django.setup()
from django.test.runner import DiscoverRunner
from django.test.utils import iter_test_cases, setup_test_environment
out = {"django": django.get_version(), "tests": [], "error": ""}
try:
    runner = DiscoverRunner(verbosity=0, interactive=False)
    setup_test_environment()
    suite = runner.build_suite(["__APP__"])
    names = [t.id() for t in iter_test_cases(suite)]
    old = runner.setup_databases()
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    runner.teardown_databases(old)
    bad = {}
    for kind, items in (("failed", result.failures), ("error", result.errors)):
        for test, tb in items:
            lines = tb.strip().splitlines()
            # assertNumQueries 는 예외 줄 뒤에 실행된 SQL 목록을 붙인다 — 예외 줄을 고른다
            head = [l for l in lines if re.match(r"^[A-Za-z_.]+(Error|Exception)\\b", l)]
            bad[test.id()] = (kind, (head[-1] if head else lines[-1])[:300])
    for name in names:
        kind, msg = bad.get(name, ("passed", ""))
        out["tests"].append({"name": name.rsplit(".", 1)[-1], "status": kind, "message": msg})
except Exception as e:
    out["error"] = (type(e).__name__ + ": " + str(e))[:300]
print("@@RESULT" + json.dumps(out))
'''


def _support_source(source: str, support: dict) -> str:
    """보조 모듈 안의 `from shop.models import X`·`from shop.helpers import Y` 를 임시 앱 기준 상대 import 로 바꾼다."""
    tree = ast.parse(source)
    apps = {app for app, _s in support.values() if app}
    for node in tree.body:
        parts = (node.module or '').split('.') if isinstance(node, ast.ImportFrom) and not node.level else []
        if parts and parts[0] in apps:                      # from shop.models import X · from shop import models
            node.module, node.level = '.'.join(parts[1:]) or None, 1
    return ast.unparse(tree) + '\n'


def run_examples(content: str, *, timeout: int = TIMEOUT) -> dict:
    """반환: {'ran': bool, 'reason': str, 'django': str, 'tests': [{name,status,message,expected}], 'error': str}"""
    if not enabled():
        return {'ran': False, 'reason': 'OFFICE_CODE_RUN 꺼짐'}
    built = assemble(content)
    if not built:
        return {'ran': False, 'reason': '모델과 테스트가 함께 있는 코드 예제 없음'}
    models_py, tests_py, expected = built
    with tempfile.TemporaryDirectory(prefix='colcheck-') as root:
        label = app_label(content)
        app = Path(root, label)
        app.mkdir()
        Path(app, '__init__.py').write_text('', encoding='utf-8')
        Path(app, 'models.py').write_text(models_py, encoding='utf-8')
        Path(app, 'tests.py').write_text(tests_py, encoding='utf-8')
        support = support_modules(content)
        for name, (_app, source) in support.items():
            Path(app, f'{name}.py').write_text(_support_source(source, support), encoding='utf-8')
        Path(root, 'colsettings.py').write_text(SETTINGS.replace('__APP__', label), encoding='utf-8')
        Path(root, '_run.py').write_text(RUNNER.replace('__APP__', label), encoding='utf-8')
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'TEMP', 'TMP') if k in os.environ}
        env.update({'DJANGO_SETTINGS_MODULE': 'colsettings', 'PYTHONIOENCODING': 'utf-8'})
        try:
            proc = subprocess.run([sys.executable, '-I', str(Path(root, '_run.py')), root], cwd=root, env=env,
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'ran': False, 'reason': f'{timeout}초 안에 끝나지 않음'}
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith('@@RESULT')), '')
    if not line:
        return {'ran': False, 'reason': (proc.stderr.strip().splitlines() or ['실행 결과 없음'])[-1][:300]}
    res = json.loads(line[len('@@RESULT'):])
    for t in res['tests']:
        t['expected'] = expected.get(t['name'], [])
    res['ran'] = not res.get('error')
    res['reason'] = res.get('error', '')
    return res


def _env_problem(message: str) -> bool:
    return any(message.startswith(e) for e in ENV_ERRORS)


def facts(result: dict) -> str:
    """근거 묶음에 넣을 [코드 실행 확인] 블록. 실행하지 못했으면 빈 문자열.
    줄마다 ITEM 표식을 붙인다 — 근거 묶음의 다른 줄도 '- '로 시작해 표식 없이는 블록을 갈아 끼울 수 없다."""
    if not result.get('ran') or not result.get('tests'):
        return ''
    lines = [f"{HEADING} 본문 코드를 Django {result.get('django', '')} 임시 앱·메모리 DB에서 그대로 실행한 결과예요. "
             '실행 환경 차이로 실패한 항목은 본문 오류로 단정하지 마세요.']
    for t in result['tests']:
        q = f" (assertNumQueries {', '.join(map(str, t['expected']))}회)" if t['expected'] else ''
        if t['status'] == 'passed':
            lines.append(f"{ITEM}{t['name']}: 통과{q}")
        elif _env_problem(t['message']):
            lines.append(f"{ITEM}{t['name']}: 실행 환경 차이로 확인 못 함 — {t['message']}")
        else:
            m = re.search(r'(\d+) != (\d+) : \d+ queries executed', t['message'])
            real = f' 실제 실행 {m.group(1)}회, 본문 기대 {m.group(2)}회 —' if m else ''
            lines.append(f"{ITEM}{t['name']}: 실패{q} —{real} {t['message']}")
    return '\n'.join(lines)


_STANDALONE = re.compile(r'settings\.configure\(|django\.setup\(\)|if __name__ == ["\']__main__["\']')


def format_issues(content: str) -> list[str]:
    """튜토리얼 실행 예제가 연구실이 실행할 수 있는 형식인지(office.genres 의 '실행 예제' 규칙).

    왜(2026-11-02 atomic 2차·select 4차): 혼자 실행하는 스크립트로 쓴 예제는 실행 검증이 돌지 않아, '테스트로
    재현된다'·'메일 1건' 같은 결과 주장이 모두 원장 밖이 됐다. 실행기를 넓히는 대신 예제 형식을 고정한다."""
    codes = blocks(content)
    if not codes:
        return []
    issues = []
    if any(_STANDALONE.search(c) for c in codes):
        issues.append('실행 예제에 혼자 실행하는 스크립트(settings.configure·django.setup()·__main__)가 있습니다. '
                      '연구실이 실행해 확인할 수 있도록 `# 앱/models.py`·`# 앱/tests.py`(TestCase) 블록으로 나눠 쓰세요.')
    if assemble(content) is None:
        issues.append('실행 예제에 예제용 모델(`# 앱/models.py`)과 TestCase 테스트(`# 앱/tests.py`)가 함께 있지 않아 '
                      '실행 확인을 할 수 없습니다. 결과를 말하는 문장은 그 값을 assert 하는 테스트로 뒷받침하세요.')
    return issues


def failures(pack: str) -> list[str]:
    """근거 묶음의 실행 확인 블록에서 본문 코드가 실제로 실패한 항목."""
    return [ln[len(ITEM):].strip() for ln in (pack or '').splitlines() if ln.startswith(ITEM) and ': 실패' in ln]


def replace(pack: str, block: str) -> str:
    """이전 판의 실행 확인 블록을 새 결과로 바꾼다(옛 코드의 결과가 근거로 남지 않게)."""
    kept = [ln for ln in (pack or '').splitlines() if not ln.startswith((HEADING, ITEM))]
    return '\n'.join(p for p in ('\n'.join(kept).strip(), block.strip()) if p)
