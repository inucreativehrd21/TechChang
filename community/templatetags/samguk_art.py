"""삼국지 그림 표시만 담당해요. 판정과 도감 공개 여부는 서버 데이터가 정해요."""
from functools import lru_cache
import json
from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@lru_cache(maxsize=1024)
def _portrait(code):
    from community import samguk_data as D
    from community import samguk_legends as L
    g = D.GENERAL.get(code) or L.HIDDEN.get(code)
    if not g:
        return '_unknown', ''
    path = Path(settings.BASE_DIR) / 'static' / 'samguk' / 'officer' / '160' / f'{g.code}.webp'
    if path.is_file():
        return g.code, g.name
    group = g.group if g.group in D.GROUPS else 'qun'
    return f'_common_{group}_{"f" if g.female else "m"}', g.name


@register.simple_tag
def sg_portrait(code, state='recruited', large=False):
    art, name = ('_unknown', '미발견 장수') if state == 'unknown' else _portrait(str(code))
    folder = '' if large else '160/'
    return format_html('<img class="sg-portrait" src="{}" alt="{}" width="160" height="160" loading="lazy" decoding="async">',
                       static(f'samguk/officer/{folder}{art}.webp'), name)


@register.simple_tag
def sg_name(code):
    return _portrait(str(code))[1]


@register.inclusion_tag('community/samguk/_map_art.html')
def sg_map(cities):
    lookup = {c['code']: c for c in cities}
    edges, markers = [], []
    for c in cities:
        markers.append({**c, 'left': c['x'] / 10, 'top': c['y'] / 10})
        for code in c['links']:
            if code in lookup and c['code'] < code:
                edges.append({'a': c, 'b': lookup[code]})
    return {'markers': markers, 'edges': edges}


@lru_cache(maxsize=1)
def _manor_coordinates():
    folder = Path(settings.BASE_DIR) / 'static' / 'samguk' / 'manor'
    return (json.loads((folder / 'slots.json').read_text(encoding='utf-8')),
            json.loads((folder / 'building-slots.json').read_text(encoding='utf-8')))


@register.inclusion_tag('community/samguk/_manor_art.html')
def sg_manor_art(manor):
    people, places = _manor_coordinates()
    buildings, decor, officers = [], [], []
    for b in manor['buildings']:
        x, y, width = places[b['code']]
        buildings.append({**b, 'x': x / 10, 'y': y / 10, 'width': width / 10,
                          'path': f"samguk/manor/buildings/{b['code']}-{b['level']}.webp"})
    for d in manor['decor']:
        if not d['decor']:
            continue
        x, y, width = places[d['slot']]
        decor.append({**d, 'x': x / 10, 'y': y / 10, 'width': width / 10,
                      'path': f"samguk/manor/decor/{d['decor']}.webp"})
    for p in manor['placed']:
        x, y = people[p['slot']]
        officers.append({**p, 'x': x / 10, 'y': y / 10})
    return {'buildings': buildings, 'decor': decor, 'officers': officers}
