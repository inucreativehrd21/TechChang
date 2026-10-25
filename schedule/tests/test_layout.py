"""월간 배치 계산: 첫 요일, 여러 날 막대의 차선 배정·주 경계 분할, 넘침(+N)."""
from datetime import date, time

from django.test import SimpleTestCase

from schedule.layout import MAX_LANES, MAX_SINGLES, Item, build_month, items_on

TODAY = date(2026, 10, 16)


def item(key, start, end=None, kind='mine', at=None):
    return Item(key=key, title=key, start_date=start, end_date=end or start, kind=kind, start_time=at)


def week_of(weeks, day):
    return next(w for w in weeks if any(d.date == day for d in w.days))


class MonthGridTests(SimpleTestCase):
    def test_sunday_first_grid(self):
        weeks = build_month(2026, 10, [], first_weekday=6, today=TODAY)
        self.assertEqual(weeks[0].days[0].date, date(2026, 9, 27))       # 일요일
        self.assertEqual(weeks[-1].days[-1].date, date(2026, 10, 31))
        self.assertTrue(all(len(w.days) == 7 for w in weeks))
        today_cells = [d for w in weeks for d in w.days if d.is_today]
        self.assertEqual([d.date for d in today_cells], [TODAY])

    def test_monday_first_grid(self):
        weeks = build_month(2026, 10, [], first_weekday=0, today=TODAY)
        self.assertEqual(weeks[0].days[0].date, date(2026, 9, 28))       # 월요일

    def test_out_of_month_days_are_flagged(self):
        weeks = build_month(2026, 10, [], first_weekday=6, today=TODAY)
        self.assertFalse(weeks[0].days[0].in_month)
        self.assertTrue(weeks[1].days[0].in_month)


class MultiDayBarTests(SimpleTestCase):
    def test_overlapping_events_get_separate_lanes_and_lanes_are_reused(self):
        items = [
            item('a', date(2026, 10, 13), date(2026, 10, 15)),   # 화~목
            item('b', date(2026, 10, 14), date(2026, 10, 16)),   # 수~금 (a 와 겹침)
            item('c', date(2026, 10, 16), date(2026, 10, 17)),   # 금~토 (a 가 끝난 뒤)
        ]
        week = week_of(build_month(2026, 10, items, first_weekday=6, today=TODAY), date(2026, 10, 13))
        bars = {bar.item.key: bar for bar in week.bars}
        self.assertEqual((bars['a'].col, bars['a'].span, bars['a'].lane), (3, 3, 1))
        self.assertEqual(bars['b'].lane, 2)
        self.assertEqual(bars['c'].lane, 1)
        self.assertEqual(week.lanes, 2)

    def test_event_crossing_week_boundary_is_split(self):
        weeks = build_month(2026, 10, [item('trip', date(2026, 10, 16), date(2026, 10, 20))],
                            first_weekday=6, today=TODAY)
        first = week_of(weeks, date(2026, 10, 16)).bars[0]
        second = week_of(weeks, date(2026, 10, 20)).bars[0]
        self.assertTrue(first.cont_right)
        self.assertFalse(first.cont_left)
        self.assertTrue(second.cont_left)
        self.assertEqual((second.col, second.span), (1, 3))               # 일~화

    def test_lane_overflow_folds_into_more(self):
        items = [item(f'm{i}', date(2026, 10, 12), date(2026, 10, 14)) for i in range(MAX_LANES + 1)]
        week = week_of(build_month(2026, 10, items, first_weekday=6, today=TODAY), date(2026, 10, 12))
        self.assertEqual(len(week.bars), MAX_LANES)
        self.assertEqual(week.lanes, MAX_LANES)
        covered = [d for d in week.days if date(2026, 10, 12) <= d.date <= date(2026, 10, 14)]
        self.assertTrue(all(d.more == 1 for d in covered))


class SingleDayTests(SimpleTestCase):
    def test_singles_are_sorted_all_day_first_and_overflow(self):
        items = [item(f's{i}', TODAY, at=time(9 + i)) for i in range(MAX_SINGLES + 2)]
        items.append(item('allday', TODAY))
        day = next(d for w in build_month(2026, 10, items, first_weekday=6, today=TODAY)
                   for d in w.days if d.date == TODAY)
        self.assertEqual(day.items[0].key, 'allday')
        self.assertEqual(len(day.items), MAX_SINGLES)
        self.assertEqual(day.more, 3)

    def test_kinds_cover_multi_day_events(self):
        items = [item('trip', date(2026, 10, 15), date(2026, 10, 17), kind='community'),
                 item('memo', TODAY, kind='lab')]
        day = next(d for w in build_month(2026, 10, items, first_weekday=6, today=TODAY)
                   for d in w.days if d.date == TODAY)
        self.assertEqual(day.kinds, ['community', 'lab'])

    def test_items_on_includes_spanning_events(self):
        items = [item('trip', date(2026, 10, 15), date(2026, 10, 17)), item('other', date(2026, 10, 18))]
        self.assertEqual([it.key for it in items_on(TODAY, items)], ['trip'])
