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
        author = User.objects.create_user('writer', password='x')
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
