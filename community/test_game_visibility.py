"""운영자(admin) 계정의 게임 기록은 홈페이지 어디에도 보이지 않는다(community.game_visibility, 2026-10-16)."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

from common.models import Profile
from community.models import Game2048, MinesweeperGame, NumberBaseballGame

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


def player(name, shown):
    u = User.objects.create(username=name, email=f'{name}@example.com')
    p, _ = Profile.objects.get_or_create(user=u)
    p.is_email_verified = True
    p.nickname = shown
    p.save()
    return u


class AdminGameRecordsHiddenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = player('admin', '운영자테스트계정')
        self.mem = player('member1', '일반회원기록')
        for u in (self.admin, self.mem):
            NumberBaseballGame.objects.create(player=u, secret_number='1234', attempts=3 if u == self.admin else 7,
                                              difficulty='normal', status='won')
            Game2048.objects.create(player=u, best_score=99999 if u == self.admin else 512, status='won')
            MinesweeperGame.objects.create(player=u, difficulty='easy', status='won',
                                           time_elapsed=1 if u == self.admin else 90)

    def page(self, url, user=None, ua=PC):
        self.client.force_login(user or self.mem)
        return self.client.get(url, HTTP_USER_AGENT=ua)

    def test_leaderboards_skip_admin_on_pc_and_mobile(self):
        for ua in (PC, MOBILE):
            for url in ('/baseball/leaderboard/', '/2048/leaderboard/', '/minesweeper/leaderboard/?difficulty=easy'):
                r = self.page(url, ua=ua)
                self.assertEqual(r.status_code, 200, url)
                self.assertNotContains(r, '운영자테스트계정', msg_prefix=url)
                self.assertNotContains(r, '99999', msg_prefix=url)
                self.assertContains(r, '일반회원기록', msg_prefix=url)
        # 운영자 본인이 봐도 순위표에는 없다(머리말 닉네임은 별개라 점수로 확인)
        self.assertNotContains(self.page('/2048/leaderboard/', user=self.admin), '99999')

    def test_play_counts_skip_admin(self):
        r = self.page('/games/')
        self.assertContains(r, '지금까지 3판이 플레이됐습니다')       # 회원 3판만(운영자 3판 제외)
        r = self.client.get('/', HTTP_USER_AGENT=PC)
        self.assertEqual(r.status_code, 200)

    @override_settings(GAME_HIDDEN_USERNAMES=('member1',))
    def test_hidden_accounts_are_configurable(self):
        r = self.page('/2048/leaderboard/', user=self.admin)
        self.assertContains(r, '99999')
        self.assertNotContains(r, '일반회원기록')
