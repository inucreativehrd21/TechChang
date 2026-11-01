"""수치의 소수점·규모·단위를 보존한다. 주제·모집단·시점 검증을 대신하지 않는다."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

NUMBER = re.compile(r'(?<![\d.,A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?')
SCALE = re.compile(r'\s*(billion|million|thousand|억|만|천)\b|\s*(억|만|천)', re.I)
SCALES = {'billion': '1000000000', 'million': '1000000', 'thousand': '1000',
          '억': '100000000', '만': '10000', '천': '1000'}
UNITS = [
    ('USD', r'(?:달러|USD|US\s*dollars?|dollars?)'),
    ('KRW', r'(?:원|KRW|won)'),
    ('percent_point', r'(?:%p|percentage\s+points?)'),
    ('percent', r'(?:%|percent\b)'),
    ('person', r'(?:명|(?:coach\s+)?practitioners?\b|people\b|persons?\b|respondents?\b|developers?\b|participants?\b|coaches\b)'),
    ('case', r'(?:건|cases?\b|responses?\b)'),
    ('country', r'(?:개국|countries\b)'),
    ('count', r'(?:개|행|rows?\b|items?\b)'),
    ('second', r'(?:초|seconds?\b)'),
    ('times', r'(?:배|times\b)'),
]


def decimal_key(raw: str) -> str:
    try:
        value = Decimal(raw.replace(',', '').strip())
        return format(value.normalize(), 'f') if value.is_finite() else ''
    except (InvalidOperation, ValueError):
        return ''


@dataclass(frozen=True)
class Quantity:
    raw: str
    value: str
    unit: str
    start: int
    end: int

    @property
    def key(self):
        return self.value, self.unit


def extract(text: str) -> list[Quantity]:
    result = []
    for match in NUMBER.finditer(text or ''):
        value = Decimal(match.group().replace(',', ''))
        end = match.end()
        tail = text[end:]
        scale = SCALE.match(tail)
        if scale:
            value *= Decimal(SCALES[(scale.group(1) or scale.group(2)).lower()])
            end += scale.end()
        unit = ''
        # 괄호로 된 USD 표기와 통화 접두사를 함께 읽는다.
        after = re.sub(r'^[\s(]+', '', text[end:])
        for name, pattern in UNITS:
            found = re.match(pattern, after, re.I)
            if found:
                unit = name
                break
        prefix = text[max(0, match.start()-4):match.start()].rstrip()
        if prefix.endswith('$'):
            unit = 'USD'
        elif prefix.endswith('₩'):
            unit = 'KRW'
        result.append(Quantity(match.group(), format(value.normalize(), 'f'), unit, match.start(), end))
    return result
