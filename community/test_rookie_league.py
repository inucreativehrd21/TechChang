"""야구선수 키우기 리그 — 시즌 달력·경기 모형 보정·하루 진행·시상·기록 화면(community/rookie_league.py)."""
import random
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from common.models import Profile
from community import rookie as R
from community import rookie_league as L
from community.models import RookieAward, RookieGame, RookieLog, RookiePlayer, RookieSeasonStat

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'
D1 = L.EPOCH                                     # 시즌 1 첫날(월)


def member(name, nick=None):
    u = User.objects.create_user(username=name, password='pw12345!', email=f'{name}@example.com')
    p, _ = Profile.objects.get_or_create(user=u)
    p.nickname, p.is_email_verified = nick or name, True
    p.save()
    return u


def player(name, role='batter', team='lg', position='SS', level=60.0, tier=2):
    p = R.create(member(name), name=name[:12], role=role, team=team, position=position)
    p.stats = {k: level for k in p.stats}
    p.ovr, p.tier = level, tier
    p.save()
    return p


def active_on(p, day):
    RookieLog.objects.create(player=p, kind='earn', source='checkin', ref=str(day), tp=20, text='출석', day=day)


class CalendarTests(TestCase):
    def test_season_is_four_weeks_of_144_games(self):
        start, end = L.season_bounds(1)
        self.assertEqual((start, end), (D1, D1 + timedelta(days=27)))
        days = [start + timedelta(days=i) for i in range(28)]
        self.assertEqual(sum(len(L.games_on(d)) for d in days), 144)
        self.assertTrue(all(len(L.games_on(d)) in (5, 6) for d in days))
        self.assertEqual(L.games_through(end), 144)
        self.assertEqual(L.season_no(end + timedelta(days=1)), 2)
        self.assertEqual(L.season_no(D1 - timedelta(days=1)), 0)
        self.assertEqual(L.season_state(D1 - timedelta(days=3))['dday'], 3)
        st = L.season_state(D1 + timedelta(days=2))
        self.assertEqual((st['phase'], st['played']), ('season', L.games_through(D1 + timedelta(days=1))))

    def test_text_formats(self):
        self.assertEqual(L.rate(0.3126), '.313')
        self.assertEqual(L.rate(1.0), '1.000')
        self.assertEqual(L.ip_text(19), '6⅓')
        self.assertEqual(L.ip_text(18), '6')


class ModelCalibrationTests(TestCase):
    """같은 수준끼리면 리그 평균이 KBO 언저리에 오고, 능력치가 높을수록 성적이 좋아진다(몬테카를로, 시드 고정)."""

    def seasons(self, level, lvl=64.0, n=12, seed=3):
        rng = random.Random(seed)
        bat = {k: level for k in ('contact', 'power', 'eye', 'speed', 'defense')}
        pit = {k: level for k in ('velocity', 'control', 'breaking', 'stamina', 'mental')}
        tb, tp = {}, {}
        for _ in range(n):
            for _g in range(144):
                tb = L.add(tb, L.batter_game(bat, 'SS', lvl, rng)['line'])
            for _g in range(28):
                tp = L.add(tp, L.pitcher_game(pit, lvl, rng)['line'])
        return tb, tp

    def test_league_average(self):
        tb, tp = self.seasons(64.0)
        b, p = L.batting(tb), L.pitching(tp)
        self.assertTrue(.245 <= b['avg'] <= .290, b['avg'])
        self.assertTrue(.70 <= b['ops'] <= .82, b['ops'])
        self.assertLess(abs(b['woba'] - L.LG_WOBA), 0.02)
        self.assertTrue(3.3 <= p['era'] <= 4.6, p['era'])
        self.assertLess(abs(p['fip'] - p['era']), 0.45)              # FIP 상수가 리그 평균자책점에 맞는다
        self.assertTrue(5.3 <= p['ip'] / tp['gs'] <= 7.0)            # 선발 평균 이닝
        per = tb['pa'] / 12
        self.assertTrue(560 <= per <= 700, per)                       # 시즌 타석 ≈ KBO 주전
        self.assertTrue(1.0 <= L.war('batter', 'SS', {k: v / 12 for k, v in tb.items()}) <= 4.5)

    def test_better_players_do_better(self):
        lo_b, lo_p = self.seasons(58.0, n=6)
        hi_b, hi_p = self.seasons(82.0, n=6)
        self.assertGreater(L.batting(hi_b)['ops'], L.batting(lo_b)['ops'] + .12)
        self.assertLess(L.pitching(hi_p)['era'], L.pitching(lo_p)['era'] - 1.0)
        self.assertGreater(L.war('batter', 'SS', hi_b), L.war('batter', 'SS', lo_b))


class SimulateDayTests(TestCase):
    def setUp(self):
        cache.clear()
        self.bat = player('타자일', 'batter', 'lg', 'SS')
        self.pit = player('투수일', 'pitcher', 'kia', 'SP')
        self.lazy = player('쉬는선수', 'batter', 'nc', 'OF')
        for p in (self.bat, self.pit):
            active_on(p, D1)
        RookieLog.objects.filter(player=self.lazy).update(day=D1 - timedelta(days=10))    # 입단 기록도 오래전

    def test_only_active_players_play_and_stats_add_up(self):
        n = L.simulate_day(D1, rng=random.Random(5))
        self.assertEqual(n, 2)
        self.assertEqual(RookieGame.objects.filter(player=self.bat).count(), len(L.games_on(D1)))   # 타자는 그날 전 경기
        self.assertEqual(RookieGame.objects.filter(player=self.pit).count(), 1)                    # 투수는 한 경기 선발
        self.assertFalse(RookieGame.objects.filter(player=self.lazy).exists())                     # 쉰 선수는 결장
        st = RookieSeasonStat.objects.get(player=self.bat, league=2)
        self.assertEqual(st.totals['pa'], sum(g.line['pa'] for g in RookieGame.objects.filter(player=self.bat)))
        self.assertEqual(st.totals['g'], len(L.games_on(D1)))
        self.assertNotIn('vs', st.totals)                                                        # 상대 등급은 경기 줄에만
        self.assertEqual(sum(st.totals.get(f'{c}_pa', 0) for c in ('ace', 'reg', 'bak', 'pen')), st.totals['pa'])
        self.assertEqual(L.simulate_day(D1), 0)                                                  # 같은 날 두 번 치르지 않는다
        g = RookieGame.objects.filter(player=self.bat).first()
        self.assertNotEqual(g.opponent, 'lg')
        self.assertTrue(g.summary.startswith(f"{g.line['ab']}타수"))

    def test_activity_window_is_three_days(self):
        active_on(self.lazy, D1 - timedelta(days=2))
        L.simulate_day(D1, rng=random.Random(1))
        self.assertTrue(RookieGame.objects.filter(player=self.lazy).exists())

    def test_advance_catches_up_and_preseason_is_noop(self):
        self.assertEqual(L.advance(D1), 0)                    # 개막 당일 아침엔 치를 경기가 없다
        self.assertEqual(L.advance(D1 + timedelta(days=3)), 3)
        self.assertEqual(L.advance(D1 + timedelta(days=3)), 0)
        self.assertEqual(L.get_season(1).simulated_through, D1 + timedelta(days=2))

    def test_board_shows_latest_games_and_dnp(self):
        L.simulate_day(D1, rng=random.Random(2))
        L.simulate_day(D1 + timedelta(days=1), rng=random.Random(2))   # 둘째 날은 아무도 활동 안 했지만 3일 창 안
        with mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=5)):
            L.simulate_day(D1 + timedelta(days=4), rng=random.Random(2))
            b = L.player_board(self.bat, D1 + timedelta(days=5))
        self.assertEqual(b['games_day'], D1 + timedelta(days=1))
        self.assertTrue(b['dnp'])                                          # 넷째 날은 결장
        self.assertEqual(b['main_line']['s'].league, 2)


class CloseSeasonTests(TestCase):
    def stat(self, p, league=2, **totals):
        return RookieSeasonStat.objects.create(season=self.season, user=p.user, player=p, league=league, name=p.name,
                                               number=p.number, team=p.team, role=p.role, position=p.position,
                                               totals=totals, war=L.war(p.role, p.position, totals))

    def setUp(self):
        cache.clear()
        self.season = L.get_season(1)
        big = dict(g=140, pa=620, ab=540, h=180, d=35, t=3, hr=38, rbi=120, r=110, bb=70, hbp=5, so=90, sb=12, cs=3)
        ok = dict(g=140, pa=600, ab=540, h=150, d=28, t=2, hr=15, rbi=70, r=80, bb=50, hbp=4, so=110, sb=30, cs=5)
        self.star = player('강타자', 'batter', 'lg', 'SS')
        self.ss2 = player('둘째유격', 'batter', 'kia', 'SS')
        self.of = player('외야수', 'batter', 'ssg', 'OF')
        self.ace = player('에이스', 'pitcher', 'doosan', 'SP')
        self.fut = player('퓨처스', 'batter', 'nc', '2B', tier=1)
        self.boss = player('admin', 'batter', 'kt', 'SS')
        self.stat(self.star, **big)
        self.stat(self.ss2, **ok)
        self.stat(self.of, **ok)
        self.stat(self.ace, g=28, gs=28, w=18, l=4, qs=22, outs=600, h=150, r=55, er=50, bb=40, hbp=3, so=210, hr=12, bf=800)
        self.stat(self.fut, league=1, **ok)
        self.stat(self.boss, **dict(big, hr=60))                       # 운영자 — 시상에서 빠진다

    def test_awards(self):
        awards = L.close_season(self.season)
        got = {a.label: a.name for a in awards}
        self.assertEqual(got['MVP'], max(['강타자', '에이스'], key=lambda n: RookieSeasonStat.objects.get(name=n).war))
        self.assertEqual(got['골든글러브 유격수'], '강타자')
        self.assertEqual(got['골든글러브 외야수'], '외야수')
        self.assertEqual(got['골든글러브 투수'], '에이스')
        self.assertEqual(got['홈런왕'], '강타자')                         # admin(60홈런)은 후보가 아니다
        self.assertEqual(got['도루왕'], '둘째유격')
        self.assertEqual(got['다승왕'], '에이스')
        self.assertEqual(got['퓨처스 MVP'], '퓨처스')
        self.assertIn('신인왕', got)
        self.assertNotIn('admin', got.values())
        self.season.refresh_from_db()
        self.assertTrue(self.season.closed)
        self.assertEqual(L.close_season(self.season), [])               # 두 번 시상하지 않는다
        self.assertTrue(RookieLog.objects.filter(player=self.star, kind='award').exists())

    def test_records_and_career_highs(self):
        L.close_season(self.season)
        highs = L.career_highs('batter')
        self.assertEqual(highs[0]['s'].name, '강타자')
        self.assertNotIn('admin', [h['s'].name for h in highs])
        recs = {r['label']: r for r in L.season_records()}
        self.assertEqual(recs['시즌 최다 홈런']['value'], 38)
        self.assertEqual(recs['시즌 최다승']['s'].name, '에이스')

    def test_screens(self):
        L.close_season(self.season)
        c = self.client
        later = mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=29))
        later.start()
        self.addCleanup(later.stop)
        for ua in (PC, MOBILE):
            r = c.get('/rookie/awards/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '골든글러브')
            self.assertContains(r, '강타자')
            self.assertContains(r, 'rk-diamond')
            self.assertNotContains(r, '>admin<')
            r = c.get('/rookie/records/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '커리어하이')
            self.assertContains(r, '강타자')
            self.assertContains(c.get('/rookie/records/?role=pitcher', HTTP_USER_AGENT=ua), '에이스')
        r = c.get(f'/rookie/p/{self.star.pk}/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '통산 기록')
        self.assertContains(r, '골든글러브 유격수')
        self.assertEqual(c.get(f'/rookie/p/{self.boss.pk}/').status_code, 404)    # 운영자 선수 페이지는 남에게 없다


class ScreenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_preseason_home_shows_dday(self):
        p = player('개막대기', tier=0)
        self.client.force_login(p.user)
        with mock.patch('django.utils.timezone.localdate', return_value=D1 - timedelta(days=3)):
            r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '개막 D-3')
        self.assertContains(r, 'rk-board')

    def test_in_season_home_league_and_player(self):
        bat = player('리그타자', 'batter', 'lg', 'SS')
        pit = player('리그투수', 'pitcher', 'kia', 'SP')
        for d in range(3):
            for p in (bat, pit):
                active_on(p, D1 + timedelta(days=d))
            L.simulate_day(D1 + timedelta(days=d), rng=random.Random(d))
        self.client.force_login(bat.user)
        with mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=3)):
            for ua in (PC, MOBILE):
                r = self.client.get('/rookie/', HTTP_USER_AGENT=ua)
                self.assertContains(r, 'rk-board-rows')
                self.assertContains(r, '시즌 1 1군 기록')
                self.assertContains(r, '규정타석')
                r = self.client.get('/rookie/league/', HTTP_USER_AGENT=ua)
                self.assertContains(r, '홈런')
                self.assertContains(r, '평균자책점')
                self.assertContains(r, '리그투수')
                r = self.client.get('/rookie/awards/', HTTP_USER_AGENT=ua)
                self.assertContains(r, 'MVP 레이스')
            r = self.client.get(f'/rookie/p/{pit.pk}/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '평균자책점')
            self.assertContains(r, '탈삼진')
            r = self.client.get('/rookie/records/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '진행 중')

    def test_batter_position_saved(self):
        u = member('위치선택')
        self.client.force_login(u)
        self.client.post('/rookie/create/', {'role': 'batter', 'team': 'lg', 'name': '포수', 'position': 'C',
                                             'focus_batter': 'eye'})
        self.assertEqual(RookiePlayer.objects.get(user=u).position, 'C')
        u2 = member('투수선택')
        self.client.force_login(u2)
        self.client.post('/rookie/create/', {'role': 'pitcher', 'team': 'lg', 'name': '투수', 'position': 'C'})
        self.assertEqual(RookiePlayer.objects.get(user=u2).position, 'SP')

    def test_retired_players_records_survive(self):
        p = player('은퇴선수')
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(9))
        R.retire(p.user)
        st = RookieSeasonStat.objects.get(name='은퇴선수')
        self.assertIsNone(st.player)
        self.assertFalse(RookieAward.objects.exists())


class OpponentGradeTests(TestCase):
    """상대가 에이스·주전·백업 중 누구였는지 경기마다 남고, 등급이 높을수록 실제로 더 어렵다."""

    def test_batter_game_records_starter_grade_and_splits(self):
        rng = random.Random(11)
        s = {k: 64.0 for k in ('contact', 'power', 'eye', 'speed', 'defense')}
        seen = set()
        for _ in range(200):
            r = L.batter_game(s, 'SS', 64.0, rng)
            line = r['line']
            seen.add(line['vs'])
            self.assertEqual(sum(line.get(f'{c}_pa', 0) for c in ('ace', 'reg', 'bak', 'pen')), line['pa'])
            self.assertLessEqual(line.get(f"{line['vs']}_pa", 0), L.STARTER_PA[line['vs']])
            self.assertAlmostEqual(line['vs_lvl'], 64 + L.OPP_OFFSET[line['vs']], delta=8)
        self.assertEqual(seen, {'ace', 'reg', 'bak'})

    def test_pitcher_game_faces_lineup_by_slot(self):
        rng = random.Random(12)
        s = {k: 64.0 for k in ('velocity', 'control', 'breaking', 'stamina', 'mental')}
        forms = set()
        for _ in range(100):
            line = L.pitcher_game(s, 64.0, rng)['line']
            forms.add(line['vs'])
            self.assertEqual(sum(line.get(f'{c}_pa', 0) for c in ('ace', 'reg', 'bak')), line['bf'])
            self.assertEqual(line.get('reg_pa', 0) >= line.get('bak_pa', 0) - 3, True)
        self.assertEqual(forms, {'strong', 'normal', 'weak'})
        self.assertNotIn('vs', L.add({}, line))

    def test_aces_are_harder_than_backups(self):
        rng = random.Random(13)
        bat = {k: 64.0 for k in ('contact', 'power', 'eye', 'speed', 'defense')}
        pit = {k: 64.0 for k in ('velocity', 'control', 'breaking', 'stamina', 'mental')}
        tb, tp = {}, {}
        for _ in range(12 * 144):                                       # 백업 선발 타석이 적어(25%×2타석) 표본을 넉넉히
            tb = L.add(tb, L.batter_game(bat, 'SS', 64.0, rng)['line'])
        for _ in range(10 * 28):
            tp = L.add(tp, L.pitcher_game(pit, 64.0, rng)['line'])
        b = {x['code']: x for x in L.splits('batter', tb, 2)}
        p = {x['code']: x for x in L.splits('pitcher', tp, 2)}
        avg = lambda x: x['h'] / x['ab']  # noqa: E731
        self.assertLess(avg(b['ace']) + .03, avg(b['reg']))
        self.assertLess(avg(b['reg']) + .015, avg(b['bak']))
        self.assertGreater(avg(p['ace']), avg(p['reg']) + .015)         # 투수에겐 중심타자가 가장 잘 친다
        self.assertGreater(avg(p['ace']), avg(p['bak']) + .035)         # (투수 모형은 타자보다 민감도가 낮다)
        self.assertEqual((b['ace']['level'], b['reg']['level'], b['bak']['level']), (76, 64, 54))

    def test_screens_show_grades(self):
        bat = player('등급타자', 'batter', 'lg', 'SS')
        pit = player('등급투수', 'pitcher', 'kia', 'SP')
        for p in (bat, pit):
            active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(4))
        with mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=1)):
            self.client.force_login(bat.user)
            r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '선발, 상대 능력')                   # 전광판 칩(주전 64) — 풀이는 title 에
            self.assertContains(r, 'class="rk-vs is-')
            self.assertContains(r, '상대 등급별 성적')
            self.assertContains(r, '1군 상대 능력: 에이스 76, 주전 64, 백업 54')
            self.client.force_login(pit.user)
            r = self.client.get('/rookie/', HTTP_USER_AGENT=MOBILE)
            self.assertContains(r, '중심타자')
            self.assertContains(r, 'rk-box-split')
            r = self.client.get(f'/rookie/p/{bat.pk}/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '에이스 선발')
