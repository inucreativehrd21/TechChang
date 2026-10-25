"""공개 검색 경계와 PC·모바일 운영 페이지의 회귀 검사예요."""
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from common.context_processors import seo
from .models import Category, Question
from .sitemaps import StaticViewSitemap

PC='Mozilla/5.0 Windows NT 10.0 Chrome/130'
MOBILE='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


class SearchBoundaryTests(SimpleTestCase):
    def result(self,path,user=False,session=None):
        from types import SimpleNamespace
        request=RequestFactory().get(path)
        request.user=SimpleNamespace(is_authenticated=user)
        request.session=session or {}
        return seo(request)

    def test_personal_and_combination_pages_are_noindex(self):
        for path in ('/rookie/world/?lg=mlb','/rookie/lite/world/','/rookie/extreme/world/',
                     '/rookie/report/','/rookie/lite/cards/','/rookie/extreme/lab/',
                     '/rookie/p/3/','/rookie/lite/c/3/','/common/connections/','/lab/job/test/'):
            self.assertEqual(self.result(path)['seo_robots'],'noindex, follow',path)

    def test_anonymous_landings_are_indexable_but_own_progress_is_not(self):
        for path in ('/rookie/','/rookie/lite/','/rookie/extreme/'):
            self.assertEqual(self.result(path)['seo_robots'],'index, follow')
            self.assertEqual(self.result(path,user=True)['seo_robots'],'noindex, follow')
        self.assertEqual(self.result('/rookie/extreme/',session={'extreme_guest':'owned'})['seo_robots'],'noindex, follow')

    def test_public_rankings_are_indexable_and_canonical_has_no_filter(self):
        for path in ('/common/points/ranking/','/rookie/lite/hall/?lg=mlb&role=pitcher','/rookie/extreme/today/'):
            result=self.result(path)
            self.assertEqual(result['seo_robots'],'index, follow')
            self.assertNotIn('?',result['canonical_url'])


@override_settings(ROOKIE_EXTREME_ENABLED=True,ROOKIE_EXTREME_PREVIEW=False)
class OperationsPageTests(TestCase):
    def setUp(self):
        self.client=Client(HTTP_USER_AGENT=PC)

    def test_sitemap_contains_all_public_game_routes_and_no_private_state(self):
        page=self.client.get('/sitemap-static.xml')
        self.assertEqual(page.status_code,200)
        for name,_,_ in StaticViewSitemap().items():
            from django.urls import reverse
            url=reverse(name)
            self.assertContains(page,'https://techchang.com'+url)
            self.assertEqual(self.client.get(url).status_code,200,url)
        for path in ('/rookie/world/','/rookie/report/','/rookie/extreme/lab/','/common/connections/'):
            self.assertNotContains(page,'https://techchang.com'+path)

    def test_extreme_flag_controls_xml_and_html_entries(self):
        for enabled in (True,False,True):
            with override_settings(ROOKIE_EXTREME_ENABLED=enabled):
                for path in ('/sitemap-static.xml','/sitemap/'):
                    response=self.client.get(path)
                    self.assertEqual('/rookie/extreme/' in response.content.decode(),enabled,path)

    def test_human_sitemap_has_friendly_labels_and_mobile_base(self):
        for ua in (PC,MOBILE):
            response=Client(HTTP_USER_AGENT=ua).get('/sitemap/')
            self.assertContains(response,'칼럼 지도')
            self.assertContains(response,'익스트림 모드')
            self.assertContains(response,'연구실 위클리')
            self.assertNotContains(response,'community:column_map')
            self.assertContains(response,'css/sitemap.css')
            if ua==MOBILE:self.assertTemplateUsed(response,'community/mobile/sitemap_page.html')

    def test_shared_game_metadata_preserves_logo_and_mode_description(self):
        for ua in (PC,MOBILE):
            response=Client(HTTP_USER_AGENT=ua).get('/rookie/extreme/')
            self.assertContains(response,'전용 이벤트 12종')
            self.assertContains(response,'property="og:title" content="야구선수 키우기 익스트림 모드')
            self.assertContains(response,'techchang-share-logo.png')
            self.assertContains(response,'<link rel="canonical" href="https://techchang.com/rookie/extreme/">')
            self.assertContains(Client(HTTP_USER_AGENT=ua).get('/games/'),'야구선수 키우기 세 모드')

    def test_locked_column_is_absent_from_post_and_making_sitemaps(self):
        from office.models import ColumnDraft
        author=User.objects.create_user(Question.BOT_USERNAME)
        cat=Category.objects.create(name='HRD')
        q=Question.objects.create(author=author,category=cat,subject='회원 전용 원고',content='내용 '*100,
                                  create_date=timezone.now(),is_locked=True)
        ColumnDraft.objects.create(topic='hrd',status='published',question=q)
        self.assertNotContains(self.client.get('/sitemap-columns.xml'),f'https://techchang.com/{q.pk}/')
        self.assertNotContains(self.client.get('/sitemap-making.xml'),f'/lab/making/{q.pk}/')

    def test_robots_keeps_public_games_crawlable_and_auth_paths_restricted(self):
        text=self.client.get('/robots.txt').content.decode()
        for path in ('/common/google/','/common/kakao/','/common/connections/','/lab/job/','/rookie/extreme/lab/'):
            self.assertIn('Disallow: '+path,text)
        self.assertNotIn('Disallow: /rookie/\n',text)
        self.assertNotIn('Disallow: /rookie/world/',text)
        self.assertIn('Sitemap: https://techchang.com/sitemap.xml',text)
