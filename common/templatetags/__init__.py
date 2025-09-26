from django import template
from common.models import Profile

register = template.Library()

@register.filter
def display_name(user):
    """사용자의 표시명을 반환 (닉네임이 있으면 닉네임, 없으면 사용자명)"""
    try:
        profile = user.profile
        return profile.display_name
    except Profile.DoesNotExist:
        return user.username

@register.filter  
def display_name_initial(user):
    """사용자 표시명의 첫 글자를 반환"""
    try:
        profile = user.profile
        return profile.display_name[0:1]
    except (Profile.DoesNotExist, IndexError):
        return user.username[0:1] if user.username else 'U'