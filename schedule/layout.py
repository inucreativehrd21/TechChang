"""월간 달력 배치 계산 — 화면(템플릿)은 계산 결과를 그리기만 한다.

한 주는 CSS 그리드 한 줄이다. 여러 날 일정은 주 안에서 '차선(lane)'을 배정받아 가로 막대로 그리고,
하루짜리 일정은 막대 차선 아래에 칸별로 쌓는다. 차선이 넘치거나 칸이 넘치는 일정은 '+N'으로 접는다.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, time

KIND_ORDER = {'community': 0, 'mine': 1, 'lab': 2}
MAX_LANES = 3
MAX_SINGLES = 3


@dataclass
class Item:
    """달력에 그리는 일정 한 건 (회원 일정이든 사이트 피드든 같은 모양)."""
    key: str
    title: str
    start_date: date
    end_date: date
    kind: str                       # 'mine' | 'community' | 'lab'
    start_time: time | None = None
    end_time: time | None = None
    icon: str = ''
    url: str = ''
    note: str = ''
    location: str = ''
    public: bool = True
    listed: bool = True

    @property
    def is_multi_day(self) -> bool:
        return self.end_date > self.start_date

    @property
    def day_sort_key(self):
        """하루 안에서의 순서: 종일 일정 먼저, 그다음 시각 순."""
        return (self.start_time is not None, self.start_time or time.min,
                KIND_ORDER.get(self.kind, 9), self.title)

    def covers(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date


@dataclass
class Day:
    date: date
    col: int
    in_month: bool
    is_today: bool
    items: list[Item] = field(default_factory=list)
    more: int = 0
    weather: dict | None = None
    kinds: list[str] = field(default_factory=list)   # 그날 걸친 일정 종류(모바일 칸 표시용)

    @property
    def weekday(self) -> int:       # 0=월 … 6=일
        return self.date.weekday()


@dataclass
class Bar:
    item: Item
    col: int                        # 1~7
    span: int
    lane: int                       # 1~MAX_LANES
    cont_left: bool                 # 지난주에서 이어짐
    cont_right: bool                # 다음 주로 이어짐


@dataclass
class Week:
    days: list[Day]
    bars: list[Bar]
    lanes: int


def month_dates(year: int, month: int, first_weekday: int) -> list[list[date]]:
    return calendar.Calendar(firstweekday=first_weekday).monthdatescalendar(year, month)


def build_month(year: int, month: int, items: list[Item], *, first_weekday: int, today: date,
                weather: dict | None = None, max_lanes: int = MAX_LANES,
                max_singles: int = MAX_SINGLES) -> list[Week]:
    weather = weather or {}
    weeks: list[Week] = []
    for dates in month_dates(year, month, first_weekday):
        days = [Day(date=d, col=i + 1, in_month=(d.month == month), is_today=(d == today),
                    weather=weather.get(d.isoformat()))
                for i, d in enumerate(dates)]
        week_start, week_end = dates[0], dates[-1]
        by_date = {d.date: d for d in days}

        multi = [it for it in items
                 if it.is_multi_day and it.start_date <= week_end and it.end_date >= week_start]
        multi.sort(key=lambda it: (max(it.start_date, week_start),
                                   -(min(it.end_date, week_end) - max(it.start_date, week_start)).days,
                                   KIND_ORDER.get(it.kind, 9), it.title))
        lane_ends: list[int] = []
        bars: list[Bar] = []
        for it in multi:
            s, e = max(it.start_date, week_start), min(it.end_date, week_end)
            col_s, col_e = (s - week_start).days + 1, (e - week_start).days + 1
            lane = next((i for i, end_col in enumerate(lane_ends) if end_col < col_s), None)
            if lane is None:
                lane_ends.append(col_e)
                lane = len(lane_ends) - 1
            else:
                lane_ends[lane] = col_e
            if lane < max_lanes:
                bars.append(Bar(item=it, col=col_s, span=col_e - col_s + 1, lane=lane + 1,
                                cont_left=it.start_date < week_start, cont_right=it.end_date > week_end))
            else:
                for offset in range(col_s - 1, col_e):
                    days[offset].more += 1

        for it in sorted((it for it in items if not it.is_multi_day), key=lambda it: it.day_sort_key):
            day = by_date.get(it.start_date)
            if day is None:
                continue
            if len(day.items) < max_singles:
                day.items.append(it)
            else:
                day.more += 1

        for day in days:
            day.kinds = sorted({it.kind for it in items if it.covers(day.date)},
                               key=lambda k: KIND_ORDER.get(k, 9))

        weeks.append(Week(days=days, bars=bars, lanes=min(len(lane_ends), max_lanes)))
    return weeks


def items_on(day: date, items: list[Item]) -> list[Item]:
    """그날에 걸친 일정 전부(여러 날 일정 포함), 하루 안 순서대로."""
    return sorted((it for it in items if it.covers(day)), key=lambda it: it.day_sort_key)
