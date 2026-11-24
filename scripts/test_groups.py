"""회귀 테스트를 모듈 묶음으로 나눠 실행한다.

    python scripts/test_groups.py              # 바뀐 파일(git) 기준으로 묶음 자동 선택 + 보안 묶음 항상
    python scripts/test_groups.py rookie lab   # 묶음 지정 (security·community·lab·samguk·rookie·all)
    python scripts/test_groups.py all --slow   # 전체 + 느린 테스트 = 배포 전 (manage.py test 와 같음)
    python scripts/test_groups.py --list       # 실행하지 않고 고른 묶음·모듈만 출력
    python scripts/test_groups.py rookie -- --failfast -v 2   # -- 뒤는 manage.py test 에 그대로 전달

manage.py test 를 하위 프로세스로 부른다 — 설정(base.py)이 argv[1] == 'test' 로 테스트 전용 캐시·해셔를 고르기 때문.
자동 선택은 파일 이름 규칙에 따른 추정이라 묶음 사이 의존을 다 잡지 못한다. 배포 전에는 all --slow 를 돌린다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GROUPS = {
    'security': ['common/test*.py', 'community/test_*security*.py', 'community/test_recent_privacy.py'],
    'rookie': ['community/test_rookie*.py'],
    'samguk': ['community/test_samguk*.py'],
    'lab': ['office/test*.py'],
    'community': ['community/test*.py'],          # 위 묶음에 든 모듈은 뺀다(labels 참고)
}
# 이 경로가 바뀌면 사이트 전체에 영향 — 전체 실행
GLOBAL = ('config/', 'requirements', 'manage.py', 'common/middleware.py', 'common/mobile_loader.py',
          'common/context_processors.py', 'templates/base', 'community/models.py', 'community/migrations/')
IGNORED = ('docs/', 'static/', 'graphify-out/', 'logs/', 'scratchpad/', 'tmp/', 'output/', '.claude/', '.agents/',
           '.github/', 'scripts/')


def labels(group):
    """묶음 → manage.py test 라벨(모듈 경로). community 는 다른 묶음에 든 모듈을 뺀 나머지."""
    found = {p for pattern in GROUPS[group] for p in ROOT.glob(pattern)}
    if group == 'community':
        found -= {p for g in GROUPS if g != 'community' for pattern in GROUPS[g] for p in ROOT.glob(pattern)}
    return sorted('.'.join(p.relative_to(ROOT).with_suffix('').parts) for p in found)


def group_for(path):
    """바뀐 파일 하나 → 묶음 이름('all' = 전체, None = 테스트 불필요)."""
    path = path.replace('\\', '/')
    if path.startswith(IGNORED) or path.endswith(('.md', '.txt', '.json')):
        return None
    if path.startswith(GLOBAL):
        return 'all'
    if 'samguk' in path:
        return 'samguk'
    if 'rookie' in path:
        return 'rookie'
    if path.startswith(('office/', 'templates/office/', 'templates/newsletter/')):
        return 'lab'
    if path.startswith(('common/', 'templates/common/')):
        return 'security'
    if path.startswith(('community/', 'templates/community/')):
        return 'community'
    return 'all' if path.endswith(('.py', '.html')) else None


def changed_files():
    git = lambda *a: subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True,
                                    encoding='utf-8').stdout.split('\n')
    return [f for f in git('diff', '--name-only', 'HEAD') + git('ls-files', '--others', '--exclude-standard') if f]


def main(argv):
    passthrough = argv[argv.index('--') + 1:] if '--' in argv else []
    argv = argv[:argv.index('--')] if '--' in argv else argv
    slow, dry = '--slow' in argv, '--list' in argv
    chosen = [a for a in argv if not a.startswith('--')]
    unknown = [g for g in chosen if g not in GROUPS and g != 'all']
    if unknown:
        sys.exit(f'모르는 묶음: {unknown} — 가능한 묶음: {", ".join(GROUPS)}, all')
    if not chosen:
        picked = {group_for(f) for f in changed_files()} - {None}
        chosen = ['all'] if 'all' in picked else sorted(picked | {'security'})
        print('바뀐 파일 기준 묶음:', ', '.join(chosen))
    cmd = [sys.executable, 'manage.py', 'test', '--noinput']
    if 'all' not in chosen:
        mods = sorted({m for g in chosen for m in labels(g)})
        cmd += mods
        print(f'{len(mods)}개 모듈: {", ".join(chosen)}')
    if not slow:
        cmd += ['--exclude-tag', 'slow']
    cmd += passthrough
    if dry:
        print(' '.join(cmd))
        return 0
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
