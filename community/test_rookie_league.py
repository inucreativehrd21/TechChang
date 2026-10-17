"""야구선수 키우기 리그 — 시즌 달력·경기 모형 보정·하루 진행·시상·기록 화면(community/rookie_league.py)."""
import random
from collections import Counter
from datetime import date, datetime, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from common.models import Profile
from community import rookie as R
from community import rookie_league as L
from community import rookie_sim as M
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


def player(name, role='batter', team='lg', position='SS', level=60.0, league='kbo1'):
    """프로 성인 선수(기본 KBO 1군) — 나이 한계·잠재력·특성이 경기 보정을 흔들지 않게."""
    p = R.create(member(name), name=name[:12], role=role, team=team, position=position, region='서울')
    p.stats = {k: level for k in p.stats}
    p.ovr, p.league, p.club = level, league, team
    p.age, p.potential, p.traits, p.grade, p.grade_since, p.pending = 25, 99, [], 0, None, {}
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
        self.assertEqual(L.season_no(end + timedelta(days=1)), 1)              # 시즌 사이 쉬는 날
        self.assertFalse(L.in_season(end + timedelta(days=1)))
        self.assertEqual(L.season_bounds(2)[0], end + timedelta(days=L.OFF_DAYS + 1))
        self.assertEqual(L.season_no(L.season_bounds(2)[0]), 2)
        off = L.season_state(end + timedelta(days=1))
        self.assertEqual((off['phase'], off['next'], off['dday']), ('off', 2, L.OFF_DAYS))
        self.assertEqual(list(L.games_on(end + timedelta(days=1))), [])
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
        self.pit = player('투수일', 'pitcher', 'kia', 'SP', level=70)        # 선발형 → 하루 한 경기 선발
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
        st = RookieSeasonStat.objects.get(player=self.bat, league='kbo1')
        self.assertEqual(st.totals['pa'], sum(g.line['pa'] for g in RookieGame.objects.filter(player=self.bat)))
        self.assertEqual(st.totals['g'], len(L.games_on(D1)))
        self.assertNotIn('vs', st.totals)                                                        # 상대 등급은 경기 줄에만
        self.assertEqual(sum(st.totals.get(f'{c}_pa', 0) for c, _l in M.BAT_SPLITS), st.totals['pa'])
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
        self.assertEqual(b['main_line']['s'].league, 'kbo1')


class CloseSeasonTests(TestCase):
    def stat(self, p, league='kbo1', **totals):
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
        self.fut = player('퓨처스', 'batter', 'nc', '2B', league='kbo2')
        self.boss = player('admin', 'batter', 'kt', 'SS')
        self.stat(self.star, **big)
        self.stat(self.ss2, **ok)
        self.stat(self.of, **ok)
        self.stat(self.ace, g=28, gs=28, w=18, l=4, qs=22, outs=600, h=150, r=55, er=50, bb=40, hbp=3, so=210, hr=12, bf=800)
        self.stat(self.fut, league='kbo2', **ok)
        self.stat(self.boss, **dict(big, hr=60))                       # 운영자 — 시상에서 빠진다

    def test_awards(self):
        awards = L.close_season(self.season)
        got = {a.label: a.name for a in awards}
        self.assertEqual(got['MVP'], max(['강타자', '에이스'], key=lambda n: RookieSeasonStat.objects.get(name=n).war))
        self.assertEqual(got['골든글러브 유격수'], '강타자')
        self.assertEqual(got['골든글러브 외야수'], '외야수')
        self.assertEqual(got['골든글러브 투수'], '에이스')
        self.assertEqual(got['홈런왕'], '강타자')                         # admin(60홈런)은 후보가 아니다
        self.assertEqual(sorted(a.name for a in awards if a.label == '도루왕'), ['둘째유격', '외야수'])   # 동률 → 공동 수상
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
        self.assertContains(r, '통산 성적')
        self.assertContains(r, '골든글러브 유격수')
        self.assertEqual(c.get(f'/rookie/p/{self.boss.pk}/').status_code, 404)    # 운영자 선수 페이지는 남에게 없다


class ScreenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_preseason_home_shows_dday(self):
        p = player('개막대기', league='kbo3')
        self.client.force_login(p.user)
        with mock.patch('django.utils.timezone.localdate', return_value=D1 - timedelta(days=3)):
            r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '개막 D-3')
        self.assertContains(r, 'rk-board')

    def test_in_season_home_league_and_player(self):
        bat = player('리그타자', 'batter', 'lg', 'SS')
        pit = player('리그투수', 'pitcher', 'kia', 'SP', level=70)
        for d in range(3):
            for p in (bat, pit):
                active_on(p, D1 + timedelta(days=d))
            L.simulate_day(D1 + timedelta(days=d), rng=random.Random(d))
        self.client.force_login(bat.user)
        with mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=3)):
            for ua in (PC, MOBILE):
                r = self.client.get('/rookie/', HTTP_USER_AGENT=ua)
                self.assertContains(r, 'rk-board-rows')
                self.assertContains(r, '시즌 1 KBO 1군 기록')
                self.assertContains(r, '규정타석')
                r = self.client.get('/rookie/league/?lg=kbo1', HTTP_USER_AGENT=ua)
                self.assertContains(r, '홈런')
                self.assertContains(r, '평균자책점')
                self.assertContains(r, '리그투수')
                r = self.client.get('/rookie/awards/', HTTP_USER_AGENT=ua)
                self.assertContains(r, 'MVP 레이스')
            r = self.client.get(f'/rookie/p/{pit.pk}/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '평균자책점')
            self.assertContains(r, '탈삼진')
            r = self.client.get('/rookie/records/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '아직 KBO리그 시즌 기록이 없습니다')   # 진행 중 시즌 초반은 기록실에 오르지 않는다

    def test_batter_position_saved(self):
        u = member('위치선택')
        self.client.force_login(u)
        self.client.post('/rookie/create/', {'role': 'batter', 'team': 'lg', 'name': '포수', 'position': 'C',
                                             'focus_batter': 'eye', 'region': '서울'})
        self.assertEqual(RookiePlayer.objects.get(user=u).position, 'C')
        u2 = member('투수선택')
        self.client.force_login(u2)
        self.client.post('/rookie/create/', {'role': 'pitcher', 'team': 'lg', 'name': '투수', 'position': 'C',
                                             'region': '서울'})
        self.assertEqual(RookiePlayer.objects.get(user=u2).position, 'SP')

    def test_retired_players_records_survive(self):
        p = player('은퇴선수')
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(9))
        R.retire(p.user)
        st = RookieSeasonStat.objects.get(name='은퇴선수')
        self.assertEqual(st.player_id, p.pk)                       # 은퇴해도 선수와 기록이 이어져 있다
        p.refresh_from_db()
        self.assertIsNotNone(p.retired_at)
        self.assertFalse(RookieAward.objects.exists())
        R.create(p.user, name='새출발', role='batter', team='lg', region='서울')     # 다시 시작할 수 있다
        L.simulate_day(D1 + timedelta(days=1), rng=random.Random(9))
        self.assertFalse(RookieGame.objects.filter(player=p, day=D1 + timedelta(days=1)).exists())


class OpponentGradeTests(TestCase):
    """상대가 누구였는지 경기마다 남고, 에이스와 백업의 차이가 크다(민감도 S=9)."""

    def test_batter_game_records_starter_grade_and_splits(self):
        rng = random.Random(11)
        s = {k: 64.0 for k in M.BAT}
        seen = set()
        for _ in range(200):
            line = L.batter_game(s, 'SS', 64.0, rng)['line']
            seen.add(line['vs'])
            self.assertEqual(sum(line.get(f'{c}_pa', 0) for c, _l in M.BAT_SPLITS), line['pa'])
            self.assertLessEqual(line.get(f"{line['vs']}_pa", 0), M.STARTER_PA[line['vs']])
        self.assertEqual(seen, {'ace', 'reg', 'bak'})

    def test_pitcher_faces_top_heart_bottom_of_order(self):
        rng = random.Random(12)
        s = {k: 64.0 for k in M.PIT}
        forms = set()
        for _ in range(100):
            line = L.pitcher_game(s, 64.0, rng)['line']
            forms.add(line['vs'])
            self.assertEqual(sum(line.get(f'{c}_pa', 0) for c in ('top', 'heart', 'bottom')), line['bf'])
        self.assertEqual(forms, {'strong', 'normal', 'weak'})
        self.assertNotIn('vs', L.add({}, line))
        # 상위타선은 출루·주루, 중심타선은 클러치에 컨택·파워, 하위타선은 밋밋
        top, heart, bottom = M.opp_batter(1, 64), M.opp_batter(4, 64), M.opp_batter(8, 64)
        self.assertGreater(min(top['eye'], top['speed']), max(top['power'], 64))
        self.assertGreater(heart['clutch'], 64 + 8)
        self.assertGreaterEqual(sum(M.opp_batter(3, 64)[k] > 64 + 4 for k in ('contact', 'power')), 2)
        self.assertLess(max(bottom[k] for k in ('contact', 'power', 'eye', 'clutch')), 64)

    def test_ace_and_backup_are_far_apart(self):
        avg_b = {k: 64.0 for k in M.BAT}
        avg_p = {k: 64.0 for k in M.PIT}

        def avg(pr):
            return (pr['1B'] + pr['2B'] + pr['3B'] + pr['HR']) / (1 - pr['BB'] - pr['HBP'])
        vs = {k: avg(M.pa_probs(avg_b, M.opp_pitcher(k, 64.0))) for k in ('ace', 'reg', 'bak')}
        self.assertLess(vs['ace'], .215)
        self.assertTrue(.255 <= vs['reg'] <= .28)
        self.assertGreater(vs['bak'], .315)
        # 내 투수도 같은 승부 — 에이스급 타자(+12)와 백업 타자(−10) 사이가 크다
        ace_bat = {k: 76.0 for k in M.BAT}
        bak_bat = {k: 54.0 for k in M.BAT}
        self.assertGreater(avg(M.pa_probs(ace_bat, avg_p)) - avg(M.pa_probs(bak_bat, avg_p)), .12)

    def test_seasons_split_by_opponent(self):
        rng = random.Random(13)
        bat = {k: 64.0 for k in M.BAT}
        pit = {k: 64.0 for k in M.PIT}
        tb, tp = {}, {}
        for _ in range(6 * 144):
            tb = L.add(tb, L.batter_game(bat, 'SS', 64.0, rng)['line'])
        for _ in range(8 * 28):
            tp = L.add(tp, L.pitcher_game(pit, 64.0, rng)['line'])
        b = {x['code']: x for x in L.splits('batter', tb, 'kbo1')}
        p = {x['code']: x for x in L.splits('pitcher', tp, 'kbo1')}
        avg = lambda x: x['h'] / x['ab']  # noqa: E731
        self.assertLess(avg(b['ace']) + .04, avg(b['reg']))
        self.assertLess(avg(b['reg']) + .02, avg(b['bak']))             # 백업 선발은 25%×2타석 — 표본이 작다
        self.assertLess(avg(b['setup']) + .06, avg(b['mop']))
        self.assertGreater(avg(p['heart']), avg(p['bottom']) + .04)
        self.assertGreater(p['top']['bb'] / p['top']['pa'], p['bottom']['bb'] / p['bottom']['pa'])
        self.assertEqual((b['ace']['level'], b['reg']['level'], b['bak']['level']), (75, 64, 54))

    def test_screens_show_grades(self):
        bat = player('등급타자', 'batter', 'lg', 'SS', level=66)
        pit = player('등급투수', 'pitcher', 'kia', 'SP', level=70)
        for p in (bat, pit):
            active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(4))
        with mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=1)):
            self.client.force_login(bat.user)
            r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '선발, 상대 능력')
            self.assertContains(r, '상대 등급별 성적')
            self.assertContains(r, '1군 상대 선발 구위: 에이스 75, 주전 64, 백업 54')
            self.assertContains(r, '하위타선 주전')
            self.client.force_login(pit.user)
            r = self.client.get('/rookie/', HTTP_USER_AGENT=MOBILE)
            self.assertContains(r, '중심타선')
            self.assertContains(r, 'rk-box-split')
            self.assertContains(r, 'km/h · 직구')
            r = self.client.get(f'/rookie/p/{bat.pk}/', HTTP_USER_AGENT=PC)
            self.assertContains(r, '선발')


class LineupRoleTests(TestCase):
    """내 타순·보직은 한 계단씩 — 능력이나 최근 성적으로 증명하면 오르고, 무너지면 내려간다."""

    def bat(self, **over):
        return dict({k: 60.0 for k in M.BAT}, **over)

    def hot(self, games=4):
        return [{'pa': 4, 'ab': 4, 'h': 2, 'hr': 1} for _ in range(games)]

    def test_batter_climbs_from_bench(self):
        lvl = 64.0
        self.assertEqual(M.batter_role('', self.bat(), 55, lvl, [])[0], 'bench')
        role, slot, why = M.batter_role('bench', self.bat(), 55, lvl, self.hot())
        self.assertEqual((role, slot), ('lower', 9))
        self.assertIn('증명', why)
        self.assertEqual(M.batter_role('bench', self.bat(), 61, lvl, [])[0], 'lower')
        self.assertEqual(M.batter_role('lower', self.bat(eye=70, speed=75), 68, lvl, [])[:2], ('table', 1))
        self.assertEqual(M.batter_role('lower', self.bat(power=78), 68, lvl, [])[:2], ('slugger', 4))
        self.assertEqual(M.batter_role('lower', {k: 75.0 for k in M.BAT}, 75, lvl, [])[:2], ('five', 3))
        self.assertEqual(M.batter_role('lower', self.bat(contact=72), 68, lvl, [])[:2], ('contact', 3))
        slump = [{'pa': 4, 'ab': 4, 'h': 0} for _ in range(10)]
        self.assertEqual(M.batter_role('slugger', self.bat(power=78), 68, lvl, slump)[0], 'lower')
        self.assertEqual(M.batter_role('lower', self.bat(), 50, lvl, [])[0], 'bench')

    def test_bench_appears_as_pinch(self):
        rng = random.Random(3)
        kinds = Counter()
        for _ in range(300):
            r = M.batter_game(self.bat(), 'SS', 64.0, rng, role='bench', slot=0)
            if r is None:
                kinds['none'] += 1
                continue
            line = r['line']
            kinds['ph' if line.get('ph') else 'pr' if line.get('pr') else 'dr'] += 1
            self.assertLessEqual(line.get('pa', 0), 1)
        self.assertTrue(all(kinds[k] > 20 for k in ('ph', 'pr', 'dr', 'none')), kinds)

    def test_pitcher_climbs_bullpen_one_step_at_a_time(self):
        lvl = 64.0
        arm = {'velocity': 76, 'control': 72, 'breaking': 76, 'stamina': 40, 'mental': 74}
        cur, path = '', []
        for _ in range(6):
            cur = M.pitcher_role(cur, arm, lvl, [])[0]
            path.append(cur)
        self.assertEqual(path[:5], ['chase', 'win', 'setup', 'closer', 'closer'])
        soft = dict(arm, mental=58)
        self.assertEqual(M.pitcher_role('win', soft, lvl, [])[0], 'win')
        bad = [{'outs': 9, 'er': 8} for _ in range(2)]
        self.assertEqual(M.pitcher_role('setup', arm, lvl, bad)[0], 'win')
        good = [{'outs': 9, 'er': 0} for _ in range(2)]
        weaker = {'velocity': 67, 'control': 64, 'breaking': 67, 'stamina': 40, 'mental': 66}   # 구위 66.3 — 필승조 기준 68 미달
        self.assertEqual(M.pitcher_role('win', weaker, lvl, [])[0], 'win')
        self.assertEqual(M.pitcher_role('win', weaker, lvl, good)[0], 'setup')

    def test_starter_type_goes_to_rotation(self):
        lvl = 64.0
        horse = {'velocity': 70, 'control': 70, 'breaking': 70, 'stamina': 72, 'mental': 66}
        role, slot, why = M.pitcher_role('mop', horse, lvl, [])
        self.assertEqual(role, 'sp')
        self.assertIn('선발', why)
        self.assertEqual(M.rotation_rank(horse, lvl), 2)
        self.assertEqual(M.pitcher_role('sp', dict(horse, stamina=50), lvl, [])[0], 'mop')
        prof = M.pitch_profile(horse)
        self.assertEqual(prof['style'], '이닝이터')
        self.assertIn('체인지업', prof['pitches'])

    def test_relievers_earn_saves_and_holds(self):
        rng = random.Random(5)
        arm = {k: 72.0 for k in M.PIT}
        tot = {}
        for role in ('closer', 'setup', 'chase'):
            t = {}
            for _ in range(80):
                t = L.add(t, M.relief_game(arm, 64.0, rng, role)['line'])
            tot[role] = t
        self.assertGreater(tot['closer'].get('sv', 0), 50)
        self.assertGreater(tot['setup'].get('hld', 0), 45)
        self.assertGreater(tot['chase'].get('w', 0), 3)

    def test_daily_assignment_logs_promotion(self):
        p = player('계단타자', 'batter', 'lg', 'SS', level=60)
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(1))
        p.refresh_from_db()
        self.assertEqual((p.lineup, p.slot), ('lower', 8))          # OVR 60 = 리그 수준 −4 → 8번
        p.stats = dict(p.stats, contact=65.0, power=63.0, eye=74.0, speed=76.0, defense=65.0)
        p.ovr = R.overall('batter', p.stats)                     # ≈ 68 — 경기 경험이 OVR 을 능력치로 다시 셈한다
        p.save()
        active_on(p, D1 + timedelta(days=1))
        L.simulate_day(D1 + timedelta(days=1), rng=random.Random(2))
        p.refresh_from_db()
        self.assertEqual(p.lineup, 'lower')                                   # 새 자리에서 최소 이틀
        active_on(p, D1 + timedelta(days=2))
        L.simulate_day(D1 + timedelta(days=2), rng=random.Random(3))
        p.refresh_from_db()
        self.assertEqual((p.lineup, p.slot), ('table', 1))
        self.assertTrue(RookieLog.objects.filter(player=p, kind='role', text__contains='테이블세터').exists())
        self.assertTrue(any(g.line.get('bslot') == 1 for g in RookieGame.objects.filter(player=p, day=D1 + timedelta(days=2))))



class StageOneFixTests(TestCase):
    """개막 전 1단계 수정(2026-10-17 감사) — 날짜 경계, 오류 격리, 시상 재시도, 기록 표본, 탈퇴, 보직 대기."""

    def setUp(self):
        cache.clear()

    def test_morning_signup_plays_and_is_not_dnp(self):
        from django.utils import timezone as tz
        p = player('오전입단', level=60)
        RookiePlayer.objects.filter(pk=p.pk).update(
            created_at=tz.make_aware(datetime(D1.year, D1.month, D1.day, 8, 30)))         # KST 오전 = UTC 전날
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(1))
        self.assertTrue(RookieGame.objects.filter(player=p, day=D1).exists())
        p.refresh_from_db()
        self.assertFalse(L.player_board(p, D1 + timedelta(days=1))['dnp'])

    def test_idle_reliever_day_is_not_dnp(self):
        p = player('불펜대기', 'pitcher', level=60)
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(1))
        RookieGame.objects.filter(player=p).delete()                        # 그날 등판이 없었던 경우
        self.assertFalse(L.player_board(p, D1 + timedelta(days=1))['dnp'])

    def test_one_failing_player_does_not_block_others(self):
        ok, bad = player('정상선수', level=60), player('오류선수', level=60)
        for p in (ok, bad):
            active_on(p, D1)
        real = L._play

        def flaky(p, *a, **kw):
            if p.pk == bad.pk:
                raise RuntimeError('boom')
            return real(p, *a, **kw)
        with mock.patch('community.rookie_league._play', side_effect=flaky):
            self.assertEqual(L.simulate_day(D1, rng=random.Random(1)), 1)
        self.assertTrue(RookieGame.objects.filter(player=ok).exists())
        self.assertFalse(RookieGame.objects.filter(player=bad).exists())
        self.assertEqual(L.get_season(1).simulated_through, D1)

    def test_failed_ceremony_is_retried(self):
        s = L.get_season(1)
        s.simulated_through = s.end - timedelta(days=1)
        s.save()
        with mock.patch('community.rookie_league.close_season', side_effect=RuntimeError('db')):
            L.simulate_day(s.end, rng=random.Random(1))
        s.refresh_from_db()
        self.assertFalse(s.closed)
        L.advance(s.end + timedelta(days=1))                                # 다음 날 밤 cron
        s.refresh_from_db()
        self.assertTrue(s.closed)

    def test_records_wait_for_finished_seasons(self):
        p = player('첫날타자', level=80)
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(2))
        self.assertTrue(all(r['s'] is None for r in L.season_records()))   # 진행 중 시즌 첫날 표본은 기록이 아니다
        self.assertEqual(L.career_highs('batter'), [])

    def test_withdraw_removes_rookie_records(self):
        from common.services.account import withdraw
        p = player('탈퇴예정', level=60)
        active_on(p, D1)
        L.simulate_day(D1, rng=random.Random(1))
        withdraw(p.user)
        self.assertFalse(RookiePlayer.objects.filter(pk=p.pk).exists())
        self.assertFalse(RookieSeasonStat.objects.filter(name='탈퇴예정').exists())

    def test_promotion_starts_on_bench_again(self):
        from community.models import RookiePlayer as RP
        p = player('승격타자', league='kbo2', level=50)
        p.stats = {k: 66.0 for k in p.stats}
        p.ovr, p.lineup, p.slot = 66.0, 'table', 1
        p.save()

        class Always:
            def gauss(self, mu, sigma):
                return 10.0

            def choice(self, seq):
                return seq[0]
        R.promotion_test(p.user, rng=Always())
        p = RP.objects.get(pk=p.pk)
        self.assertEqual((p.league, p.lineup, p.slot), ('kbo1', 'bench', 0))
        self.assertTrue(p.logs.filter(kind='promote', text__contains='백업부터').exists())

    def test_daily_upkeep_is_not_logged_as_decay(self):
        p = player('성실선수', level=60)
        p.last_active = D1
        p.settled_through = D1 - timedelta(days=1)
        p.save()
        R.settle(p, D1 + timedelta(days=1))                                # 활동한 다음 날 — 유지비만
        self.assertFalse(p.logs.filter(kind='decay').exists())
        R.settle(p, D1 + timedelta(days=5))                                # 사흘 넘게 쉼
        self.assertTrue(p.logs.filter(kind='decay').exists())

    def test_reliever_score_matches_shown_deficit(self):
        rng = random.Random(9)
        arm = {k: 60.0 for k in M.PIT}
        gap, expect = [], []
        for _ in range(400):
            r = M.relief_game(arm, 64.0, rng, 'mop')
            lead = r['line']['lead']
            self.assertLess(lead, 0)
            self.assertGreaterEqual(r['team_runs'], 0)
            gap.append(r['opp_runs'] - r['team_runs'])
            expect.append(-lead + r['line'].get('r', 0))
        # 최종 점수 차 평균이 '들어갈 때 점수 차 + 내 실점'과 맞는다(예전엔 0점 아래를 잘라 2~3점 작았다)
        self.assertLess(abs(sum(gap) / len(gap) - sum(expect) / len(expect)), 0.5)
