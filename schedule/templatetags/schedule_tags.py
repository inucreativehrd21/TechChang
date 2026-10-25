from django import template

register = template.Library()

WEEKDAY_KO = ['월', '화', '수', '목', '금', '토', '일']


@register.filter
def ko_weekday(value):
    """date → '목'"""
    return WEEKDAY_KO[value.weekday()] if value else ''


@register.filter
def ko_date(value):
    """date → '10월 16일 (목)'"""
    if not value:
        return ''
    return f'{value.month}월 {value.day}일 ({WEEKDAY_KO[value.weekday()]})'


@register.filter
def ko_short(value):
    """date → '10.16'"""
    return f'{value.month}.{value.day}' if value else ''


@register.filter
def ko_short_day(value):
    """date → '10.16 목'"""
    return f'{value.month}.{value.day} {WEEKDAY_KO[value.weekday()]}' if value else ''


@register.filter
def hm(value):
    """time → '09:30'"""
    return value.strftime('%H:%M') if value else ''


@register.filter
def time_range(item):
    """일정(Item·Event) → '09:30–11:00' / '09:30' / '하루 종일'"""
    start, end = getattr(item, 'start_time', None), getattr(item, 'end_time', None)
    if not start:
        return '하루 종일'
    return f'{start:%H:%M}–{end:%H:%M}' if end else f'{start:%H:%M}'


KIND_LABEL = {'mine': '내 일정', 'community': '커뮤니티 일정', 'lab': '연구실'}


@register.filter
def kind_label(kind):
    return KIND_LABEL.get(kind, '')


@register.filter
def when_short(item):
    """목록 왼쪽 칸: 시각 있으면 '09:30', 없거나 여러 날이면 '종일'"""
    if getattr(item, 'start_time', None) and not getattr(item, 'is_multi_day', False):
        return f'{item.start_time:%H:%M}'
    return '종일'


@register.filter
def date_range(item):
    """일정 → '10월 16일 (목)' 또는 '10월 16일 (목) – 10월 18일 (토)'"""
    if item.end_date and item.end_date != item.start_date:
        return f'{ko_date(item.start_date)} – {ko_date(item.end_date)}'
    return ko_date(item.start_date)
