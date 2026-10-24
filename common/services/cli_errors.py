"""구독 CLI 오류 분류. 공급자의 문구를 비용 정책이나 작업 성공으로 오인하지 않는다."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

LIMIT_RE = re.compile(
    r'session limit|usage.?limit|rate.?limit|quota.?exceeded|insufficient_quota|'
    r'too many requests|hit your .*limit|limit has been reached', re.I)
AUTH_RE = re.compile(r'unauthori[sz]ed|authentication|not logged in|please (?:log|sign) in|'
                     r'token.{0,30}(?:expired|revoked)|refresh.{0,30}failed|invalid.{0,10}(?:token|credential)', re.I)


def failure_kind(reason: str) -> str:
    if AUTH_RE.search(reason):
        return 'auth'
    return 'limit' if LIMIT_RE.search(reason) else 'execution'


def retry_at(reason: str, now=None):
    """명시된 ISO 시각·대기 초·시각을 우선 사용하고, 불명확한 한도는 30분 뒤 재확인한다."""
    now = now or timezone.now()
    m = re.search(r'\b(20\d\d-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d))', reason)
    if m:
        at = datetime.fromisoformat(m[1].replace('Z', '+00:00'))
        if at > now:
            return at
    m = re.search(r'(?:retry_after_seconds["\s:=]+|try again in\s+|retry (?:after|in)\s+)(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)?\b', reason, re.I)
    if m:
        unit = (m[2] or 's').lower()
        seconds = int(m[1]) * (3600 if unit.startswith('h') else 60 if unit.startswith('m') else 1)
        return now + timedelta(seconds=max(5, seconds))
    m = re.search(r'resets?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', reason, re.I)
    if m:
        local = timezone.localtime(now)
        tz = re.search(r'\(([A-Za-z_]+/[A-Za-z_/]+)\)', reason)
        if tz:
            try:
                local = now.astimezone(ZoneInfo(tz[1]))
            except ZoneInfoNotFoundError:
                pass
        hour = int(m[1]) % 12 + (12 if m[3].lower() == 'pm' else 0)
        if 1 <= int(m[1]) <= 12 and int(m[2] or 0) < 60:
            at = local.replace(hour=hour, minute=int(m[2] or 0), second=0, microsecond=0)
            return at if at > now else at + timedelta(days=1)
    return now + timedelta(minutes=30 if failure_kind(reason) == 'limit' else 5)


class ProviderUnavailable(Exception):
    def __init__(self, reason: str, *, provider: str, kind: str | None = None, retry_after=None):
        super().__init__(reason)
        self.provider = provider
        self.kind = kind or failure_kind(reason)
        self.retry_at = retry_after or retry_at(reason)
