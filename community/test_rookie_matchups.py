"""회원 맞대결의 양방향 기록·출전 경계·저장 원자성·실제 화면을 검증해요."""
import random
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from community import rookie_league as L, rookie_matchups as H, rookie_sim as M, rookie_universe as U
from community.models import RookieGame, RookieSeasonStat
from community.test_rookie_league import D1, PC, MOBILE, active_on, player


class MemberMatchupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.bat = player('회원타자', level=64)
        self.pit = player('회원투수', 'pitcher', level=64)
        no = list(L.games_on(D1))[self.pit.pk % len(L.games_on(D1))]
        self.opponent = U.club_fixtures('kbo1', 144, self.bat.club)[no - 1]['opponent']
        self.pit.club = self.opponent
        self.pit.career['path'][-1]['club'] = self.opponent
        self.pit.save()
        for p in (self.bat, self.pit):
            active_on(p, D1)

    def run_day(self):
        self.assertEqual(L.simulate_day(D1, random.Random(51)), 2)
        pit = RookieGame.objects.get(player=self.pit)
        bat = RookieGame.objects.get(player=self.bat, no=pit.no)
        return bat, pit

    def test_same_outcome_is_saved_to_both_players_and_season_totals(self):
        bat, pit = self.run_day()
        bd, pd = bat.line['member_duels'], pit.line['member_duels']
        self.assertEqual(len(bd), 1)
        self.assertEqual(bd[0]['outcome'], pd[0]['outcome'])
        self.assertEqual(bd[0]['opponent']['id'], self.pit.pk)
        self.assertEqual(pd[0]['opponent']['id'], self.bat.pk)
        self.assertEqual((bat.team_runs, bat.opp_runs), (pit.opp_runs, pit.team_runs))
        self.assertEqual(bat.line['member_pa'], 1)
        for p in (self.bat, self.pit):
            total = {}
            for g in p.games.all():
                total = L.add(total, g.line)
            self.assertEqual(RookieSeasonStat.objects.get(player=p).totals, total)
            self.assertNotIn('member_duels', total)
        self.assertEqual(L.simulate_day(D1, random.Random(999)), 0)
        self.assertEqual(H.history(self.bat)[0]['pa'], 1)

    def test_uses_actual_abilities_and_opponents_are_reciprocal(self):
        with mock.patch.object(M, 'pa_probs', wraps=M.pa_probs) as probabilities:
            bat, pit = self.run_day()
        from community import rookie_career as C
        self.assertTrue(any(call.args == (C.game_stats(self.bat), C.game_stats(self.pit))
                            for call in probabilities.call_args_list))
        self.assertEqual(bat.line['member_opponents'][0]['id'], self.pit.pk)
        self.assertEqual(pit.line['member_opponents'][0]['id'], self.bat.pk)
        self.assertNotIn('name', bat.line['member_opponents'][0])

    def test_idle_players_do_not_create_duels(self):
        self.pit.logs.all().delete()
        L.simulate_day(D1, random.Random(51))
        self.assertFalse(any(g.line.get('member_duels') for g in self.bat.games.all()))
        self.assertEqual(H.history(self.bat), [])

    def test_other_league_does_not_match_even_with_same_club(self):
        self.pit.league = 'kbo2'
        self.pit.save()
        L.simulate_day(D1, random.Random(51))
        self.assertEqual(H.history(self.bat), [])

    def test_draft_waiting_member_is_not_an_opponent(self):
        self.pit.pending = dict(kind='draft', deadline='2026-10-21')
        self.pit.save()
        L.simulate_day(D1, random.Random(51))
        self.assertEqual(H.history(self.bat), [])
        self.assertFalse(self.pit.games.exists())

    def test_retired_member_is_not_an_opponent(self):
        from django.utils import timezone
        self.pit.retired_at = timezone.now()
        self.pit.save()
        L.simulate_day(D1, random.Random(51))
        self.assertEqual(H.history(self.bat), [])
        self.assertFalse(self.pit.games.exists())

    def test_same_team_is_never_a_direct_opponent(self):
        self.pit.club = self.bat.club
        self.pit.save()
        L.simulate_day(D1, random.Random(51))
        self.assertEqual(H.history(self.bat), [])

    def test_two_batters_share_team_result_without_fabricated_direct_pa(self):
        self.pit.role, self.pit.position = 'batter', 'SS'
        self.pit.stats = dict(self.bat.stats)
        self.pit.lineup, self.pit.slot = 'lower', 7
        self.pit.save()
        L.simulate_day(D1, random.Random(51))
        rows = H.history(self.bat)
        self.assertTrue(rows)
        self.assertTrue(all(not r['direct'] for r in rows))
        self.assertTrue(all(r['pa'] == 0 for r in rows))

    def test_transfer_preserves_stats_and_rename_uses_current_public_name(self):
        self.run_day()
        before = H.history(self.bat)
        self.pit.club, self.pit.name = 'kt', '새로운이름'
        self.pit.save()
        after = H.history(self.bat)
        self.assertEqual(before[0]['club'], after[0]['club'])
        self.assertEqual(before[0]['pa'], after[0]['pa'])
        self.assertEqual(after[0]['name'], '새로운이름')

    def test_deleted_member_is_not_exposed_or_linked(self):
        bat, pit = self.run_day()
        self.pit.user.delete()
        self.assertEqual(H.history(self.bat), [])
        self.assertEqual(L.game_view(bat, self.bat.club)['members'], [])

    def test_failed_shared_save_leaves_neither_half_of_duel(self):
        original = L._play
        def fail(p, *args, **kwargs):
            if p.pk == self.pit.pk:
                raise RuntimeError('save failed')
            return original(p, *args, **kwargs)
        with mock.patch.object(L, '_play', side_effect=fail):
            self.assertEqual(L.simulate_day(D1, random.Random(51)), 0)
        self.assertFalse(RookieGame.objects.exists())
        self.assertTrue(all(not s.totals for s in RookieSeasonStat.objects.all()))

    def test_legacy_games_have_no_invented_member_history(self):
        s = L.get_season(1)
        RookieGame.objects.create(player=self.bat, season=s, league='kbo1', day=D1, no=1,
                                  opponent=self.opponent, line={'g': 1, 'ab': 4, 'h': 1}, summary='4타수 1안타')
        self.assertEqual(H.history(self.bat), [])

    def test_report_and_public_pc_mobile_pages_show_saved_results(self):
        self.run_day()
        from community import rookie_reports as Reports
        self.assertEqual(Reports.daily(self.bat, D1)['member_history'][0]['pa'], 1)
        self.assertEqual(Reports.daily(self.bat, D1 + timedelta(days=1))['member_history'], [])
        for ua, version in ((PC, 'desktop'), (MOBILE, 'mobile')):
            cache.clear()
            self.client.cookies['force_version'] = version
            response = self.client.get(reverse('community:rookie_player', args=[self.bat.pk]), HTTP_USER_AGENT=ua)
            self.assertContains(response, '회원 선수 맞대결')
            self.assertContains(response, '직접 승부')
            self.assertContains(response, self.pit.name)
            self.assertContains(response, reverse('community:rookie_player', args=[self.pit.pk]))


class SharedPlateTests(TestCase):
    def test_every_shared_outcome_is_in_both_boxscores(self):
        bat = {k: 64 for k in M.BAT}
        pit = {k: 64 for k in M.PIT}
        for outcome in H.OUTCOME:
            forced = [dict(outcome=outcome, slot=7)]
            rng = random.Random(7)
            # 순수 타석을 관찰해 가상 상대의 나머지 타석과 구분한다.
            from collections import Counter
            b, p = Counter(), Counter()
            M._plate(b, bat, pit, 'reg', 7, 0, rng, {}, forced[0])
            M._pitch(p, pit, 64, rng, 7, 27, lambda t, _: t['bf'] >= 1, member_pas=forced)
            self.assertEqual(b['pa'], p['bf'])
            for key in ('h', 'hr', 'bb', 'hbp', 'so'):
                self.assertEqual(b[key], p[key], (outcome, key))
            self.assertEqual(b['ab'], int(outcome not in ('BB', 'HBP')))
            self.assertEqual(b['member_pa'], 1)

    def test_relief_limit_consumes_all_shared_pas_even_when_pull_is_early(self):
        forced = [dict(outcome='HR', slot=i + 1) for i in range(3)]
        result = M.relief_game({k: 64 for k in M.PIT}, 64, random.Random(3), 'closer', member_pas=forced)
        self.assertGreaterEqual(result['line']['hr'], 3)
        self.assertGreaterEqual(result['line']['bf'], 3)
