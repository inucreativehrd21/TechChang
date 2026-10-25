"""MySQL UNSIGNED 나이 뺄셈으로 발생한 회원 비교 500 오류 회귀 검사."""
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from . import rookie_league as L
from . import rookie_peers as Peers
from .models import LiteSeason, RookieSeasonStat
from .test_rookie_league import player
from .test_rookie_lite import MOBILE, PC, new


TOTALS = dict(g=30, pa=120, ab=100, h=35, d=5, t=0, hr=4, bb=20, so=15, rbi=20)


@override_settings(ROOKIE_EXTREME_ENABLED=True)
class PeerAgeTests(TestCase):
    def setUp(self):
        cache.clear()

    def lite_season(self, c, age, ovr):
        return LiteSeason.objects.create(career=c, age=age, year=1, league='hs', club=c.club,
                                         games=30, ovr_end=ovr, totals=TOTALS)

    def check_lite_mode(self, mode):
        mine, younger, older = [new(name) for name in ('본인', '어린회원', '나이든회원')]
        for c in (mine, younger, older):
            c.mode = mode
            c.save(update_fields=['mode'])
        self.lite_season(mine, 17, 55)
        self.lite_season(younger, 16, 55)
        self.lite_season(older, 18, 60)
        rows = Peers.comparisons(mine)
        self.assertEqual([row['player_id'] for row in rows], [younger.pk, older.pk])
        self.assertEqual([row['age'] for row in rows], [16, 18])
        for ua in (PC, MOBILE):
            with self.subTest(mode=mode, ua=ua):
                client = Client(HTTP_USER_AGENT=ua)
                client.force_login(mine.user)
                response = client.get(f'/rookie/{mode}/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['peers'], rows)

    def test_lite_page_with_younger_and_older_peers(self):
        self.check_lite_mode('lite')

    def test_extreme_page_with_younger_and_older_peers(self):
        self.check_lite_mode('extreme')

    def test_daily_comparison_with_younger_and_older_peers(self):
        mine, younger, older = [player(name) for name in ('정식본인', '정식어린회원', '정식나이든회원')]
        for p, age, ovr in ((mine, 17, 55), (younger, 16, 55), (older, 18, 60)):
            RookieSeasonStat.objects.create(player=p, user=p.user, season=L.get_season(1),
                role=p.role, name=p.name, team=p.club, league=p.league, age=age, best_ovr=ovr, totals=TOTALS)
        self.assertEqual([row['player_id'] for row in Peers.comparisons(mine)], [younger.pk, older.pk])
