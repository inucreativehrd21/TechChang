"""야구선수 키우기 템플릿 필터 — 기록 행에 남은 소속(프로 구단 코드 또는 학교 이름)·리그 코드 → 이름·색."""
from django import template

from community import rookie_world as W

register = template.Library()


@register.filter
def baseball_text(value):
    """과거 JSON·기록의 야구 용어도 현재 표시 기준으로 보여 준다. HTML은 그대로 이스케이프한다."""
    from community.rookie_text import display
    return display(value)


@register.filter
def man(n):
    """게임 금액(만원)을 기존 표기와 같은 단위로 보여 준다."""
    from community.rookie_lite import man as format_money
    return format_money(n)


@register.filter
def comma(n):
    """4980 → '4,980' — 숫자가 아니면 그대로."""
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return n


@register.filter
def team_color(code):
    return W.team_color(code)


@register.filter
def team_name(code):
    return W.team_label(code)


@register.filter
def team_short(code):
    return W.club_short('', code)


@register.filter
def league_short(code):
    return W.short(code)


@register.filter
def league_name(code):
    return W.league(code)['name']
