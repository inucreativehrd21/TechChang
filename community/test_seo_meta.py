"""글 단위 메타 태그·요약 회귀 테스트.

배경: question_detail.html 이 title 만 덮어쓰고 있어서 모든 칼럼이 base.html 의
사이트 기본 설명("테크창 - HRD & 테크놀로지 커뮤니티")을 공유했다. 검색결과에 같은
문구가 반복되면 CTR 이 떨어진다(2026-09 회의 안건 "제목·메타 설명 재작성으로 CTR 개선").
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question

SITE_DEFAULT = '테크창 - HRD & 테크놀로지 커뮤니티'


class SeoDescriptionTests(TestCase):
    def _q(self, content, subject='제목'):
        return Question(subject=subject, content=content)

    def test_markdown_syntax_is_stripped(self):
        q = self._q('## 머리말\n\n**굵게** 쓴 _문장_ 과 `코드` 입니다.')
        self.assertEqual(q.seo_description, '굵게 쓴 문장 과 코드 입니다.')

    def test_heading_is_skipped_so_it_does_not_repeat_the_title(self):
        q = self._q('# 같은 제목\n\n본문 첫 문장입니다.', subject='같은 제목')
        self.assertNotIn('같은 제목', q.seo_description)
        self.assertEqual(q.seo_description, '본문 첫 문장입니다.')

    def test_links_keep_text_and_images_are_dropped(self):
        q = self._q('![도표](/media/a.png)\n\n자세한 내용은 [공식 문서](https://x.example) 참고.')
        self.assertEqual(q.seo_description, '자세한 내용은 공식 문서 참고.')

    def test_code_block_is_dropped(self):
        q = self._q('```python\nprint("hi")\n```\n\n실제 설명 문장.')
        self.assertEqual(q.seo_description, '실제 설명 문장.')

    def test_tables_and_rules_are_skipped(self):
        q = self._q('| 항목 | 값 |\n|---|---|\n| a | 1 |\n\n---\n\n표 아래 설명.')
        self.assertEqual(q.seo_description, '표 아래 설명.')

    def test_long_text_is_truncated_with_ellipsis(self):
        q = self._q('가' * 400)
        desc = q.seo_description
        self.assertLessEqual(len(desc), 156)
        self.assertTrue(desc.endswith('…'))

    def test_empty_content_is_safe(self):
        self.assertEqual(self._q('').seo_description, '')


class QuestionDetailMetaTests(TestCase):
    def setUp(self):
        author = User.objects.create_user(Question.BOT_USERNAME, password='x')   # 연구팀 칼럼 → Article
        category = Category.objects.create(name='HRD', description='HRD')
        self.q = Question.objects.create(
            subject='스킬 인벤토리로 보는 인재 재배치', category=category, author=author,
            create_date=timezone.now(),
            content='# 머리말\n\n조직이 가진 역량을 수치로 관리하면 무엇이 달라지는지 살펴본다.')

    def test_page_has_its_own_description_not_the_site_default(self):
        html = self.client.get(f'/{self.q.id}/').content.decode('utf-8')
        self.assertIn('조직이 가진 역량을', html)
        self.assertNotIn(f'<meta name="description" content="{SITE_DEFAULT}">', html)

    def test_og_tags_use_the_post_title_and_article_type(self):
        html = self.client.get(f'/{self.q.id}/').content.decode('utf-8')
        self.assertIn(f'<meta property="og:title" content="{self.q.subject}">', html)
        self.assertIn('<meta property="og:type" content="article">', html)

    def test_jsonld_is_valid_article_schema(self):
        html = self.client.get(f'/{self.q.id}/').content.decode('utf-8')
        start = html.index('application/ld+json')
        block = html[html.index('>', start) + 1:html.index('</script>', start)]
        data = json.loads(block)          # 깨진 JSON 이면 여기서 실패한다
        self.assertEqual(data['@type'], 'Article')
        self.assertEqual(data['headline'], self.q.subject)
        self.assertEqual(data['articleSection'], 'HRD')

    def test_jsonld_survives_quotes_and_script_tags_in_the_title(self):
        self.q.subject = '"따옴표" 와 </script> 가 든 제목'
        self.q.save(update_fields=['subject'])
        html = self.client.get(f'/{self.q.id}/').content.decode('utf-8')
        start = html.index('application/ld+json')
        block = html[html.index('>', start) + 1:html.index('</script>', start)]
        self.assertEqual(json.loads(block)['headline'], self.q.subject)


MOBILE_BOT = ('Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130 Mobile Safari/537.36 (compatible; Googlebot/2.1)')


def jsonld_blocks(html):
    out, pos = [], 0
    while (start := html.find('application/ld+json', pos)) != -1:
        body = html[html.index('>', start) + 1:html.index('</script>', start)]
        out.append(json.loads(body))
        pos = start + 1
    return out


class MobileFirstIndexingTests(TestCase):
    """구글은 스마트폰 크롤러로 색인한다 — 모바일 화면에도 같은 검색엔진 머리말이 있어야 한다.
    (2026-10-09 GSC '표준이 없는 중복 페이지' 41건: 모바일 베이스에 canonical 이 없었다)"""

    def setUp(self):
        self.bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        self.member = User.objects.create_user('member', password='x')
        self.cat = Category.objects.create(name='HRD', description='HRD')
        self.column = Question.objects.create(subject='칼럼 제목', category=self.cat, author=self.bot,
                                              create_date=timezone.now(),
                                              content='첫 문단 요약입니다.' + chr(10) * 2 + '![차트](/media/c.png)')
        self.thin = Question.objects.create(subject='짧은 질문', category=self.cat, author=self.member,
                                            create_date=timezone.now(), content='이거 뭐예요?')

    def get(self, url, ua=MOBILE_BOT):
        return self.client.get(url, HTTP_USER_AGENT=ua)

    def test_mobile_detail_has_canonical_description_and_jsonld(self):
        html = self.get(f'/{self.column.id}/?sort=recommend').content.decode()
        self.assertIn(f'<link rel="canonical" href="https://techchang.com/{self.column.id}/">', html)
        self.assertIn('<meta name="description" content="첫 문단 요약입니다.">', html)
        types = [b['@type'] for b in jsonld_blocks(html)]
        self.assertIn('Article', types)
        self.assertIn('BreadcrumbList', types)
        article = next(b for b in jsonld_blocks(html) if b['@type'] == 'Article')
        self.assertEqual(article['image'], ['https://techchang.com/media/c.png'])
        self.assertEqual(article['author']['name'], '테크창 연구팀')

    def test_home_canonical_keeps_category_and_page_only(self):
        html = self.get('/?category=HRD&sort=popular&page=2').content.decode()
        self.assertIn('<link rel="canonical" href="https://techchang.com/?category=HRD&amp;page=2">', html)
        self.assertIn('content="index, follow"', html)

    def test_search_results_are_noindex(self):
        html = self.get('/?kw=HRD').content.decode()
        self.assertIn('<meta name="robots" content="noindex, follow">', html)

    def test_thin_member_post_is_noindex_but_column_is_indexed(self):
        for ua in (MOBILE_BOT, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'):
            self.assertIn('content="noindex, follow"', self.get(f'/{self.thin.id}/', ua).content.decode())
            self.assertIn('<meta name="robots" content="index, follow">',
                          self.get(f'/{self.column.id}/', ua).content.decode())

    def test_dynamic_serving_sends_vary_user_agent(self):
        self.assertIn('User-Agent', self.get('/')['Vary'])

    def test_sitemap_index_splits_sections_and_drops_thin_posts(self):
        index = self.client.get('/sitemap.xml').content.decode()
        for section in ('static', 'columns', 'series', 'posts', 'making', 'portfolios'):
            self.assertIn(f'/sitemap-{section}.xml', index)
        columns = self.client.get('/sitemap-columns.xml').content.decode()
        self.assertIn(f'https://techchang.com/{self.column.id}/', columns)
        posts = self.client.get('/sitemap-posts.xml').content.decode()
        self.assertNotIn(f'/{self.thin.id}/', posts)


class RssFeedTests(TestCase):
    def test_feed_lists_columns_only_with_summary_and_absolute_links(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        member = User.objects.create_user('member', password='x')
        cat = Category.objects.create(name='HRD', description='HRD')
        col = Question.objects.create(subject='칼럼 제목', category=cat, author=bot, create_date=timezone.now(),
                                      content='요약이 될 첫 문단입니다.' + chr(10) * 2 + '본문 둘째 문단은 피드에 없다.')
        Question.objects.create(subject='회원 글', category=cat, author=member, create_date=timezone.now(),
                                content='회원 본문 ' * 60)
        res = self.client.get('/rss.xml')
        self.assertEqual(res.status_code, 200)
        self.assertIn('application/rss+xml', res['Content-Type'])
        xml = res.content.decode()
        self.assertIn('<title>칼럼 제목</title>', xml)
        self.assertIn(f'<link>https://techchang.com/{col.id}/</link>', xml)
        self.assertIn('요약이 될 첫 문단입니다.', xml)
        self.assertNotIn('회원 글', xml)
        self.assertIn('/rss.xml', self.client.get('/').content.decode())   # 페이지 머리말에서 피드 자동 발견
