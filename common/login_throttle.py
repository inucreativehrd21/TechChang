"""로그인 실패 제한 — 계정별·IP별 실패 횟수를 세고, 넘으면 비밀번호를 확인하지 않고 잠시 막아요.

2026-11-24 점검: 로그인 화면(AccountLoginView)은 실패 횟수 제한이 없었고, 전역 요청 제한은 LocMem 캐시라
gunicorn 워커마다 따로 세어 사실상 워커 수배로 느슨했어요. 회원 100명을 넘기며 비밀번호 대입을 막으려고 추가했어요.

- 계정: 같은 아이디(대소문자 무시)로 15분 안에 8번 틀리면 15분 잠금 — 여러 IP 에서 한 계정을 노리는 대입 차단
- IP: 같은 IP 에서 15분 안에 40번 틀리면 15분 잠금 — 한 IP 가 여러 계정을 훑는 대입 차단
- 잠금 중에는 아이디가 있든 없든 같은 안내를 보여 줘요(계정 존재 여부를 알려 주지 않아요).
"""
from __future__ import annotations

import hashlib
import logging
import time

from django.core.cache import caches

logger = logging.getLogger('security')

WINDOW = 15 * 60
ACCOUNT_LIMIT = 8
IP_LIMIT = 40
MESSAGE = '로그인 시도가 너무 많아요. 15분 뒤 다시 시도하거나 비밀번호 찾기를 이용해 주세요.'


def _store():
    return caches['throttle']


def client_ip(request) -> str:
    """nginx 가 붙인 X-Forwarded-For 마지막 값(보안 미들웨어와 같은 규칙)."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = xff.split(',')[-1].strip() if xff else request.META.get('REMOTE_ADDR')
    return ip or '0.0.0.0'


def _keys(request, username: str) -> tuple[str, str]:
    ident = hashlib.sha256((username or '').strip().lower().encode('utf-8')).hexdigest()[:32]
    return f'login_fail:acct:{ident}', f'login_fail:ip:{client_ip(request)}'


def _count(key: str, now: float) -> int:
    value = _store().get(key)
    if not value or now - value[1] > WINDOW:
        return 0
    return value[0]


def _bump(key: str, now: float) -> int:
    count, start = _store().get(key) or (0, now)
    if now - start > WINDOW:
        count, start = 0, now
    count += 1
    _store().set(key, (count, start), WINDOW)
    return count


def blocked(request, username: str) -> bool:
    now = time.time()
    account, ip = _keys(request, username)
    return _count(account, now) >= ACCOUNT_LIMIT or _count(ip, now) >= IP_LIMIT


def failed(request, username: str) -> None:
    now = time.time()
    account, ip = _keys(request, username)
    a, i = _bump(account, now), _bump(ip, now)
    if a == ACCOUNT_LIMIT or i == IP_LIMIT:
        logger.warning('로그인 실패 제한 걸림: ip=%s account_fails=%s ip_fails=%s', client_ip(request), a, i)


def succeeded(request, username: str) -> None:
    account, _ip = _keys(request, username)
    _store().delete(account)
