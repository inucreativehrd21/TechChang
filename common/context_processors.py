import secrets
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
