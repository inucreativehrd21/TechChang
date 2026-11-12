"""모델 CLI에 DB·메일·일반 API 키를 전달하지 않는다."""
import os

BASE = {'PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
        'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL', 'APPDATA', 'LOCALAPPDATA',
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY'}


def claude_environment():
    allowed = BASE | {'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CONFIG_DIR'}
    return {key: value for key, value in os.environ.items() if key in allowed}


def worker_environment():
    allowed = BASE | {'DJANGO_SETTINGS_MODULE', 'PYTHONPATH', 'PYTHONIOENCODING', 'CLAUDE_CODE_OAUTH_TOKEN',
                      'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'CODEX_ACCESS_TOKEN', 'AI_FALLBACK_BACKEND',
                      'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'}
    # Django 작업 자체에는 DB 설정이 필요하다. 모델 CLI는 위의 별도 허용 목록으로 다시 격리한다.
    return {key: value for key, value in os.environ.items()
            if key in allowed or key.startswith(('DJANGO_', 'OFFICE_', 'LAB_'))}
