"""직접 유입·세션 중복 방지·비방문 요청 제외를 검증해요."""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from common.visitor_tracking import VisitorTrackingMiddleware
from community.models import Category, DailyVisitor, PortfolioCollection, Question
from community.site_stats import CACHE_KEY

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'
HTML_ACCEPT = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'


class VisitorIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.defaults['HTTP_ACCEPT'] = HTML_ACCEPT
        author = User.objects.create_user(Question.BOT_USERNAME)
        category = Category.objects.create(name='HRD')
        self.question = Question.objects.create(
            author=author, category=category, subject='검색 유입 칼럼',
            content='본문', create_date=timezone.now(),
        )

    def count(self):
        row = DailyVisitor.objects.filter(date=timezone.localdate()).first()
        return row.visitor_count if row else 0

    def test_direct_column_then_other_pages_and_home_count_once(self):
        cache.set(CACHE_KEY, {'visitors_today': 0}, 60)
        response = self.client.get(reverse('community:detail', args=[self.question.pk]),
                                   HTTP_USER_AGENT=PC, HTTP_REFERER='https://www.google.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.count(), 1)
        self.assertIsNone(cache.get(CACHE_KEY))
        for path in ('/board/', '/games/', '/'):
            response = self.client.get(path, HTTP_USER_AGENT=PC)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.count(), 1)
        self.assertEqual(response.context['visitors_today'], 1)
        self.assertEqual(response.context['visitors_total'], '1')

    def test_home_first_shows_own_visit_on_pc_and_mobile(self):
        for expected, ua in enumerate((PC, MOBILE), start=1):
            response = Client(HTTP_ACCEPT=HTML_ACCEPT).get('/', HTTP_USER_AGENT=ua)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['visitors_today'], expected)
            self.assertEqual(response.context['visitors_total'], str(expected))
            self.assertEqual(self.count(), expected)

    def test_old_home_marker_is_preserved_without_double_count(self):
        DailyVisitor.objects.create(date=timezone.localdate(), visitor_count=8)
        session = self.client.session
        session[f'visited_{timezone.localdate()}'] = True
        session.save()
        self.client.get(reverse('community:detail', args=[self.question.pk]), HTTP_USER_AGENT=PC)
        self.assertEqual(self.count(), 8)

    def test_game_direct_entry_counts(self):
        response = self.client.get('/games/', HTTP_USER_AGENT=MOBILE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.count(), 1)

    def test_bot_home_is_not_counted_but_still_loads(self):
        response = self.client.get('/', HTTP_USER_AGENT='Googlebot/2.1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['visitors_today'], 0)
        self.assertEqual(self.count(), 0)

    def test_home_template_failure_is_not_counted(self):
        self.client.raise_request_exception = False
        with patch('django.template.response.TemplateResponse.render', side_effect=RuntimeError('render failed')):
            with self.assertLogs('django.request', level='ERROR'):
                response = self.client.get('/', HTTP_USER_AGENT=PC)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.count(), 0)


class VisitorFilterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.mw = VisitorTrackingMiddleware(lambda request: HttpResponse('본문'))

    def request(self, path='/98/', method='get', **headers):
        headers.setdefault('HTTP_ACCEPT', HTML_ACCEPT)
        req = getattr(self.factory, method)(path, HTTP_USER_AGENT=PC, **headers)
        req.session = {}
        return req

    def test_non_page_requests_do_not_create_visitors_or_session_markers(self):
        cases = [
            (self.request(method='post'), HttpResponse()),
            (self.request(method='head'), HttpResponse()),
            (self.request(), HttpResponse(status=302)),
            (self.request(), HttpResponse(status=403)),
            (self.request(), HttpResponse(status=404)),
            (self.request(), HttpResponse(status=500)),
            (self.request(), JsonResponse({'ok': True})),
            (self.request(), HttpResponse('User-agent: *', content_type='text/plain')),
            (self.request(), HttpResponse('<p>파일</p>', headers={'Content-Disposition': 'attachment'})),
        ]
        for path in ('/static/test.html', '/media/test.html', '/api/page/',
                     '/secret-control-panel/', '/lab/admin/', '/common/admin/monitor/'):
            cases.append((self.request(path), HttpResponse()))
        for headers in ({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                        {'HTTP_SEC_FETCH_DEST': 'empty'}, {'HTTP_SEC_FETCH_DEST': 'iframe'},
                        {'HTTP_PURPOSE': 'prefetch'}, {'HTTP_SEC_PURPOSE': 'prefetch;prerender'}):
            cases.append((self.request(**headers), HttpResponse()))
        for req, response in cases:
            with self.subTest(path=req.path, headers=dict(req.headers), status=response.status_code):
                self.mw.record_visit(req, response)
                self.assertFalse(req.session)
                self.assertFalse(DailyVisitor.objects.exists())

    def test_automated_agents_are_excluded(self):
        for ua in ('', 'Googlebot/2.1', 'bingbot/2.0', 'Yeti/1.1', 'Twitterbot',
                   'facebookexternalhit/1.1', 'curl/8.0', 'python-requests/2',
                   'HeadlessChrome/130', 'UptimeRobot/2.0'):
            with self.subTest(ua=ua):
                req = self.factory.get('/', HTTP_USER_AGENT=ua, HTTP_ACCEPT=HTML_ACCEPT)
                req.session = {}
                self.mw.record_visit(req, HttpResponse())
                self.assertFalse(req.session)
                self.assertFalse(DailyVisitor.objects.exists())

    def test_browser_user_agent_alone_does_not_make_a_collector_a_visit(self):
        for accept in ('', '*/*', 'application/json', 'text/html;q=0,*/*;q=1', 'text/html;q=invalid'):
            with self.subTest(accept=accept):
                req = self.request('/map/?q=AI', HTTP_ACCEPT=accept)
                self.mw.record_visit(req, HttpResponse())
                self.assertFalse(req.session)
                self.assertFalse(DailyVisitor.objects.exists())

    def test_real_browser_navigation_is_kept_including_legacy_and_in_app(self):
        for headers in ({}, {'HTTP_SEC_FETCH_MODE': 'navigate', 'HTTP_SEC_FETCH_DEST': 'document'},
                        {'HTTP_ACCEPT': 'application/xhtml+xml'}):
            with self.subTest(headers=headers):
                req = self.request('/map/?q=AI', **headers)
                self.mw.record_visit(req, HttpResponse())
                self.assertTrue(req.session.get(f'visited_{timezone.localdate()}'))
        self.assertEqual(DailyVisitor.objects.get().visitor_count, 3)

    def test_fetching_html_for_data_is_not_navigation(self):
        req = self.request('/map/', HTTP_SEC_FETCH_MODE='cors')
        self.mw.record_visit(req, HttpResponse())
        self.assertFalse(DailyVisitor.objects.exists())

    def test_new_automation_and_verification_agents_never_count_even_with_html_headers(self):
        for ua in ('-', 'Go-http-client/1.1', 'WebSiphon/next-0.1', 'sqlmap/1.9', 'Nuclei',
                   'meta-webindexer/1.1', 'meta-externalagent/1.1', 'ChatGPT-User/1.0',
                   'Claude-User/1.0', 'ExaUser/1.0', 'GoogleOther', 'axios/1.7',
                   'Mozilla/5.0 TechChangReleaseCheck', 'Mozilla/5.0 TechChang verification'):
            with self.subTest(ua=ua):
                req = self.factory.get('/', HTTP_USER_AGENT=ua, HTTP_ACCEPT=HTML_ACCEPT)
                req.session = {}
                self.mw.record_visit(req, HttpResponse())
                self.assertFalse(req.session)
                self.assertFalse(DailyVisitor.objects.exists())

    @override_settings(SCANNER_PATH_PATTERNS=[r'\.env', r'/\.git/'])
    def test_probe_paths_never_count_even_if_an_upstream_returns_html_200(self):
        middleware = VisitorTrackingMiddleware(lambda request: HttpResponse())
        for path in ('/.env', '/app/.env.production', '/%2egit/HEAD'):
            with self.subTest(path=path):
                req = self.request(path)
                middleware.record_visit(req, HttpResponse())
                self.assertFalse(req.session)
                self.assertFalse(DailyVisitor.objects.exists())

    def test_korean_midnight_starts_new_day_for_same_session(self):
        req = self.request()
        before = datetime(2026, 11, 16, 14, 59, tzinfo=dt_timezone.utc)
        after = before + timedelta(minutes=2)
        with timezone.override('Asia/Seoul'):
            with patch('django.utils.timezone.now', return_value=before):
                self.mw.record_visit(req, HttpResponse())
                self.mw.record_visit(req, HttpResponse())
            with patch('django.utils.timezone.now', return_value=after):
                self.mw.record_visit(req, HttpResponse())
        self.assertEqual(list(DailyVisitor.objects.order_by('date').values_list('visitor_count', flat=True)), [1, 1])
        self.assertEqual(req.session, {'visited_2026-11-17': True})

    def test_raw_portfolio_iframe_does_not_count_even_without_fetch_headers(self):
        from django.urls import resolve
        req = self.request('/portfolios/example/raw/')
        req.resolver_match = resolve(req.path)
        self.mw.record_visit(req, HttpResponse())
        self.assertFalse(DailyVisitor.objects.exists())


@override_settings(SITE_OWNER_USERNAME='owner')
class VisitorConsumerCompatibilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.defaults['HTTP_ACCEPT'] = HTML_ACCEPT
        self.today = timezone.localdate()
        DailyVisitor.objects.create(date=self.today - timedelta(days=1), visitor_count=1000)
        DailyVisitor.objects.create(date=self.today, visitor_count=234)
        self.owner = User.objects.create_user('owner')
        self.portfolio = PortfolioCollection.objects.create(
            user=self.owner, portfolio_name='문승현 포트폴리오', slug='owner-portfolio',
            is_published=True, approval_status='approved', content_mode='html',
            html_content='<b data-tc-stat="visitors_total">0</b><b data-tc-stat="visitors_today">0</b>',
        )

    def test_portfolio_outer_page_then_iframe_share_live_stats_without_double_count(self):
        from community import site_stats
        original = self.portfolio.html_content
        for ua in (PC, MOBILE):
            with self.subTest(ua=ua):
                client = Client(HTTP_ACCEPT=HTML_ACCEPT)
                expected = DailyVisitor.objects.get(date=self.today).visitor_count + 1
                # 이전 캐시를 읽은 상태에서도 새 방문 후 최신 통계를 받아야 해요.
                site_stats.stats()
                response = client.get(self.portfolio.get_absolute_url(), HTTP_USER_AGENT=ua)
                self.assertEqual(response.status_code, 200)
                for _ in range(2):
                    response = client.get(reverse('community:portfolio_collection_raw', args=[self.portfolio.slug]),
                                          HTTP_USER_AGENT=ua, HTTP_SEC_FETCH_DEST='iframe')
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f'data-tc-stat="visitors_today">{expected}</b>')
                    self.assertContains(response, f'data-tc-stat="visitors_total">{1000 + expected:,}</b>')
                home = client.get('/', HTTP_USER_AGENT=ua)
                self.assertEqual(home.context['visitors_today'], expected)
                self.assertEqual(DailyVisitor.objects.get(date=self.today).visitor_count, expected)
        self.portfolio.refresh_from_db()
        self.assertEqual(self.portfolio.html_content, original)

    def test_report_and_lab_consumers_read_same_table_after_direct_visit(self):
        from common.management.commands.send_log_report import Command as LogReport
        from common.management.commands.send_visitor_report import Command as VisitorReport
        from office.services import collect_site_snapshot
        self.client.get('/games/', HTTP_USER_AGENT=PC)
        weekly = VisitorReport()._collect('weekly')
        monthly = VisitorReport()._collect('monthly')
        self.assertEqual(weekly['cumulative'], 1235)
        self.assertEqual(monthly['cumulative'], 1235)
        self.assertEqual(weekly['yest_count'], 1000)
        report = LogReport()._collect_db_stats()
        self.assertEqual(report['visitors_today'], 235)
        self.assertEqual(report['visitors_yesterday'], 1000)
        with patch('office.services._collect_gsc', return_value={}), \
                patch('office.services._gsc_gaps', return_value={}), \
                patch('office.services._collect_server_log', return_value={}):
            snapshot = collect_site_snapshot()
        self.assertEqual(snapshot['visitors']['recent'], 1235)

    def test_server_report_visitors_use_korean_date_during_utc_previous_day(self):
        from common.management.commands.send_log_report import Command as LogReport
        DailyVisitor.objects.all().delete()
        DailyVisitor.objects.create(date=datetime(2026, 11, 17).date(), visitor_count=9)
        DailyVisitor.objects.create(date=datetime(2026, 11, 16).date(), visitor_count=7)
        with timezone.override('Asia/Seoul'), patch('django.utils.timezone.now', return_value=(
                datetime(2026, 11, 16, 15, 1, tzinfo=dt_timezone.utc))):
            report = LogReport()._collect_db_stats()
        self.assertEqual(report['visitors_today'], 9)
        self.assertEqual(report['visitors_yesterday'], 7)
