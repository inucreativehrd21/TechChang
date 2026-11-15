"""가상 구단 로스터의 국적 구성 — 리그 외국인 규정·해외 리그 자국 이름(rookie_nations)."""
from django.test import SimpleTestCase

from . import rookie_nations as N
from . import rookie_universe as U
from . import rookie_world_hub as Hub
from .rookie_text import is_real_person


def _rosters(league, years=(1, 2, 3)):
    return [(club, year, Hub.roster(league, club, year)) for club in U.teams(league) for year in years]


def _foreign(roster):
    return [p for p in roster if p['nation']]


class QuotaLeagueTests(SimpleTestCase):
    def test_kbo_teams_have_three_foreigners_and_one_asia_quota(self):
        for club, year, roster in _rosters('kbo1'):
            foreign = _foreign(roster)
            regular = [p for p in foreign if p['tag'] == '외국인']
            asia = [p for p in foreign if p['tag'] == '아시아쿼터']
            self.assertEqual((len(regular), len(asia)), (3, 1), club)
            self.assertIn(asia[0]['nation'], ('일본', '대만', '호주'))
            self.assertEqual(len({p['role'] for p in regular}), 2, club)     # 투수·타자 한쪽으로 3명은 안 된다

    def test_npb_first_team_four_foreigners_at_most_three_of_one_kind(self):
        for club, year, roster in _rosters('npb1'):
            foreign = _foreign(roster)
            self.assertEqual(len(foreign), 4, club)
            pitchers = sum(p['role'] == 'pitcher' for p in foreign)
            self.assertTrue(1 <= pitchers <= 3, club)

    def test_cpbl_three_foreigners_mostly_pitchers(self):
        for club, year, roster in _rosters('cpbl'):
            foreign = _foreign(roster)
            self.assertEqual(len(foreign), 3, club)
            self.assertGreaterEqual(sum(p['role'] == 'pitcher' for p in foreign), 2, club)

    def test_foreign_batters_are_starters(self):
        for club, year, roster in _rosters('kbo1') + _rosters('npb1'):
            for i, p in enumerate(roster):
                if p['nation'] and p['role'] == 'batter':
                    self.assertIn(i, N.FOREIGN_BAT, club)

    def test_amateur_and_kbo_farm_rosters_stay_korean(self):
        for league in ('little', 'ms', 'hs', 'univ', 'kbo2', 'kbo3'):
            for club in U.teams(league)[:4]:
                self.assertEqual(_foreign(Hub.roster(league, club, 1)), [], (league, club))


class AbroadLeagueTests(SimpleTestCase):
    def test_mlb_international_share_follows_opening_day_rate(self):
        rows = [p for _c, _y, roster in _rosters('mlb', years=(1,)) for p in roster]
        share = len(_foreign(rows)) / len(rows)
        self.assertTrue(.20 <= share <= .33, share)
        per_team = {len(_foreign(Hub.roster('mlb', club, 1))) for club in U.teams('mlb')}
        self.assertGreater(len(per_team), 3)                    # 구단마다 다르게 흔들린다

    def test_home_players_get_local_names(self):
        jp_family = set(N.POOLS['jp'][0])
        for club in U.teams('npb1'):
            for p in Hub.roster('npb1', club, 1):
                if not p['nation']:
                    self.assertIn(p['name'].split()[0], jp_family)
        us_given = set(N.POOLS['us'][0])
        for club in U.teams('mlb'):
            for p in Hub.roster('mlb', club, 1):
                if not p['nation']:
                    self.assertIn(p['name'].split()[0], us_given)
        tw_family = set(N.POOLS['tw'][0])
        for club in U.teams('cpbl'):
            for p in Hub.roster('cpbl', club, 1):
                if not p['nation']:
                    self.assertIn(N.family('tw', p['name']), tw_family)
                    self.assertNotIn(' ', p['name'])

    def test_names_unique_safe_and_stable_across_seasons(self):
        for league in ('kbo1', 'npb1', 'npb2', 'cpbl', 'mlb', 'mlb_a'):
            for club in U.teams(league):
                first, second = Hub.roster(league, club, 1), Hub.roster(league, club, 2)
                names = [p['name'] for p in first]
                self.assertEqual(len(names), len(set(names)), (league, club))
                self.assertEqual([n for n in names if is_real_person(n)], [])
                for a, b in zip(first, second):
                    if a['id'] == b['id']:                     # 같은 선수면 이름·국적이 시즌을 넘어도 같다
                        self.assertEqual((a['name'], a['nation']), (b['name'], b['nation']))

    def test_famous_foreign_combinations_are_blocked(self):
        self.assertTrue(is_real_person('호세 라미레스'))
        self.assertTrue(is_real_person('사카모토 하야토'))
        self.assertFalse(is_real_person('오스틴 킹'))

    def test_every_league_with_foreigners_has_a_note(self):
        for league in list(N.QUOTA) + list(N.LOOSE) + list(N.INTL_RATE):
            self.assertTrue(N.NOTE.get(league), league)
