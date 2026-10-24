from django import template
from community.rookie_env_presentation import game_conditions, split_groups

register = template.Library()
register.filter('game_conditions', game_conditions)


@register.simple_tag
def env_split_groups(rows, role=''):
    role = role or ('pitcher' if rows and rows[0].get('rate_label') == '평균자책점' else 'batter')
    return split_groups(role, rows or [])
