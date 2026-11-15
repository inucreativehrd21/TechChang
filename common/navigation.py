"""가입과 콘텐츠 탐색에서 사용하는 사이트 내부 복귀 주소."""
from urllib.parse import urlsplit, urlunsplit

from django.utils.http import url_has_allowed_host_and_scheme


def safe_destination(request, value, fallback='/'):
    if not isinstance(value, str) or not value:
        return fallback
    if not url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return fallback
    parts = urlsplit(value)
    if not parts.path.startswith('/') or parts.path.startswith('//'):
        return fallback
    return urlunsplit(('', '', parts.path, parts.query, parts.fragment))


def auth_destination(request):
    value = request.POST.get('next') or request.GET.get('next') or '/'
    target = safe_destination(request, value)
    if urlsplit(target).path in ('/common/login/', '/common/signup/', '/common/logout/'):
        return '/'
    return target
