"""테크창 삼국지 카탈로그 검사 — 장수 명단 규칙과 지도."""
from django.test import SimpleTestCase

from community import samguk_data as D


class SamgukDataTests(SimpleTestCase):
    def test_validate_clean(self):
        self.assertEqual(D.validate(), [])

    def test_roster_size(self):
        s = D.summary()
        self.assertGreaterEqual(s['total'], 280)          # 1세대 본편 약 300명
        for group in D.GROUPS:
            self.assertIn(group, s['group'])
        for tier in D.TIERS:
            self.assertGreater(s['tier'][tier], 0)

    def test_added_women_are_available_in_recruitment_catalog(self):
        # 객잔과 매일 판의 후보는 본편 카탈로그에서 뽑아요.
        for code, group in [('daqiao', 'wu'), ('xiaoqiao', 'wu'), ('zhenji', 'wei')]:
            g = D.GENERAL[code]
            self.assertTrue(g.female)
            self.assertEqual(g.group, group)
            self.assertIn(g, D.by_tier(2))
            self.assertLess(g.war, 20)
            self.assertTrue(g.source.startswith('정사'))

    def test_codex_numbers_follow_groups(self):
        nos = [g.no for g in D.GENERALS]
        self.assertEqual(nos, list(range(1, len(nos) + 1)))
        order = [code for code, _ in D.roster.GROUPS]
        seen = [g.group for g in D.GENERALS]
        self.assertEqual(sorted(seen, key=order.index), seen)

    def test_hidden_generals_are_not_in_roster(self):
        # 외전 장수는 시리즈로만 얻는다(설계 8.3)
        for code in ('menghuo', 'zhurong', 'huatuo', 'simahui', 'huangyueying', 'zuoci', 'guanlu', 'yuji'):
            self.assertNotIn(code, D.GENERAL)

    def test_player_factions_have_lords(self):
        pools = {info['pool'] for info in D.LORDS.values()}
        self.assertTrue(set(D.FACTIONS) <= pools)

    def test_every_tier_four_is_strong_or_famous(self):
        for g in D.by_tier(4):
            self.assertTrue(max(g.stats) >= 92 or g.total >= 320, g.code)
