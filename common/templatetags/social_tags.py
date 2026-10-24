from django import template
from common.social_views import PROVIDERS, enabled
from common.login_views import LINK_PROMPT_SESSION_KEY

register = template.Library()


@register.simple_tag
def social_enabled(provider):
    return enabled(provider)


@register.simple_tag(takes_context=True)
def account_link_prompt(context):
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    if request.session.get(LINK_PROMPT_SESSION_KEY) != request.user.pk:
        return False
    # 인증·동의·설정 화면에서는 작업을 방해하지 않고 다음 일반 화면까지 기다려요.
    match = request.resolver_match
    if match and match.namespace == 'common' and match.url_name != 'force_email_verification':
        return False
    request.session.pop(LINK_PROMPT_SESSION_KEY, None)
    return not request.user.social_identities.exists() and any(enabled(p) for p in PROVIDERS)


@register.simple_tag
def account_login_methods(user):
    methods = ['아이디·비밀번호'] if user.has_usable_password() else []
    methods.extend(identity.get_provider_display() for identity in user.social_identities.all())
    return ' / '.join(methods) or '로그인 수단 없음'
