"""사이트 주인 — 구성원 목록 첫 자리, 주인의 HTML 포트폴리오만 최신 사이트 통계를 받는다(community.site_stats)."""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from community import site_stats
from community.models import Category, DailyVisitor, PortfolioCollection, Question

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'
STAT_HTML = ('<html><body><p>운영 <span class="n" data-tc-stat="launch_days">376</span>일 · '
             '누적 <b data-tc-stat="visitors_total">31,789</b> · 칼럼 <span data-tc-stat="lab_columns">63</span>편 · '
             '<span data-tc-stat="as_of">2026.10.12</span> 기준 · <span data-tc-stat="secret_key">x</span></p></body></html>')


def collection(user, name, **kw):
    kw.setdefault('is_published', True)
    kw.setdefault('approval_status', 'approved')
    return PortfolioCollection.objects.create(
        user=user, portfolio_name=name, slug=f'{user.username}-{name}',
        display_name=kw.pop('display_name', user.username), **kw)


@override_settings(SITE_OWNER_USERNAME='owner')
class OwnerFirstInMembersTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='x')
        others = [User.objects.create_user(f'm{i}', password='x') for i in range(3)]
        self.own = collection(self.owner, 'main', display_name='문승현')
        for u in others:
            collection(u, 'pf')            # 주인보다 나중에 고친 글 — 예전 정렬이면 주인보다 앞에 온다

    def test_owner_takes_first_slot_once_on_pc_and_mobile(self):
        for ua in (PC, MOBILE):
            r = self.client.get(reverse('community:members_list'), HTTP_USER_AGENT=ua)
            html = r.content.decode()
            self.assertEqual(r.context['owner_collection'], self.own)
            self.assertNotIn(self.own, list(r.context['collections']))
            self.assertEqual(html.count(f'/portfolios/{self.own.slug}/'), 1)
            first_card = html.index('/portfolios/')
            self.assertIn(self.own.slug, html[first_card:first_card + 80])   # 첫 카드가 주인
            self.assertIn('운영자', html)
        self.assertEqual(r.context['member_total'], 4)

    def test_main_portfolio_is_preferred(self):
        main = collection(self.owner, 'second', is_main=True)
        r = self.client.get(reverse('community:members_list'), HTTP_USER_AGENT=PC)
        self.assertEqual(r.context['owner_collection'], main)
        self.assertIn(self.own, list(r.context['collections']))    # 다른 하나는 일반 목록에


@override_settings(SITE_OWNER_USERNAME='owner')
class OwnerLiveStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        cat = Category.objects.create(name='HRD')
        for i in range(2):
            Question.objects.create(author=bot, category=cat, subject=f'칼럼{i}', content='본문', create_date=timezone.now())
        DailyVisitor.objects.create(date=timezone.localdate() - timedelta(days=1), visitor_count=1000)
        DailyVisitor.objects.create(date=timezone.localdate(), visitor_count=234)
        self.owner = User.objects.create_user('owner', password='x')
        self.member = User.objects.create_user('member', password='x')

    def raw(self, c):
        return self.client.get(reverse('community:portfolio_collection_raw', args=[c.slug]), HTTP_USER_AGENT=PC).content.decode()

    def test_owner_portfolio_gets_live_values(self):
        html = self.raw(collection(self.owner, 'pf', content_mode='html', html_content=STAT_HTML))
        self.assertIn(f'data-tc-stat="launch_days">{site_stats.launch_days()}</span>', html)
        self.assertIn('data-tc-stat="visitors_total">1,234</b>', html)
        self.assertIn('data-tc-stat="lab_columns">2</span>', html)
        self.assertIn(f'data-tc-stat="as_of">{timezone.localdate():%Y.%m.%d}</span>', html)
        self.assertIn('data-tc-stat="secret_key">x</span>', html)          # 모르는 키는 그대로

    def test_columns_and_series_episodes_are_counted_apart(self):
        from community.models import ColumnSeries
        q = Question.objects.filter(author__username=Question.BOT_USERNAME).first()
        q.series = ColumnSeries.objects.create(slug='django', title='장고', category=q.category)
        q.episode_number = 1
        q.save()
        html = self.raw(collection(self.owner, 'pf', content_mode='html', html_content=(
            '<p><b data-tc-stat="lab_essays">0</b>·<b data-tc-stat="lab_episodes">0</b>·'
            '<b data-tc-stat="visitors_today">0</b></p>')))
        self.assertIn('data-tc-stat="lab_essays">1</b>', html)
        self.assertIn('data-tc-stat="lab_episodes">1</b>', html)
        self.assertIn('data-tc-stat="visitors_today">234</b>', html)

    def test_other_members_html_is_left_as_uploaded(self):
        html = self.raw(collection(self.member, 'pf', content_mode='html', html_content=STAT_HTML))
        self.assertIn('data-tc-stat="visitors_total">31,789</b>', html)
        self.assertIn('data-tc-stat="launch_days">376</span>', html)

    def test_homepage_uses_the_same_numbers(self):
        r = self.client.get('/', HTTP_USER_AGENT=PC)
        self.assertEqual(r.context['launch_days'], site_stats.launch_days())
        self.assertEqual(r.context['visitors_total'], f'{site_stats.visitors_total():,}')
        self.assertEqual(site_stats.launch_days(date(2025, 10, 1)), 0)


class AdminSelfApprovalTests(TestCase):
    """관리자는 자기 포트폴리오를 고쳐도 내려가지 않고, 게시 요청은 바로 공개된다. 일반 회원은 예전대로."""

    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'b@x.com', 'x')
        self.member = User.objects.create_user('member', password='x')
        self.member.profile.is_email_verified = True
        self.member.profile.save()

    def publish(self, c):
        return self.client.post(reverse('community:portfolio_collection_publish', args=[c.slug]), HTTP_USER_AGENT=PC)

    def test_admin_publish_request_goes_live_at_once(self):
        c = collection(self.admin, 'pf', approval_status='draft', is_published=False)
        self.client.login(username='boss', password='x')
        self.publish(c)
        c.refresh_from_db()
        self.assertEqual((c.approval_status, c.is_published, c.reviewed_by), ('approved', True, self.admin))

    def test_member_publish_request_still_waits_for_review(self):
        c = collection(self.member, 'pf', approval_status='draft', is_published=False)
        self.client.login(username='member', password='x')
        self.publish(c)
        c.refresh_from_db()
        self.assertEqual((c.approval_status, c.is_published), ('pending', False))

    def test_admin_edit_keeps_approval_but_member_edit_resets_it(self):
        from django.test import RequestFactory
        from community.views.portfolio_views import _reset_approval_on_change
        for user, expect in ((self.admin, ('approved', True)), (self.member, ('draft', False))):
            c = collection(user, 'edit')
            req = RequestFactory().post('/')
            req.user = user
            req._messages = type('M', (), {'add': lambda *a, **k: None})()
            _reset_approval_on_change(c, req)
            c.refresh_from_db()
            self.assertEqual((c.approval_status, c.is_published), expect)
