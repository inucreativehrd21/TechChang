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
    return {
        'theme_class': f"theme-{get_theme_for_request(request)}"
    }
