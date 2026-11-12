"""DB 대기열의 실행·종료를 추적한다. 웹 프로세스에서는 호출하지 않는다."""
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from .models import JobRequest, ColumnDraft

ALLOWED = {'office_publish', 'office_revise', 'auto_write_series', 'hold_meeting',
           'make_newsletter', 'polish_meeting', 'update_column_map', 'remake_column'}


def alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # 접근 거부면 중복 실행을 피하려고 살아 있다고 본다.
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


from .worker_runtime import work
