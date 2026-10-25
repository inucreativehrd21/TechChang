"""기상청 응답 요약과 ICS 줄 접기·이스케이프."""
from datetime import date, time

from django.test import SimpleTestCase

from schedule import ics, weather
from schedule.layout import Item

REG = '11B10101'


def row(tm_fc, tm_ef, ta, st, sky='DB03', prep='0'):
    # REG_ID TM_FC TM_EF MOD NE STN C MAN_ID MAN_FC W1 T W2 TA ST SKY PREP WF
    return f'{REG} {tm_fc} {tm_ef} A01 2 109 2 111 1 SW 1 W {ta} {st} {sky} {prep} "x"'


class WeatherSummaryTests(SimpleTestCase):
    def test_summary_recovers_past_slot_temperature_from_previous_announcement(self):
        text = '\n'.join([
            '# header',
            row('202610150500', '202610160000', '14', '20'),            # 이전 발표: 16일 새벽 14도
            row('202610150500', '202610161200', '22', '20'),
            row('202610151700', '202610160000', '-99', '30'),           # 최신 발표는 지난 구간을 -99 로
            row('202610151700', '202610161200', '23', '60', sky='DB04', prep='1'),
            row('202610151700', '202610170000', '13', '10', sky='DB01'),
            row('202610151700', '202610171200', '25', '10', sky='DB01'),
            'OTHER 202610151700 202610171200 A01 2 109 2 111 1 SW 1 W 99 99 DB01 0 "x"',
        ])
        announced, days = weather.summarize(weather.parse_rows(text, REG))
        self.assertEqual(announced, '202610151700')
        self.assertEqual(days['2026-10-16'], {'condition': '비', 'icon': weather.ICONS['rain'],
                                              'temp_low': 14, 'temp_high': 23, 'rain_prob': 60})
        self.assertEqual(days['2026-10-17']['condition'], '맑음')
        self.assertEqual(days['2026-10-17']['temp_low'], 13)

    def test_single_slot_day_has_no_low(self):
        _, days = weather.summarize(weather.parse_rows(row('202610151700', '202610151200', '21', '60'), REG))
        self.assertIsNone(days['2026-10-15']['temp_low'])
        self.assertEqual(days['2026-10-15']['temp_high'], 21)

    def test_announce_window(self):
        from datetime import datetime
        self.assertEqual(weather.announce_window(datetime(2026, 10, 16, 7, 0)), ('202610151800', '202610161800'))
        self.assertEqual(weather.announce_window(datetime(2026, 10, 16, 3, 0)), ('202610150600', '202610160600'))


class IcsTests(SimpleTestCase):
    def test_escape_and_fold(self):
        long_title = '연구실 위클리 발행 기념, 데이터분석; 프로그래밍 ' * 4
        body = ics.build_ics(
            [Item(key='event:1', title=long_title, start_date=date(2026, 10, 16), end_date=date(2026, 10, 16),
                  kind='community', start_time=time(19), end_time=time(21), location='강남, 3층', url='/calendar/event/1/')],
            name='며칠', host='techchang.com', absolute=lambda path: f'https://techchang.com{path}')
        lines = body.split('\r\n')
        self.assertTrue(all(len(line.encode()) <= 75 for line in lines))
        unfolded = body.replace('\r\n ', '')
        self.assertIn('LOCATION:강남\\, 3층', unfolded)
        self.assertIn('데이터분석\\; 프로그래밍', unfolded)
        self.assertIn('DTSTART:20261016T100000Z', unfolded)          # 19시 KST = 10시 UTC
        self.assertIn('DTEND:20261016T120000Z', unfolded)
        self.assertIn('URL:https://techchang.com/calendar/event/1/', unfolded)
        self.assertIn('UID:event:1@techchang.com', unfolded)

    def test_all_day_multi_day_end_is_exclusive(self):
        body = ics.build_ics([Item(key='event:2', title='워크숍', start_date=date(2026, 10, 19),
                                   end_date=date(2026, 10, 21), kind='community')],
                             name='며칠', host='h', absolute=str)
        self.assertIn('DTSTART;VALUE=DATE:20261019', body)
        self.assertIn('DTEND;VALUE=DATE:20261022', body)
