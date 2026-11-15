"""표시 이름 주소·기존 링크·공개 범위와 구성원 메뉴를 확인해요."""
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from community.models import Portfolio, PortfolioCollection
from community.portfolio_urls import public_portfolio_urls
from community.sitemaps import PortfolioCollectionSitemap

PC = 'Mozilla/5.0 Windows Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone) Mobile'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PortfolioAddressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('raw-user')
        self.collection = PortfolioCollection.objects.create(
            user=self.user, portfolio_name='sequence', slug='raw-user-sequence-portfolio',
            display_name='문승현', content_mode='html', html_content='<html><body>공개 원본</body></html>',
            is_main=True, is_published=True, approval_status='approved',
        )

    def test_public_address_uses_portfolio_display_name(self):
        url = self.collection.get_absolute_url()
        self.assertEqual(unquote(url), '/portfolios/문승현/')
        response = self.client.get(url, HTTP_USER_AGENT=PC)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'/portfolios/{self.collection.slug}/raw/')
        self.assertContains(response, '문승현의 포트폴리오')

    def test_old_address_redirects_once_and_preserves_query(self):
        old = reverse('community:portfolio_collection_detail', args=[self.collection.slug])
        result = self.client.get(old + '?source=share', HTTP_USER_AGENT=PC)
        self.assertRedirects(result, self.collection.get_absolute_url() + '?source=share',
                             status_code=301, fetch_redirect_response=False)
        self.assertEqual(self.client.get(result.url, HTTP_USER_AGENT=PC).status_code, 200)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.slug, 'raw-user-sequence-portfolio')

    def test_member_cards_and_sitemap_share_canonical_address(self):
        for ua in (PC, MOBILE):
            response = self.client.get('/members/', HTTP_USER_AGENT=ua)
            self.assertContains(response, 'href="' + self.collection.get_absolute_url() + '"')
            self.assertNotContains(response, 'href="/portfolios/' + self.collection.slug + '/"')
        sitemap = PortfolioCollectionSitemap()
        self.assertEqual(sitemap.location(list(sitemap.items())[0]), self.collection.get_absolute_url())

    def test_namesakes_get_distinct_non_raw_addresses(self):
        another = PortfolioCollection.objects.create(
            user=User.objects.create_user('another-raw-user'), portfolio_name='other', slug='another-raw',
            display_name='문승현', is_main=True, is_published=True, approval_status='approved',
        )
        first, second = self.collection.get_absolute_url(), another.get_absolute_url()
        self.assertEqual(unquote(first), '/portfolios/문승현/')
        self.assertEqual(unquote(second), f'/portfolios/문승현-{another.pk}/')
        self.assertEqual(len(set(public_portfolio_urls().values())), 2)
        self.assertEqual(self.client.get(second, HTTP_USER_AGENT=PC).context['portfolio'], another)

    def test_names_cannot_take_over_an_existing_private_slug(self):
        private = PortfolioCollection.objects.create(
            user=User.objects.create_user('private-owner'), portfolio_name='private', slug='문승현',
            display_name='비공개 이름', is_published=False, approval_status='draft',
        )
        self.assertNotEqual(self.collection.get_absolute_url(), private.get_absolute_url())
        self.assertEqual(self.client.get(private.get_absolute_url(), HTTP_USER_AGENT=PC).status_code, 403)
        response = self.client.get(self.collection.get_absolute_url(), HTTP_USER_AGENT=PC)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['portfolio'], self.collection)

    def test_nonpublic_content_keeps_original_access_control_and_address(self):
        self.collection.is_published = False
        self.collection.save(update_fields=['is_published'])
        self.assertEqual(self.collection.get_absolute_url(), reverse(
            'community:portfolio_collection_detail', args=[self.collection.slug]))
        self.assertEqual(self.client.get('/portfolios/문승현/', HTTP_USER_AGENT=PC).status_code, 404)
        self.assertEqual(self.client.get(self.collection.get_absolute_url(), HTTP_USER_AGENT=PC).status_code, 403)

    def test_legacy_portfolio_uses_the_same_public_address_pattern(self):
        member = User.objects.create_user('legacy-user')
        portfolio = Portfolio.objects.create(user=member, display_name='최한빈', is_public=True, approval_status='approved')
        self.assertEqual(unquote(portfolio.get_absolute_url()), '/portfolios/최한빈/')
        response = self.client.get(reverse('community:portfolio_view', args=[member.pk]), HTTP_USER_AGENT=PC)
        self.assertRedirects(response, portfolio.get_absolute_url(), status_code=301, fetch_redirect_response=False)
        self.assertEqual(self.client.get(portfolio.get_absolute_url(), HTTP_USER_AGENT=PC).context['portfolio'], portfolio)

    def test_reserved_route_names_do_not_shadow_portfolio_creation(self):
        self.collection.display_name = 'create'
        self.collection.save(update_fields=['display_name'])
        url = self.collection.get_absolute_url()
        self.assertNotEqual(url, '/portfolios/create/')
        self.assertEqual(self.client.get(url, HTTP_USER_AGENT=PC).status_code, 200)

    def test_old_raw_html_route_retains_sandbox_and_noindex_headers(self):
        response = self.client.get(reverse('community:portfolio_collection_raw', args=[self.collection.slug]), HTTP_USER_AGENT=PC)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '공개 원본')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertIn("default-src 'none'", response['Content-Security-Policy'])

    def test_members_is_directly_accessible_from_primary_navigation(self):
        pc = self.client.get('/', HTTP_USER_AGENT=PC)
        self.assertContains(pc, 'href="/members/" class="premium-nav-link">구성원</a>')
        mobile = self.client.get('/', HTTP_USER_AGENT=MOBILE)
        self.assertContains(mobile, '<span>구성원</span>')
        self.assertContains(mobile, 'grid-template-columns: repeat(6, 1fr)')
