"""캐시 템플릿 로더가 PC·모바일 판을 섞지 않는지 확인한다."""
import tempfile
from pathlib import Path

from django.template import engines
from django.test import SimpleTestCase, override_settings

from common.mobile_loader import clear_mobile_request, set_mobile_request


class _Req:
    def __init__(self, is_mobile):
        self.is_mobile = is_mobile


class MobileCachedLoaderTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'x' / 'mobile').mkdir(parents=True)
        (root / 'x' / 'page.html').write_text('desktop', encoding='utf-8')
        (root / 'x' / 'mobile' / 'page.html').write_text('mobile', encoding='utf-8')
        (root / 'x' / 'only.html').write_text('only', encoding='utf-8')
        # 모바일 판이 같은 이름의 PC 판을 이어받는 경우(자기 자신 재귀가 나면 안 된다)
        (root / 'x' / 'wrap.html').write_text('[{% block b %}pc{% endblock %}]', encoding='utf-8')
        (root / 'x' / 'mobile' / 'wrap.html').write_text(
            "{% extends 'x/wrap.html' %}{% block b %}m{% endblock %}", encoding='utf-8')
        templates = [{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [str(root)], 'APP_DIRS': False,
            'OPTIONS': {'loaders': [('common.mobile_loader.MobileCachedLoader', [
                'common.mobile_loader.MobileFsLoader', 'common.mobile_loader.MobileAppLoader'])]},
        }]
        self.override = override_settings(TEMPLATES=templates)
        self.override.enable()
        self.engine = engines['django']

    def tearDown(self):
        clear_mobile_request()
        self.override.disable()
        self.tmp.cleanup()

    def render(self, name, mobile):
        set_mobile_request(_Req(mobile))
        try:
            return self.engine.get_template(name).render({})
        finally:
            clear_mobile_request()

    def test_desktop_and_mobile_cached_separately(self):
        for _ in range(2):   # 두 번째는 캐시 적중
            self.assertEqual(self.render('x/page.html', False), 'desktop')
            self.assertEqual(self.render('x/page.html', True), 'mobile')

    def test_mobile_falls_back_to_desktop_template(self):
        self.assertEqual(self.render('x/only.html', True), 'only')

    def test_mobile_template_can_extend_same_desktop_name(self):
        self.assertEqual(self.render('x/wrap.html', True), '[m]')
        self.assertEqual(self.render('x/wrap.html', True), '[m]')
        self.assertEqual(self.render('x/wrap.html', False), '[pc]')

    def test_compiled_template_is_reused(self):
        self.render('x/page.html', False)
        loader = self.engine.engine.template_loaders[0]
        cached = dict(loader.get_template_cache)
        self.render('x/page.html', False)
        self.assertEqual(cached, loader.get_template_cache)
        self.assertTrue(any(k.startswith('d-x/page.html') for k in cached))
