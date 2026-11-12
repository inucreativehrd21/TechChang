"""연구실 전용 운영자 권한과 실행 인자 검증."""
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect


def is_operator(user):
    if not user or not user.is_authenticated or not user.is_active or not (user.is_staff or user.is_superuser):
        return False
    ids = getattr(settings, 'LAB_OPERATOR_IDS', ())
    return user.pk in {int(i) for i in ids} if ids else user.is_superuser


def operator_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_operator(request.user):
            messages.error(request, '연구실 운영자 계정으로 로그인해 주세요.')
            return redirect('common:login')
        response = view(request, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response
    return wrapped


COMMANDS = {
    'office_publish': {'--topic', '--profile', '--resume-run', '--track'},
    'office_revise': {'--draft', '--note', '--by', '--facts'},
    'auto_write_series': {'--series', '--revise-draft', '--note', '--by'},
    'hold_meeting': {'--email'}, 'make_newsletter': set(),
    'polish_meeting': {'--meeting'}, 'update_column_map': {'--settle'},
    'remake_column': {'--question', '--facts'},
}
FLAGS = {'--force', '--prepare', '--if-missing', '--no-publish'}


def validate_args(args):
    if not isinstance(args, list) or not args or args[0] not in COMMANDS:
        raise ValueError('허용되지 않은 작업이에요.')
    i = 1
    while i < len(args):
        arg = args[i]
        if arg in FLAGS:
            i += 1
        elif arg in COMMANDS[args[0]] and i + 1 < len(args) and isinstance(args[i+1], str):
            if len(args[i+1]) > 10000 or '\x00' in args[i+1] or args[i+1].startswith('--'):
                raise ValueError('작업 인자가 너무 길거나 올바르지 않아요.')
            if arg in ('--draft', '--revise-draft', '--question', '--meeting', '--settle') and not args[i+1].isdigit():
                raise ValueError('작업 번호는 숫자여야 해요.')
            if arg == '--track' and args[i+1] not in ('research', 'practical', 'both', 'legacy'):
                raise ValueError('올바른 칼럼 유형이 필요해요.')
            i += 2
        else:
            raise ValueError('허용되지 않은 작업 인자예요.')
    return args
