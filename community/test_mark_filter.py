"""본문 마크다운 필터 — 결과를 캐시해도 XSS 정화가 그대로인지 확인한다."""
from django.test import SimpleTestCase

from community.templatetags.pybo_filter import _render_markdown, mark


class MarkFilterTests(SimpleTestCase):
    def setUp(self):
        _render_markdown.cache_clear()

    def test_sanitizes_on_first_and_cached_render(self):
        src = '**굵게**\n\n<script>alert(1)</script><img src=x onerror=alert(1)>'
        for _ in range(2):
            html = mark(src)
            self.assertIn('<strong>굵게</strong>', html)
            self.assertNotIn('<script', html)
            self.assertNotIn('onerror', html)
        self.assertEqual(_render_markdown.cache_info().hits, 1)

    def test_changed_source_renders_again(self):
        self.assertIn('하나', mark('하나'))
        self.assertIn('둘', mark('둘'))
        self.assertNotIn('하나', mark('둘'))
        self.assertEqual(_render_markdown.cache_info().misses, 2)
