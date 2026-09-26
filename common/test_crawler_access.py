"""크롤러 접근성·스캐너 차단 회귀 테스트.

배경(2026-09 접근로그 분석):
- SUSPICIOUS_USER_AGENT_PATTERNS 의 'bot' 이 Googlebot 까지 걸어 의심 점수를 쌓고
  20회 요청이면 IP 를 차단했다. 검색 유입이 목표인 사이트에서 크롤러를 막고 있었다.
- 반대로 스캐너들은 UA 를 Googlebot 으로 위조한 채 /credentials.json,
  /.streamlit/secrets.toml, /docker-compose.yaml 등을 훑었다.
따라서 "정상 크롤러는 통과, 경로로 드러나는 스캐너는 차단" 이 되어야 한다.

사이트맵은 비로그인 방문자가 실제로 열 수 있는 URL 만 담아야 한다 — 로그인으로
302 되는 URL 을 넣으면 크롤링 예산만 쓰고 색인은 되지 않는다.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from common.middleware import SecurityMiddleware
from community.models import Category, Question
from community.sitemaps import QuestionSitemap, StaticViewSitemap
from community.views.base_views import ROBOTS_PATH

GOOGLEBOT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


class CrawlerNotBlockedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.mw = SecurityMiddleware(get_response=lambda r: HttpResponse())

    def tearDown(self):
        cache.clear()

    def _get(self, path='/', ua=GOOGLEBOT, ip='203.0.113.9'):
        req = self.factory.get(path, HTTP_USER_AGENT=ua, REMOTE_ADDR=ip)
        req.user = User(is_staff=False)
        return req

    def test_googlebot_user_agent_is_not_suspicious(self):
        self.assertFalse(self.mw.is_suspicious_user_agent(self._get()))

    def test_naver_and_bing_crawlers_are_not_suspicious(self):
        for ua in ('Mozilla/5.0 (compatible; Yeti/1.1; +http://naver.me/spd)',
                   'Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)'):
            self.assertFalse(self.mw.is_suspicious_user_agent(self._get(ua=ua)), ua)

    def test_googlebot_survives_a_full_sitemap_crawl(self):
        """차단 임계치를 넘는 연속 크롤링에도 막히지 않아야 한다."""
        ip = '66.249.65.204'
        for i in range(self.mw.SUSPICION_SCORE_THRESHOLD * 2):
            self.assertIsNone(self.mw.check_security(self._get(f'/{i}/', ip=ip)))
        self.assertFalse(self.mw.is_ip_blocked(ip))

    def test_unknown_bot_is_still_suspicious(self):
        ua = 'Mozilla/5.0 (compatible; GenomeCrawlerd/1.0; +https://www.nokia.com/genomecrawler)'
        self.assertTrue(self.mw.is_suspicious_user_agent(self._get(ua=ua)))

    def test_empty_user_agent_is_still_suspicious(self):
        self.assertTrue(self.mw.is_suspicious_user_agent(self._get(ua='')))


class ScannerProbeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.mw = SecurityMiddleware(get_response=lambda r: HttpResponse())

    def tearDown(self):
        cache.clear()

    def _probe(self, path, ip='198.51.100.7'):
        req = self.factory.get(path, HTTP_USER_AGENT=GOOGLEBOT, REMOTE_ADDR=ip)
        req.user = User(is_staff=False)
        return self.mw.check_security(req)

    def test_spoofed_googlebot_probing_secrets_is_blocked(self):
        """UA 를 Googlebot 으로 위조해도 경로로 잡힌다 — 실제 관측된 경로들."""
        for path in ('/credentials.json', '/.streamlit/secrets.toml', '/docker-compose.yaml',
                     '/.env', '/.git/HEAD', '/wp-admin/setup.php', '/api/fs/exec'):
            cache.clear()
            response = self._probe(path)
            self.assertIsNotNone(response, path)
            self.assertEqual(response.status_code, 403, path)

    def test_repeated_probes_block_the_ip(self):
        ip = '198.51.100.8'
        needed = -(-self.mw.SUSPICION_SCORE_THRESHOLD // self.mw.SCANNER_PROBE_WEIGHT)
        for _ in range(needed):
            self._probe('/.env', ip=ip)
        self.assertTrue(self.mw.is_ip_blocked(ip))

    def test_normal_pages_are_not_scanner_probes(self):
        for path in ('/', '/98/', '/members/', '/lab/', '/static/css/premium.css',
                     '/portfolios/my-portfolio/', '/sitemap.xml', '/robots.txt'):
            self.assertFalse(self.mw.is_scanner_probe(path), path)


class SitemapContentTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user('writer', password='x')
        self.open_cat = Category.objects.create(name='자유', description='자유')
        self.inquiry_cat = Category.objects.create(name='문의', description='문의')

    def _q(self, subject, category, **kw):
        return Question.objects.create(subject=subject, content='본문', author=self.author,
                                       category=category, create_date=timezone.now(), **kw)

    def test_locked_and_inquiry_posts_are_excluded(self):
        public = self._q('공개글', self.open_cat)
        self._q('회원전용', self.open_cat, is_locked=True)
        self._q('문의글', self.inquiry_cat)
        items = list(QuestionSitemap().items())
        self.assertEqual([q.id for q in items], [public.id])

    def test_deleted_posts_stay_excluded(self):
        self._q('삭제글', self.open_cat, is_deleted=True)
        self.assertEqual(list(QuestionSitemap().items()), [])

    def test_static_sitemap_has_no_login_required_pages(self):
        names = [name for name, _p, _c in StaticViewSitemap.PAGES]
        self.assertNotIn('community:guestbook_list', names)


class RobotsTxtTests(TestCase):
    """운영에서는 nginx 가 static/robots.txt 를 서빙한다 — 뷰와 파일이 갈라지면 안 된다."""

    def test_view_serves_the_same_file_nginx_serves(self):
        served = self.client.get('/robots.txt').content.decode('utf-8')
        self.assertEqual(served, ROBOTS_PATH.read_text(encoding='utf-8'))

    def test_crawl_wasting_paths_are_disallowed(self):
        served = self.client.get('/robots.txt').content.decode('utf-8')
        for path in ('/common/toggle-version/', '/guestbook/', '/common/login/'):
            self.assertIn(f'Disallow: {path}', served)

    def test_sitemap_is_advertised(self):
        self.assertIn('Sitemap: https://techchang.com/sitemap.xml',
                      self.client.get('/robots.txt').content.decode('utf-8'))
