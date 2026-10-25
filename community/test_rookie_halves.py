"""정식 판 전·후기 리그(2026-10-25 사용자 결정) — 모든 리그가 같은 시간 흐름에서 반기를 고르게 치르고 마치는지."""
from collections import Counter
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from . import rookie_clock as Clock
from . import rookie_league as L
from . import rookie_universe as U
from . import rookie_world as W

ON = dict(ROOKIE_FULL_SLOTS='true', ROOKIE_FULL_HALVES='true', ROOKIE_SLOTS_FROM_SEASON='2')


class SplitScheduleTests(SimpleTestCase):
    def test_every_club_plays_half_its_games_in_each_half(self):
        for lg in W.LEAGUES:
            games = L.season_games(lg)
            clubs, rounds = U.schedule(lg, games, True)
            if not clubs:
                continue
            cut = len(rounds) // 2
            self.assertEqual(len(rounds) % 2, 0, lg)
            for part in (rounds[:cut], rounds[cut:]):
                seen = Counter(i for pairs in part for pair in pairs for i in pair)
                self.assertEqual({seen[i] for i in range(len(clubs))}, {games // 2}, lg)

    def test_second_half_swaps_home_and_away(self):
        clubs, rounds = U.schedule('kbo2', 144, True)
        cut = len(rounds) // 2
        self.assertEqual(rounds[cut], tuple((b, a) for a, b in rounds[0]))

    def test_without_split_the_schedule_is_unchanged(self):
        self.assertEqual(U.schedule('little', 28), U.schedule('little', 28, False))
        self.assertEqual(len(U.schedule('little', 28)[1]), 35)          # 예전 대진(라이트·시즌 1)
        self.assertEqual(len(U.schedule('little', 28, True)[1]), 42)


@override_settings(**ON)
class SplitClockTests(SimpleTestCase):
    def test_all_leagues_finish_each_half_on_its_last_day(self):
        start, _end = L.season_bounds(2)
        for lg in W.LEAGUES:
            clubs, rounds = U.schedule(lg, L.season_games(lg), True)
            if not clubs:
                continue
            half = L.season_games(lg) // 2
            first, second = Counter(), Counter()
            for k in range(L.SEASON_DAYS):
                day = start + timedelta(days=k)
                for club in clubs:
                    (first if k < Clock.HALF_DAYS else second)[club] += len(Clock.club_games_on(lg, club, day))
            self.assertEqual(set(first.values()), {half}, lg)
            self.assertEqual(set(second.values()), {half}, lg)
            last = Clock.day_plan(lg, start + timedelta(days=Clock.HALF_DAYS - 1))[-1][1]
            self.assertEqual(last, len(rounds) // 2 - 1, lg)            # 14일 마지막 시간대 = 전기 마지막 라운드
            self.assertEqual(Clock.day_plan(lg, start + timedelta(days=L.SEASON_DAYS - 1))[-1][1], len(rounds) - 1, lg)

    def test_half_of_day(self):
        start, end = L.season_bounds(2)
        self.assertEqual(Clock.half_of(start), 1)
        self.assertEqual(Clock.half_of(start + timedelta(days=13)), 1)
        self.assertEqual(Clock.half_of(start + timedelta(days=14)), 2)
        self.assertEqual(Clock.half_of(end), 2)
        self.assertIsNone(Clock.half_of(end + timedelta(days=1)))       # 쉬는 날 — 가을야구 자리
        self.assertIsNone(Clock.half_of(L.season_bounds(1)[0]))          # 시작 시즌 전

    @override_settings(ROOKIE_FULL_HALVES='false')
    def test_switch_off_keeps_one_season(self):
        self.assertIsNone(Clock.half_of(L.season_bounds(2)[0]))
        self.assertFalse(Clock.split_season(3))


class HalfTableTests(SimpleTestCase):
    def player(self, club='lg'):
        return SimpleNamespace(pk=7, club=club, league='kbo1', career={})

    def test_half_tables_and_finalists(self):
        p = self.player()
        rounds = len(U.schedule('kbo1', 144, True)[1])
        U.advance(p, 2, 'kbo1', 144, rounds // 2 - 1, split=True)
        mid = U.half_tables(p)
        self.assertEqual(mid['half'], 1)
        self.assertIsNone(mid['first_champ'])
        U.advance(p, 2, 'kbo1', 144, rounds, split=True)
        done = U.half_tables(p)
        self.assertEqual(done['half'], 2)
        self.assertEqual({r['g'] for r in done['first']['rows']}, {72})
        self.assertEqual({r['g'] for r in done['second']['rows']}, {72})
        self.assertEqual(done['final'], '한국시리즈')
        whole = U.table(p, 2, 'kbo1', 144)
        a, b = U.half_finalists(done, whole)
        self.assertNotEqual(a['club'], b['club'])

    def test_one_club_wins_both_halves(self):
        whole = {'rows': [{'club': 'x', 'name': 'X'}, {'club': 'y', 'name': 'Y'}]}
        halves = {'first_champ': {'club': 'x'}, 'second_champ': {'club': 'x'}}
        a, b = U.half_finalists(halves, whole)
        self.assertEqual((a['club'], b['club']), ('x', 'y'))               # 시즌 승률 2위가 도전

    def test_existing_world_keeps_its_schedule(self):
        p = self.player()
        U.advance(p, 2, 'kbo1', 144, 10)
        U.advance(p, 2, 'kbo1', 144, 20, split=True)                       # 시즌 도중에 켜도 세계는 그대로
        self.assertIsNone(U.half_tables(p))


# ───────────────────────────── 반기 MVP · 가을야구(rookie_halves)
from datetime import datetime as _dt                                         # noqa: E402

from django.template.loader import render_to_string                          # noqa: E402
from django.test import TestCase                                             # noqa: E402

from . import rookie_halves as H                                             # noqa: E402
from .models import RookieAward, RookieGame, RookiePlayer, RookieSeasonStat  # noqa: E402
from .test_rookie_league import player                                       # noqa: E402

POST_ON = dict(ON, ROOKIE_FULL_POSTSEASON='true')


def _bat_games(p, s, day, n, hits):
    stat, _ = RookieSeasonStat.objects.get_or_create(
        season=s, player=p, league='kbo1',
        defaults={'user_id': p.user_id, 'name': p.name, 'team': p.club, 'role': 'batter', 'position': 'SS'})
    line = {'g': 1, 'pa': 5, 'ab': 4, 'h': hits, 'hr': hits // 2, 'bb': 1, 'so': 1, 'r': 1, 'rbi': hits}
    RookieGame.objects.bulk_create([RookieGame(season=s, player=p, league='kbo1', day=day, no=i + 1, opponent='kia',
                                               team_runs=5, opp_runs=3, line=line, summary='')
                                    for i in range(n)])
    return stat


@override_settings(**ON)
class HalfMvpTests(TestCase):
    def setUp(self):
        self.s = L.get_season(2)
        self.ace = player('반기에이스')
        self.sub = player('반기후보', team='kia')
        _bat_games(self.ace, self.s, self.s.start + timedelta(days=3), 40, 3)
        _bat_games(self.sub, self.s, self.s.start + timedelta(days=3), 40, 1)

    def test_first_half_mvp_once(self):
        self.assertEqual(H.close_half(self.s, self.s.start + timedelta(days=5)), [])       # 반기 마지막 날만
        got = H.close_half(self.s, self.s.start + timedelta(days=13))
        self.assertEqual([(a.label, a.player_id, a.kind) for a in got], [('전기리그 MVP', self.ace.pk, 'half')])
        self.assertEqual(H.close_half(self.s, self.s.start + timedelta(days=13)), [])     # 두 번 주지 않는다
        self.assertEqual(H.close_half(self.s, self.s.end), [])                             # 후기 경기가 없으면 후보도 없다

    def test_half_award_does_not_count_for_career_score(self):
        from . import rookie_career as C
        before = C.performance(self.ace, 'kbo1')
        H.close_half(self.s, self.s.start + timedelta(days=13))
        self.assertTrue(RookieAward.objects.filter(kind='half').exists())
        self.assertEqual(C.performance(self.ace, 'kbo1'), before)          # 진로 평가에 상 하나만큼 더하지 않는다

    @override_settings(ROOKIE_FULL_HALVES='false')
    def test_switch_off_gives_nothing(self):
        self.assertEqual(H.close_half(self.s, self.s.start + timedelta(days=13)), [])


@override_settings(**POST_ON)
class PostseasonTests(TestCase):
    def setUp(self):
        self.s = L.get_season(2)
        self.p = player('가을선수')

    def _mine(self):
        post = H.build_post(self.p, self.s)
        RookiePlayer.objects.filter(pk=self.p.pk).update(club=post['seeds']['first'])
        self.p.refresh_from_db()
        self.p.career = {k: v for k, v in (self.p.career or {}).items() if k != 'post'}
        return H.build_post(self.p, self.s)

    def test_final_is_played_game_by_game_on_the_off_days(self):
        post = self._mine()
        self.assertTrue(post['mine'])
        rnd = post['doc']['rounds'][0]
        self.assertEqual(rnd['name'], '한국시리즈')
        self.assertIn(len(rnd['games']), range(4, 8))
        self.assertEqual(max(rnd['wins']), 4)
        self.assertEqual(post['doc']['result'], '우승' if rnd['wins'][0] == 4 else '준우승')
        days = {_dt.fromisoformat(t).date() for t in post['at']}
        self.assertTrue(days <= {self.s.end + timedelta(days=1), self.s.end + timedelta(days=2)})
        self.assertEqual(_dt.fromisoformat(post['at'][0]).hour, 15)
        for g in rnd['games']:                                    # 이닝 점수 합 = 점수
            self.assertEqual(sum(x for x in g['us'] if x != 'X'), g['score'][0])
        self.assertEqual(H.build_post(self.p, self.s)['doc'], post['doc'])      # 같은 씨앗 — 다시 만들어도 같다

    def test_prepare_is_idempotent_and_reveals_by_time(self):
        RookiePlayer.objects.filter(pk=self.p.pk).update(club=H.build_post(self.p, self.s)['seeds']['first'])
        self.p.refresh_from_db()
        self.assertEqual(H.prepare_post(self.s), 1)
        self.assertEqual(H.prepare_post(self.s), 0)
        self.p.refresh_from_db()
        post = self.p.career['post']
        times = [_dt.fromisoformat(t) for t in post['at']]
        before = H.post_view(self.p, times[0] - timedelta(minutes=1))
        self.assertEqual((before['shown'], before['done']), (0, False))
        self.assertIn('1차전', before['line'])
        mid = H.post_view(self.p, times[1] + timedelta(minutes=1))
        self.assertEqual(mid['shown'], 2)
        self.assertEqual(mid['doc']['rounds'][0]['result'], 'pending')
        self.assertEqual(sum(mid['doc']['rounds'][0]['wins']), 2)
        self.assertEqual(mid['next']['no'], 3)
        end = H.post_view(self.p, times[-1] + timedelta(minutes=1))
        self.assertTrue(end['done'])
        self.assertIsNotNone(end['champion'])
        later = L.season_bounds(self.s.number + 2)[0]
        self.assertIsNone(H.post_view(self.p, timezone_aware(later)))          # 지난 시즌 가을야구는 접는다
        html = render_to_string('community/games/_rookie_matchday.html', {
            'md': {'post': mid, 'replays': [], 'today': [], 'slot_labels': ['11:00'], 'slots': True}, 'p': self.p})
        self.assertIn('가을야구', html)
        self.assertIn('data-sb', html)

    def test_minor_league_final_is_shorter(self):
        RookiePlayer.objects.filter(pk=self.p.pk).update(league='kbo2')
        self.p.refresh_from_db()
        post = H.build_post(self.p, self.s)
        self.assertEqual(post['final'], '우승 결정전')
        self.assertEqual(max(post['doc']['rounds'][0]['wins']), 3)

    @override_settings(ROOKIE_FULL_POSTSEASON='false')
    def test_switch_off(self):
        self.assertEqual(H.prepare_post(self.s), 0)


def timezone_aware(day):
    from django.utils import timezone
    return timezone.make_aware(_dt.combine(day, _dt.min.time().replace(hour=12)))
