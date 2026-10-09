from django.contrib.auth.models import User
from django.test import TestCase

from common.models import Profile
from community.models import Game2048, MinesweeperGame, NumberBaseballGame

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


def player(name):
    u = User.objects.create(username=name, email=f'{name}@example.com')
    p, _ = Profile.objects.get_or_create(user=u)
    p.is_email_verified = True
    p.save()
    return u


class GamePagesTests(TestCase):
    def setUp(self):
        self.a, self.b = player('a'), player('b')
        for u, attempts in ((self.a, (4, 6, 9)), (self.b, (5, 7))):
            for i, n in enumerate(attempts):
                NumberBaseballGame.objects.create(player=u, secret_number='1234', attempts=n, difficulty='normal',
                                                  status='won' if i < 2 else 'lost')

    def get(self, url, ua=PC):
        self.client.force_login(self.a)
        return self.client.get(url, HTTP_USER_AGENT=ua)

    def test_baseball_leaderboard_total_is_all_games_not_last_player(self):
        # 예전엔 반복문의 개인 판 수가 전체 판 수 변수를 덮어써 '전체 판'이 마지막 사람 기록으로 나왔다
        res = self.get('/baseball/leaderboard/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '전체 판</span><span class="gm-stat-value">5<', html=False)
        self.assertContains(res, '2/3판')
        self.assertContains(res, '2/2판')

    def test_all_game_pages_render_on_pc_and_mobile(self):
        self.client.force_login(self.a)
        self.client.get('/2048/create/?difficulty=normal', HTTP_USER_AGENT=PC)
        self.client.get('/minesweeper/create/?difficulty=hard', HTTP_USER_AGENT=PC)
        g2 = Game2048.objects.get(player=self.a)
        ms = MinesweeperGame.objects.get(player=self.a)
        bb = NumberBaseballGame.objects.filter(player=self.a).first()
        urls = ['/games/', '/baseball/', '/2048/', '/minesweeper/',
                '/baseball/leaderboard/', '/2048/leaderboard/', '/minesweeper/leaderboard/?difficulty=hard',
                f'/2048/{g2.id}/', f'/minesweeper/{ms.id}/', f'/baseball/{bb.id}/']
        for ua, base_marker in ((PC, 'navbar'), (MOBILE, 'm-tabbar')):
            for url in urls:
                res = self.client.get(url, HTTP_USER_AGENT=ua)
                self.assertEqual(res.status_code, 200, url)
                self.assertContains(res, 'css/game.css', msg_prefix=url)
                self.assertContains(res, base_marker, msg_prefix=f'{url} ({ua[:20]})')

    def test_finished_baseball_game_does_not_render_input(self):
        bb = NumberBaseballGame.objects.filter(player=self.a, status='lost').first()
        res = self.get(f'/baseball/{bb.id}/')
        self.assertNotContains(res, 'id="guessInput"')
        self.assertContains(res, "if (guessInput)")  # 입력창이 없어도 스크립트가 멈추지 않는다
