from django import template
from community import rookie_avatar as Avatar

register=template.Library()

@register.inclusion_tag('community/games/_rookie_avatar.html')
def player_avatar(player=None,state='idle',size=4,formal=False):
    return {'avatar':Avatar.presentation(player,state,size,formal)}

@register.inclusion_tag('community/games/_rookie_avatar_picker.html')
def rookie_avatar_picker():
    return Avatar.picker()
