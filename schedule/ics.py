"""iCalendar(RFC 5545) 내보내기 — 구글·애플·아웃룩 캘린더에서 '구독'할 수 있는 형식."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone

from .layout import Item


def _esc(text: str) -> str:
    return (text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n'))


def _fold(line: str) -> str:
    """한 줄 75옥텟 제한 — 한글(3바이트)이 중간에서 잘리지 않게 글자 단위로 접는다."""
    if len(line.encode('utf-8')) <= 75:
        return line
    parts, cur, limit = [], '', 75
    for ch in line:
        if len((cur + ch).encode('utf-8')) > limit:
            parts.append(cur)
            cur, limit = ch, 74          # 이어지는 줄은 맨 앞 공백 1옥텟을 뺀다
        else:
            cur += ch
    parts.append(cur)
    return '\r\n '.join(parts)


def _utc(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def build_ics(items: list[Item], *, name: str, host: str, absolute) -> str:
    """absolute(path) -> 절대 URL. 시각 있는 일정은 사이트 시간대 기준으로 UTC 변환한다."""
    now = timezone.now()
    tz = timezone.get_current_timezone()
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//TechChang//Myochil//KO', 'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH', f'X-WR-CALNAME:{_esc(name)}', f'X-WR-TIMEZONE:{tz}',
    ]
    for it in items:
        lines += ['BEGIN:VEVENT', f'UID:{it.key}@{host}', f'DTSTAMP:{_utc(now)}']
        if it.start_time is None:
            lines.append(f'DTSTART;VALUE=DATE:{it.start_date:%Y%m%d}')
            lines.append(f'DTEND;VALUE=DATE:{it.end_date + timedelta(days=1):%Y%m%d}')
        else:
            start = timezone.make_aware(datetime.combine(it.start_date, it.start_time), tz)
            if it.end_time:
                end = timezone.make_aware(datetime.combine(it.end_date, it.end_time), tz)
            else:
                end = start + timedelta(hours=1) if not it.is_multi_day else \
                    timezone.make_aware(datetime.combine(it.end_date, it.start_time), tz)
            lines += [f'DTSTART:{_utc(start)}', f'DTEND:{_utc(max(end, start))}']
        lines.append(f'SUMMARY:{_esc(it.title)}')
        if it.location:
            lines.append(f'LOCATION:{_esc(it.location)}')
        if it.note:
            lines.append(f'DESCRIPTION:{_esc(it.note)}')
        if it.url:
            lines.append(f'URL:{absolute(it.url)}')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'
