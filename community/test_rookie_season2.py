"""시즌 2(2026-11-18) 준비 회귀 — 기록실 새 화면(라이트 명예의 전당과 같은 거르기)과 시즌 1 → 시즌 2 경계."""
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community import rookie_league as L
from community.models import RookieAward, RookieSeasonStat
from community.test_rookie_league import player

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


def stat(p, season, war, *, g=120, retired=True, legacy=False):
    t = ({'g': g, 'gs': g, 'w': 12, 'l': 6, 'sv': 0, 'outs': 540, 'er': 60, 'h': 150, 'bb': 40, 'so': 160, 'hr': 15, 'bf': 760}
         if p.role == 'pitcher' else {'g': g, 'pa': 500, 'ab': 450, 'h': 140, 'hr': 20, 'rbi': 70, 'bb': 45, 'so': 90})
    RookieSeasonStat.objects.create(season=L.get_season(season), user=p.user, player=p, league='kbo1', name=p.name,
                                    team=p.club, role=p.role, position=p.position, war=war, best_ovr=70, age=30, totals=t)
    if legacy:                                       # 1.1 업데이트 전에 시작한 선수 — 버전 표식이 없다
        p.career.pop('game_version', None)
    else:                                            # test_rookie_league.player 는 career 를 새로 써서 표식을 지운다
        p.career['game_version'] = '1.1'
    if retired:
        p.retired_at = timezone.now()
        p.career['retired'] = {'age': 34}
    p.save()
    return p


class RecordsFilterTests(TestCase):
    """기록실 — 보기 탭 + 거르기 카드(버전·투수타자·리그), 이름 칸 안 순위와 보조 줄, 역할마다 다른 열."""

    def setUp(self):
        cache.clear()
        self.bat = stat(player('전당타자', 'batter', 'lg', 'SS'), 1, 5.0)
        self.pit = stat(player('전당투수', 'pitcher', 'doosan', 'SP'), 1, 4.0)
        self.live = stat(player('현역타자', 'batter', 'kia', '2B'), 1, 3.0, retired=False)

    def get(self, ua=PC, **q):
        return self.client.get('/rookie/records/', q, HTTP_USER_AGENT=ua)

    def test_hall_all_shows_both_roles_and_lineup(self):
        for ua in (PC, MOBILE):
            with self.subTest(ua=ua[:20]):
                r = self.get(ua, view='hof', lg='kbo1')
                self.assertEqual(r.context['role'], '')
                self.assertEqual({x['p'].pk for x in r.context['rows']}, {self.bat.pk, self.pit.pk})   # 현역은 빠진다
                self.assertIsNotNone(r.context['lineup'])
                self.assertContains(r, 'data-rl-filter')
                self.assertContains(r, '<option value="" selected>전체</option>', html=False)
                self.assertContains(r, '타자 · 34세 은퇴')
                self.assertContains(r, '선수 2명')
                self.assertContains(r, '역대 베스트 라인업')

    def test_hall_role_filter_switches_columns_and_hides_lineup(self):
        r = self.get(view='hof', lg='kbo1', role='pitcher')
        self.assertEqual([x['p'].pk for x in r.context['rows']], [self.pit.pk])
        self.assertNotIn('lineup', r.context)                    # 라인업은 '전체'일 때만(라이트와 같다)
        self.assertContains(r, '<th scope="col">평균자책점</th>', html=False)
        self.assertContains(r, '투수 1명')
        r = self.get(view='hof', lg='kbo1', role='batter')
        self.assertEqual([x['p'].pk for x in r.context['rows']], [self.bat.pk])
        self.assertContains(r, '<th scope="col">OPS</th>', html=False)

    def test_career_ranking_lists_active_and_retired(self):
        r = self.get(view='career', lg='kbo1')
        self.assertEqual({x['p'].pk for x in r.context['rows']}, {self.bat.pk, self.pit.pk, self.live.pk})
        self.assertContains(r, '현역')
        self.assertNotContains(r, '<select name="version">', html=False)   # 버전은 명예의 전당에서만
        r = self.get(view='career', lg='kbo1', role='batter')
        self.assertEqual({x['p'].pk for x in r.context['rows']}, {self.bat.pk, self.live.pk})

    def test_career_highs_keep_batter_pitcher_only(self):
        r = self.get(view='highs', lg='kbo1')
        self.assertEqual(r.context['role'], 'batter')
        self.assertNotContains(r, '<option value="">전체</option>', html=False)
        r = self.get(view='highs', lg='kbo1', role='nonsense')
        self.assertEqual(r.context['role'], 'batter')
        r = self.get(view='highs', lg='kbo1', role='pitcher')
        self.assertEqual(r.context['role'], 'pitcher')

    def test_bad_query_values_fall_back(self):
        for q in (dict(view='hof', role='x', version='9'), dict(view='zzz', lg='nowhere'), dict(view='career', role='')):
            with self.subTest(q=q):
                r = self.get(**q)
                self.assertEqual(r.status_code, 200)

    def test_legacy_player_stays_in_10_hall(self):
        old = stat(player('옛전당', 'batter', 'ssg', 'C'), 1, 6.0, legacy=True)
        r = self.get(view='hof', lg='kbo1', version='1.0')
        self.assertEqual([x['p'].pk for x in r.context['rows']], [old.pk])
        self.assertContains(r, '<option value="1.0" selected>', html=False)
        r = self.get(view='hof', lg='kbo1')
        self.assertNotIn(old.pk, [x['p'].pk for x in r.context['rows']])

    def test_half_mvp_is_not_counted_in_hall_order(self):
        s = L.get_season(1)
        RookieAward.objects.create(season=s, user=self.pit.user, player=self.pit, league='kbo1', kind='half',
                                   label='전기리그 MVP', name=self.pit.name, team=self.pit.club, role='pitcher', value='')
        r = self.get(view='hof', lg='kbo1')
        row = next(x for x in r.context['rows'] if x['p'].pk == self.pit.pk)
        self.assertEqual((row['mvp'], row['awards']), (0, 0))


# ───────────────────────────── 시즌 1(옛 방식) → 시즌 2(시간대·전후기·가을야구) 경계
from datetime import datetime, time, timedelta  # noqa: E402
from io import StringIO  # noqa: E402
from unittest import mock  # noqa: E402

from django.core.management import call_command  # noqa: E402
from django.test import override_settings  # noqa: E402

from community import rookie as R  # noqa: E402
from community import rookie_clock as Clock  # noqa: E402
from community.models import RookieGame, RookieLog, RookiePlayer, RookieSeason  # noqa: E402
from community.test_rookie_league import backdate, member  # noqa: E402

PROD = dict(ROOKIE_FULL_SLOTS='true', ROOKIE_FULL_HALVES='true', ROOKIE_FULL_POSTSEASON='true', ROOKIE_SLOTS_FROM_SEASON='2')
S1_END = L.season_bounds(1)[1]                    # 2026-11-15
S2 = L.season_bounds(2)[0]                        # 2026-11-18


def at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


def legacy(p):
    """운영 시즌 1 선수처럼 — 버전 표식 없음(1.0), 시즌 1 개인 세계(전·후기 아님)."""
    p.career.pop('game_version', None)
    p.career['career_universe'] = {'year': 1, 'leagues': {p.league: {'games': L.season_games(p.league), 'scores': []}}}
    p.save()
    return p


def checkin(p, day, hh=9):
    log = RookieLog.objects.create(player=p, kind='earn', source='checkin', ref=f'c{day}', tp=20, text='출석', day=day)
    RookieLog.objects.filter(pk=log.pk).update(created_at=at(day, hh))


@override_settings(**PROD)
class SeasonTwoTransitionTests(TestCase):
    def setUp(self):
        cache.clear()
        s1 = L.get_season(1)
        s1.simulated_through = S1_END - timedelta(days=1)          # 시즌 1 마지막 경기일만 남은 상태
        s1.save()
        self.pro = legacy(player('옛프로', 'batter', 'lg', 'SS'))
        u = member('옛리틀')
        self.kid = R.create(u, name='옛리틀', role='pitcher', team='lg', region='서울')
        backdate(self.kid)
        self.kid.refresh_from_db()
        legacy(self.kid)
        for p in (self.pro, self.kid):
            for d in (S1_END, S2 - timedelta(days=1), S2):
                checkin(p, d)

    def run_at(self, when, cmd):
        with mock.patch('django.utils.timezone.now', return_value=when):
            call_command(cmd, stdout=StringIO())

    def games(self, p, day):
        return RookieGame.objects.filter(player=p, day=day).count()

    def test_season_one_closes_the_old_way_at_midnight(self):
        self.run_at(at(S1_END + timedelta(days=1), 0, 10), 'rookie_daily')
        s1 = RookieSeason.objects.get(number=1)
        self.assertTrue(s1.closed)
        self.assertIsNone(s1.slot_through)                          # 시즌 1 은 시간대 진행이 아니다
        self.assertEqual(self.games(self.pro, S1_END), len(L.games_on(S1_END)))
        self.assertFalse(Clock.active(1))
        self.assertTrue(Clock.active(2) and Clock.split_season(2))

    def test_off_days_play_nothing_and_opening_waits_for_first_slot(self):
        self.run_at(at(S1_END + timedelta(days=1), 0, 10), 'rookie_daily')
        for when in (at(S2 - timedelta(days=1), 0, 10), at(S2, 0, 10), at(S2, 10, 59)):
            self.run_at(when, 'rookie_daily' if when.hour == 0 else 'rookie_tick')
        self.assertEqual(RookieGame.objects.filter(day__gt=S1_END).count(), 0)
        self.assertFalse(RookieSeason.objects.filter(number=2, slot_through__isnull=False).exists())

    def test_legacy_players_play_season_two_by_slot_without_double_games(self):
        self.run_at(at(S1_END + timedelta(days=1), 0, 10), 'rookie_daily')
        plan = Clock.club_games_on('kbo1', self.pro.club, S2)       # 내 구단 그날 경기(전·후기 대진은 쉬는 판이 있다)
        first = Clock.SLOTS[plan[0][0]]
        self.run_at(at(S2, first.hour, first.minute + 5), 'rookie_tick')
        self.assertEqual(self.games(self.pro, S2), 1)
        for hh, mm in ((13, 5), (15, 35), (18, 5), (20, 5), (22, 5), (23, 55)):
            self.run_at(at(S2, hh, mm), 'rookie_tick')
        self.run_at(at(S2 + timedelta(days=1), 0, 10), 'rookie_daily')   # 밤 정산이 같은 날을 다시 치르지 않는다
        self.assertEqual(self.games(self.pro, S2), len(plan))
        # 학생 투수는 선발 차례·구원 확률로 등판이 갈린다 — 시즌 2 기록이 생기고, 구단 경기 수를 넘지 않으면(중복 없음) 된다
        self.assertLessEqual(self.games(self.kid, S2), len(Clock.club_games_on(self.kid.league, self.kid.club, S2)))
        self.assertTrue(RookieSeasonStat.objects.filter(season__number=2, player=self.kid).exists())
        s2 = RookieSeason.objects.get(number=2)
        self.assertEqual((s2.simulated_through, s2.slot_through), (S2, Clock.slot_at(S2, len(Clock.SLOTS) - 1)))
        for p in (self.pro, self.kid):
            p.refresh_from_db()
            self.assertIsNone(p.retired_at)                         # 만든 선수 그대로 이어서 뛴다
            self.assertNotIn('game_version', p.career)              # 1.0 선수는 끝까지 1.0
        world = self.pro.career['career_universe']
        self.assertEqual(world['year'], 2)
        self.assertTrue(world['leagues']['kbo1'].get('split'))      # 시즌 2 개인 세계는 전·후기 대진
        self.assertTrue(world['leagues']['kbo1']['scores'])

    def test_off_days_show_last_game_with_opening_notes(self):
        self.run_at(at(S1_END + timedelta(days=1), 0, 10), 'rookie_daily')     # 시즌 1 마지막 경기·시상
        self.client.force_login(self.pro.user)
        for ua in (PC, MOBILE):
            cache.clear()
            with mock.patch('django.utils.timezone.now', return_value=at(S2 - timedelta(days=1), 15)):
                r = self.client.get('/rookie/', HTTP_USER_AGENT=ua)
            self.assertContains(r, 'rk-board-off')                              # 경기 결과 칸: 휴식기 안내 + 마지막 경기
            self.assertContains(r, '시즌 2 개막(11월 18일)부터 새 중계가 올라와요')  # '오늘 경기가 끝나면'이 아니다
            self.assertNotContains(r, '오늘 경기가 끝나면 새 중계로 바뀌어요')

    def test_pages_render_across_the_boundary(self):
        pages = ['/rookie/', '/rookie/league/', '/rookie/world/', '/rookie/awards/', '/rookie/records/',
                 '/rookie/records/?view=career', '/rookie/records/?view=hof&version=1.0', '/rookie/report/']
        moments = [at(S1_END + timedelta(days=1), 10), at(S2 - timedelta(days=1), 22), at(S2, 10, 30), at(S2, 13, 30), at(S2, 23, 30)]
        for p in (self.pro, self.kid):
            self.client.force_login(p.user)
            for when in moments:
                for ua in (PC, MOBILE):
                    for url in pages + [f'/rookie/p/{p.pk}/']:
                        with self.subTest(who=p.name, when=str(when), ua=ua[:12], url=url), \
                                mock.patch('django.utils.timezone.now', return_value=when):
                            cache.clear()                           # 보안 미들웨어의 과다 요청 차단(127.0.0.1)을 피한다
                            r = self.client.get(url, HTTP_USER_AGENT=ua, follow=True)
                            self.assertEqual(r.status_code, 200)
        self.assertEqual(RookiePlayer.objects.filter(retired_at__isnull=True).count(), 2)


# ───────────────────────────── 시즌 개막 전 새 출발 선택(rookie_reset)
from community import rookie_career as C  # noqa: E402
from community import rookie_reset as Reset  # noqa: E402


@override_settings(**PROD)
class SeasonResetChoiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.p = player('선택선수', 'batter', 'lg', 'SS')
        self.off = at(S2 - timedelta(days=1), 21)                  # 휴식기(11-17 21:00)

    def now(self, when):
        return mock.patch('django.utils.timezone.now', return_value=when)

    def test_window_runs_from_day_after_close_to_first_slot(self):
        self.assertIsNone(Reset.window(at(S1_END, 23, 59)))
        self.assertEqual(Reset.window(at(S1_END + timedelta(days=1), 0, 0))['season'], 2)
        self.assertEqual(Reset.window(at(S2, 10, 59))['season'], 2)
        self.assertIsNone(Reset.window(at(S2, 11, 0)))               # 첫 시간대가 열리면 끝
        self.assertIsNone(Reset.window(at(S2 + timedelta(days=3), 9)))
        self.assertIsNone(Reset.window(at(L.EPOCH - timedelta(days=1), 12)))   # 시즌 1 개막 전에는 묻지 않는다
        s3 = L.season_bounds(3)[0]
        self.assertEqual(Reset.window(at(s3 - timedelta(days=1), 12))['season'], 3)  # 매 시즌 휴식기마다

    def test_offer_only_once_and_not_for_players_made_in_the_window(self):
        self.assertTrue(Reset.offer(self.p, self.off))
        late = player('휴식기입단', 'batter', 'kia', 'SS')
        RookiePlayer.objects.filter(pk=late.pk).update(created_at=at(S1_END + timedelta(days=1), 9))
        late.refresh_from_db()
        self.assertIsNone(Reset.offer(late, self.off))
        with self.now(self.off):
            Reset.keep(self.p.user)
        self.p.refresh_from_db()
        self.assertEqual(Reset.chosen(self.p, 2), Reset.KEEP)
        self.assertIsNone(Reset.offer(self.p, self.off))
        self.assertIsNone(self.p.retired_at)

    def test_reset_retires_keeps_records_and_new_player_rolls_fresh(self):
        old_pk, old_pot = self.p.pk, self.p.potential
        with self.now(self.off):
            r = Reset.reset(self.p.user)
        self.assertEqual((r['season'], r['pk']), (2, old_pk))
        old = RookiePlayer.objects.get(pk=old_pk)
        self.assertIsNotNone(old.retired_at)
        self.assertEqual(old.career['season_reset'], 2)
        self.assertEqual(old.career['retired']['reason'], '시즌 2 개막 전 새 출발')
        self.assertEqual(Reset.chosen(old, 2), Reset.RESET)
        fresh = 97 if old_pot != 97 else 96
        with self.now(self.off), mock.patch.object(C, 'roll_potential', return_value=fresh):
            self.assertIsNone(R.inherits_from(self.p.user))        # 짧게 뛰었어도 시즌 새 출발은 이어받지 않는다
            new = R.create(self.p.user, name='새출발', role='pitcher', team='lg', region='서울')
        self.assertEqual(new.potential, fresh)
        self.assertEqual(new.career['game_version'], '1.1')
        self.assertIsNone(Reset.offer(new, self.off))              # 새 선수에게 다시 묻지 않는다
        with self.now(self.off), self.assertRaises(Reset.ResetError):
            Reset.keep(member('없는회원'))                         # 현역 선수가 없으면 거절

    def test_plain_retire_still_inherits(self):
        RookiePlayer.objects.filter(pk=self.p.pk).update(created_at=self.off - timedelta(days=10))   # 짧은 커리어(30일 미만)
        with self.now(self.off):
            R.retire(self.p.user)
            self.assertEqual(R.inherits_from(self.p.user).pk, self.p.pk)

    def test_view_needs_confirm_and_window(self):
        self.client.force_login(self.p.user)
        url = '/rookie/season-choice/'
        with self.now(self.off):
            self.client.post(url, {'choice': 'reset'}, HTTP_USER_AGENT=PC)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.retired_at)                       # 확인 칸 없이는 은퇴하지 않는다
        with self.now(at(S2, 12)):                                 # 기간이 지나면 거절
            self.client.post(url, {'choice': 'reset', 'confirm': 'yes'}, HTTP_USER_AGENT=PC)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.retired_at)
        with self.now(self.off):
            r = self.client.post(url, {'choice': 'reset', 'confirm': 'yes'}, HTTP_USER_AGENT=PC)
        self.assertRedirects(r, '/rookie/', fetch_redirect_response=False)
        self.p.refresh_from_db()
        self.assertIsNotNone(self.p.retired_at)
        self.assertEqual(self.client.get('/rookie/season-choice/').status_code, 405)

    def test_home_shows_panel_only_in_window_on_pc_and_mobile(self):
        self.client.force_login(self.p.user)
        for ua in (PC, MOBILE):
            with self.subTest(ua=ua[:12]):
                cache.clear()
                with self.now(self.off):
                    r = self.client.get('/rookie/', HTTP_USER_AGENT=ua)
                self.assertContains(r, '선택선수 선수와 시즌 2도 함께할까요?')
                self.assertContains(r, '11월 18일 11:00까지')
                cache.clear()
                with self.now(at(S2, 12)):
                    r = self.client.get('/rookie/', HTTP_USER_AGENT=ua)
                self.assertNotContains(r, 'rk-season-choice')


# ───────────────────────────── 시즌 2 개막 전 화면 정돈(2026-11-16)
import importlib  # noqa: E402
from types import SimpleNamespace  # noqa: E402


class AwardTextTests(TestCase):
    def test_award_title_names_league_once(self):
        self.assertEqual(L.award_title(SimpleNamespace(league='ms', label='중학 최우수선수')), '중학 최우수선수')
        self.assertEqual(L.award_title(SimpleNamespace(league='ms', label='홈런상')), '중학 홈런상')

    def test_migration_fixes_doubled_league_and_is_idempotent(self):
        from django.apps import apps
        p = player('기록정리', 'batter', 'lg', 'SS')
        bad = RookieLog.objects.create(player=p, kind='award', text='시즌 1 중학 중학 최우수선수 수상 — 타율 .306', day=S1_END)
        ok = RookieLog.objects.create(player=p, kind='award', text='시즌 1 중학 홈런상 수상 — 3홈런', day=S1_END)
        other = RookieLog.objects.create(player=p, kind='mile', text='중학 중학 이정표', day=S1_END)
        m = importlib.import_module('community.migrations.0058_rookie_award_log_text')
        for _ in range(2):
            m.dedupe(apps, None)
        for log, text in ((bad, '시즌 1 중학 최우수선수 수상 — 타율 .306'), (ok, '시즌 1 중학 홈런상 수상 — 3홈런'),
                          (other, '중학 중학 이정표')):
            log.refresh_from_db()
            self.assertEqual(log.text, text)


@override_settings(**PROD)
class LayoutPolishTests(TestCase):
    def setUp(self):
        cache.clear()
        self.p = player('정돈선수', 'batter', 'lg', 'SS')
        self.client.force_login(self.p.user)

    def get(self, url, ua=PC, when=None):
        cache.clear()
        with mock.patch('django.utils.timezone.now', return_value=when or at(S2 - timedelta(days=1), 21)):
            return self.client.get(url, HTTP_USER_AGENT=ua)

    def test_report_page_uses_game_header_and_filter(self):
        for ua in (PC, MOBILE):
            r = self.get('/rookie/report/', ua)
            self.assertContains(r, 'class="rk-nav"')
            self.assertContains(r, 'aria-current="page">선수 리포트</a>', html=False)
            self.assertContains(r, 'rl-filter rk-report-filter')
            self.assertContains(r, 'css/game.css')

    def test_own_player_page_marks_my_player_tab(self):
        r = self.get(f'/rookie/p/{self.p.pk}/')
        self.assertContains(r, 'aria-current="page">내 선수</a>', html=False)
        other = player('남의선수', 'batter', 'kia', 'SS')
        r = self.get(f'/rookie/p/{other.pk}/')
        self.assertContains(r, 'aria-current="page">리그</a>', html=False)

    def test_league_opens_on_last_league_with_records(self):
        RookieSeasonStat.objects.create(season=L.get_season(1), user=self.p.user, player=self.p, league='ms', name=self.p.name,
                                        team='건대부중', role='batter', position='SS', totals={'g': 20, 'pa': 80})
        path = [{'league': 'ms', 'club': '건대부중', 'age': 13, 'day': '2026-10-20'},
                {'league': 'hs', 'club': '소래고', 'age': 16, 'day': '2026-11-16'}]
        RookiePlayer.objects.filter(pk=self.p.pk).update(league='hs', career=dict(self.p.career, path=path))
        r = self.get('/rookie/league/')
        self.assertEqual(r.context['lg'], 'ms')

    def test_card_keeps_avatar_number_block(self):
        r = self.get('/rookie/')
        self.assertContains(r, 'class="rk-card-avatar-number"')

    def test_awards_board_plates_and_roll(self):
        s = L.get_season(1)
        s.closed = True
        s.save()
        st = RookieSeasonStat.objects.create(season=s, user=self.p.user, player=self.p, league='kbo1', name=self.p.name,
                                             team='lg', role='batter', position='SS',
                                             totals={'g': 120, 'pa': 500, 'ab': 450, 'h': 140, 'hr': 20, 'rbi': 70}, war=5.0)
        mk = dict(season=s, user=self.p.user, player=self.p, league='kbo1', name=self.p.name, team='lg', role='batter')
        RookieAward.objects.create(stat=st, kind='mvp', label='MVP', value='WAR 5.0', **mk)
        RookieAward.objects.create(kind='rookie', label='신인왕', value='타율 .311', order=1, **mk)
        RookieAward.objects.create(kind='title', label='홈런왕', value='20홈런', order=10, **mk)
        for ua in (PC, MOBILE):
            r = self.get('/rookie/awards/?lg=kbo1', ua, when=at(S2 - timedelta(days=1), 21))
            self.assertContains(r, 'class="rk-aw-board"')
            self.assertContains(r, 'rk-aw-plate')
            self.assertContains(r, '<ol class="rk-aw-roll">', html=False)
            self.assertContains(r, 'css/rookie-awards.css')
            self.assertNotContains(r, 'rk-plaque is-mvp')

    def test_report_date_moves_without_button(self):
        r = self.get('/rookie/report/')
        self.assertContains(r, 'data-rk-report-day')
        self.assertContains(r, 'min="2026-10-19"', html=False)
        self.assertContains(r, '<noscript><button', html=False)      # 버튼은 자바스크립트가 꺼진 때만
