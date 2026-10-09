import secrets
from django.conf import settings
from django.utils.functional import SimpleLazyObject
from django.contrib.auth import get_user_model

from .models import Profile

User = get_user_model()

def get_theme_for_request(request):
    # 우선순위: 로그인 프로필 -> 쿠키 -> 기본(light)
    if request.user.is_authenticated:
        try:
            return request.user.profile.theme
        except Profile.DoesNotExist:
            return Profile.THEME_LIGHT
    cookie_theme = request.COOKIES.get('site_theme')
    if cookie_theme in {t[0] for t in Profile.THEME_CHOICES}:
        return cookie_theme
    return Profile.THEME_LIGHT


def static_version(request):
    """정적 파일 캐시 무효화 키 (settings.STATIC_VERSION)"""
    return {'STATIC_VERSION': settings.STATIC_VERSION}


def theme_context(request):
    """테마 및 CSP nonce, 모바일 감지 정보를 템플릿에 제공"""
    # CSP nonce 생성 (요청당 1회만 생성)
    if not hasattr(request, '_csp_nonce'):
        request._csp_nonce = secrets.token_urlsafe(16)

    return {
        'theme_class': f"theme-{get_theme_for_request(request)}",
        'current_theme': get_theme_for_request(request),
        'csp_nonce': request._csp_nonce,
        # 모바일 감지 정보 (Phase 3에서 미들웨어가 설정)
        'is_mobile': getattr(request, 'is_mobile', False),
        'is_forced_version': getattr(request, 'is_forced', False),
    }


# 목록(홈)에서 '다른 내용'을 만드는 쿼리만 대표 주소에 남긴다. sort·kw 등은 같은 글을
# 다르게 늘어놓을 뿐이라 대표 주소에서 뺀다 — GSC '사용자가 선택한 표준이 없는 중복 페이지'
# 41건의 주 원인이 /N/?sort=…, /?category=…&sort=… 같은 변형이었다(2026-10-09).
CANONICAL_KEEP_PARAMS = ('category', 'page')
# 검색 결과만 noindex. 정렬 변형은 canonical 로 묶는다(canonical+noindex 동시 사용은 구글이 상충 신호로 본다).
NOINDEX_PARAMS = ('kw',)


def seo(request):
    """대표 주소(canonical)와 기본 robots 지시 — PC·모바일 베이스가 같은 값을 쓴다."""
    path = request.path
    keep = []
    if path == '/':
        for key in CANONICAL_KEEP_PARAMS:
            value = request.GET.get(key)
            if value and not (key == 'page' and value == '1'):
                keep.append((key, value))
    from urllib.parse import urlencode
    canonical = f'https://techchang.com{path}' + (f'?{urlencode(keep)}' if keep else '')
    noindex = any(request.GET.get(p) for p in NOINDEX_PARAMS)
    return {
        'canonical_url': canonical,
        'seo_robots': 'noindex, follow' if noindex else 'index, follow',
    }
