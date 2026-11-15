from django import template

from common.navigation import auth_destination, safe_destination

register = template.Library()


@register.simple_tag(takes_context=True)
def navigation_next(context):
    request = context['request']
    if request.path in ('/common/login/', '/common/signup/'):
        return auth_destination(request)
    return safe_destination(request, request.get_full_path())
