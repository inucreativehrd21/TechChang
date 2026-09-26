
import json

import markdown
import bleach
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# XSS 방어: bleach로 허용할 HTML 태그와 속성 정의
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 'a', 'ul', 'ol', 'li',
    'blockquote', 'code', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'del', 'ins',
    'div', 'span', 'img'
]
ALLOWED_ATTRS = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title'],
    'code': ['class'],
    'pre': ['class'],
    'div': ['class'],
    'span': ['class']
}


@register.filter
def sub(value, arg):
    return value - arg

@register.filter
def mul(value, arg):
    """Multiply the value by the argument"""
    try:
        return int(value) * int(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def mark(value):
    """마크다운을 HTML로 변환하고 XSS 공격 방어"""
    extensions = ["nl2br", "fenced_code", "tables"]
    html = markdown.markdown(value, extensions=extensions)
    # bleach로 위험한 HTML 태그/속성 제거 (XSS 방어)
    clean_html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    return mark_safe(clean_html)


@register.filter
def as_json(value):
    """문자열을 JSON 리터럴로 — JSON-LD 안에 안전하게 넣기 위한 필터.

    따옴표·줄바꿈·백슬래시를 이스케이프하고, </script> 로 스크립트가 조기에 닫히는
    것을 막는다. 값은 이미 JSON 문자열(따옴표 포함)이므로 템플릿에서 따로 감싸지 않는다.
    """
    dumped = json.dumps('' if value is None else str(value), ensure_ascii=False)
    return mark_safe(dumped.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))


@register.filter
def get_item(dictionary, key):
    """딕셔너리에서 키로 값 조회 (없으면 0 반환)"""
    try:
        return dictionary.get(key, 0)
    except Exception:
        return 0
