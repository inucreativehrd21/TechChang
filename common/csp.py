"""CSP 위반 보고 수신(/csp-report/).

CSP_MODE=report-only 단계에서 브라우저가 보내는 위반 보고를 security 로그에 남긴다. 강제(enforce)로
넘어가기 전에 어떤 페이지의 어떤 인라인 스크립트가 막힐지 이 로그로 정리한다.

누구나 POST 할 수 있는 주소라 다음을 지킨다.
  - DB 를 쓰지 않는다. 본문 크기를 제한하고, 같은 위반은 1시간에 한 번만 로그에 남긴다.
  - IP 당 수신량에 상한을 둔다(넘으면 조용히 버림). 보고 요청은 SecurityMiddleware 의 요청 수 집계에서
    빠지므로(RATE_LIMIT_EXEMPT_PATHS), 위반이 많은 페이지를 본 정상 사용자가 차단되지 않는다.
  - 항상 204 로 답한다(브라우저는 응답을 보지 않는다).
"""
from __future__ import annotations

import hashlib
import json
import logging
from urllib.parse import urlsplit

from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger('security.csp')

MAX_BODY_BYTES = 16 * 1024
PER_IP_LIMIT = 60            # IP 당 10분에 받는 보고 수
PER_IP_WINDOW = 600
DEDUPE_SECONDS = 3600


def _client_ip(request) -> str:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _path(url: str) -> str:
    """보고에 담긴 URL 은 경로만 남긴다(쿼리스트링의 토큰 등이 로그에 남지 않게)."""
    if not url:
        return ''
    if '://' not in url:
        return url[:200]               # 'inline', 'eval' 같은 키워드
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}{parts.path}'[:200]


def _normalize(payload) -> list[dict]:
    """report-uri(application/csp-report)와 Reporting API(application/reports+json) 형식을 한 모양으로."""
    items = []
    if isinstance(payload, dict) and isinstance(payload.get('csp-report'), dict):
        r = payload['csp-report']
        items.append({
            'directive': r.get('effective-directive') or r.get('violated-directive') or '',
            'blocked': r.get('blocked-uri') or '',
            'document': r.get('document-uri') or '',
            'source': r.get('source-file') or '',
            'line': r.get('line-number') or '',
            'sample': r.get('script-sample') or '',
        })
    elif isinstance(payload, list):
        for entry in payload[:20]:
            if not isinstance(entry, dict) or entry.get('type') != 'csp-violation':
                continue
            b = entry.get('body') or {}
            items.append({
                'directive': b.get('effectiveDirective') or '',
                'blocked': b.get('blockedURL') or '',
                'document': b.get('documentURL') or entry.get('url') or '',
                'source': b.get('sourceFile') or '',
                'line': b.get('lineNumber') or '',
                'sample': b.get('sample') or '',
            })
    return items


@csrf_exempt
@require_POST
def csp_report(request):
    try:
        length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY_BYTES:
        return HttpResponse(status=204)

    ip_key = f'csp:ip:{_client_ip(request)}'
    if cache.add(ip_key, 1, PER_IP_WINDOW):
        count = 1
    else:
        try:
            count = cache.incr(ip_key)
        except ValueError:
            count = 1
    if count > PER_IP_LIMIT:
        return HttpResponse(status=204)

    try:
        payload = json.loads(request.body[:MAX_BODY_BYTES] or b'null')
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=204)

    for item in _normalize(payload):
        directive = str(item['directive'])[:60]
        blocked = _path(str(item['blocked']))
        document = _path(str(item['document']))
        source = _path(str(item['source']))
        line = str(item['line'])[:10]
        digest = hashlib.sha1(f'{directive}|{blocked}|{document}|{source}|{line}'.encode()).hexdigest()
        if not cache.add(f'csp:seen:{digest}', 1, DEDUPE_SECONDS):
            continue
        logger.warning(
            'CSP violation directive=%s blocked=%s page=%s source=%s:%s sample=%r',
            directive, blocked, document, source, line, str(item['sample'])[:80],
        )
    return HttpResponse(status=204)
