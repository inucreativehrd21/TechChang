"""야구선수 키우기 템플릿 필터 — 구단 코드 → 이름·색(기록 행에는 코드만 남아 있다)."""
from django import template

from community import rookie as R

register = template.Library()


@register.filter
def team_color(code):
    return R.TEAM.get(code, {}).get('color', '#4f46e5')


@register.filter
def team_name(code):
    return R.TEAM.get(code, {}).get('name', code)


@register.filter
def team_short(code):
    return R.TEAM.get(code, {}).get('short', code)
