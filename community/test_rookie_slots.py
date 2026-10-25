"""정식 판 시간대 경기(rookie_clock·simulate_slots·rookie_tick) — 시간 경계(docs/rookie-full-remake-proposal.md 11장)."""
import random
from io import StringIO
from datetime import datetime, time, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from community import rookie_clock as Clock
from community import rookie_league as L
from community.models import RookieGame, RookieLog, RookieSeason
from community.test_rookie_league import active_on, player

ON = dict(ROOKIE_FULL_SLOTS='true', ROOKIE_SLOTS_FROM_SEASON='2', ROOKIE_FULL_HALVES='false')
D = L.season_bounds(2)[0]                         # 시즌 2 개막일


def at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


@override_settings(**ON)
class SlotBoundaryTests(TestCase):
    def setUp(self):
        self.bat = player('시간타자', 'batter', 'lg', 'SS')
        active_on(self.bat, D)
        self.plan = [s for s, _r in Clock.day_plan('kbo1', D)]      # 개막일 시간대(뒤쪽부터 채움)

    def games(self, p=None, day=D):
        return RookieGame.objects.filter(player=p or self.bat, day=day).count()

    def test_runs_only_slots_whose_time_has_passed(self):
        cut = Clock.SLOTS[self.plan[1]]
        n = L.simulate_slots(D, upto=at(D, cut.hour, cut.minute + 1), rng=random.Random(1))
        self.assertEqual(n, 2)                                         # 시간대마다 한 번씩 진행(선수 1명 × 2)
        self.assertEqual(self.games(), 2)
        s = RookieSeason.objects.get(number=2)
        self.assertEqual(s.slot_through, Clock.slot_at(D, self.plan[1]))
        self.assertIsNone(s.simulated_through)                         # 그날은 아직 끝나지 않았다
        self.assertEqual(L.simulate_slots(D, upto=at(D, cut.hour, cut.minute + 1)), 0)   # 같은 시간대를 두 번 치르지 않는다
        self.assertEqual(self.games(), 2)
        self.assertEqual(sorted(g.line['at'] for g in RookieGame.objects.filter(player=self.bat)),
                         sorted(Clock.label(s) for s in self.plan[:2]))

    def test_one_minute_before_the_slot_nothing_happens(self):
        first = Clock.SLOTS[self.plan[0]]
        self.assertEqual(L.simulate_slots(D, upto=at(D, first.hour, first.minute) - timedelta(minutes=1)), 0)
        self.assertEqual(L.simulate_slots(D, upto=at(D, first.hour, first.minute)), 1)   # 정각이면 그 경기

    def test_activity_after_a_slot_counts_from_the_next_slot(self):
        late = player('늦은타자', 'batter', 'kia', 'SS')
        RookieLog.objects.filter(player=late).update(day=D - timedelta(days=10))
        log = RookieLog.objects.create(player=late, kind='earn', source='checkin', ref='x', tp=20, text='출석', day=D)
        third = Clock.SLOTS[self.plan[2]]
        RookieLog.objects.filter(pk=log.pk).update(created_at=at(D, third.hour, third.minute) - timedelta(minutes=30))
        L.simulate_slots(D, upto=at(D, 23), rng=random.Random(2))
        self.assertEqual(self.games(late), len(self.plan) - 2)        # 활동한 뒤의 시간대부터 엔트리
        self.assertEqual(self.games(), len(self.plan))

    def test_missed_cron_is_caught_up_the_next_day(self):
        L.simulate_slots(D, upto=at(D, 13, 1), rng=random.Random(3))
        L.advance(today=D + timedelta(days=1))                         # 밤 cron·화면이 남은 시간대와 마무리를 치른다
        self.assertEqual(self.games(), len(self.plan))
        s = RookieSeason.objects.get(number=2)
        self.assertEqual(s.simulated_through, D)
        self.assertEqual(s.slot_through, Clock.slot_at(D, len(Clock.SLOTS) - 1))

    def test_midnight_settles_yesterday_and_waits_for_first_slot(self):
        active_on(self.bat, D + timedelta(days=1))
        with mock.patch('django.utils.timezone.now', return_value=at(D + timedelta(days=1), 0, 5)):
            L.advance()
        self.assertEqual(self.games(), len(self.plan))
        self.assertEqual(self.games(day=D + timedelta(days=1)), 0)    # 다음 날 첫 경기 시각 전
        with mock.patch('django.utils.timezone.now', return_value=at(D + timedelta(days=1), 22, 1)):
            L.advance()
        self.assertEqual(self.games(day=D + timedelta(days=1)), len(Clock.day_plan('kbo1', D + timedelta(days=1))))

    def test_tick_command(self):
        last = Clock.SLOTS[self.plan[-1]]
        with mock.patch('django.utils.timezone.now', return_value=at(D, last.hour, last.minute + 2)):
            call_command('rookie_tick', stdout=StringIO())
        self.assertEqual(self.games(), len(self.plan))
        self.assertEqual(RookieSeason.objects.get(number=2).simulated_through, D)

    def test_role_is_decided_once_a_day(self):
        L.simulate_slots(D, upto=at(D, 23), rng=random.Random(4))
        self.bat.refresh_from_db()
        self.assertEqual(self.bat.career.get('role_day'), D.isoformat())

    @override_settings(ROOKIE_FULL_SLOTS='false')
    def test_switch_off_tick_is_noop(self):
        with mock.patch('django.utils.timezone.now', return_value=at(D, 23)):
            call_command('rookie_tick', stdout=StringIO())
        self.assertEqual(self.games(), 0)
