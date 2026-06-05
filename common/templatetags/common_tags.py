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


@register.filter
def split_skills(value):
    """스킬 값을 리스트로 정규화.

    skills는 JSONField(list)지만, 과거 데이터/입력에 따라 콤마 구분 문자열이
    들어올 수 있어 둘 다 안전하게 처리한다. 빈 값은 빈 리스트를 반환.
    """
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(s).strip() for s in value if str(s).strip()]
    return [s.strip() for s in str(value).split(',') if s.strip()]