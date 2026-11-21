"""그림 경로와 도감 공개 상태가 실제 납품 자산과 맞는지 확인해요."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from community import samguk_data as D, samguk_legends as L
from community.templatetags.samguk_art import _portrait, sg_portrait


class SamgukArtTests(SimpleTestCase):
    def test_every_catalog_character_resolves_to_existing_portrait(self):
        folder = Path(settings.BASE_DIR) / 'static/samguk/officer'
        for code in set(D.GENERAL) | set(L.HIDDEN):
            art, name = _portrait(code)
            self.assertTrue(name, code)
            for size in ['', '160']:
                self.assertTrue((folder / size / f'{art}.webp').is_file(), code)

    def test_unknown_card_does_not_disclose_portrait_or_name(self):
        markup = str(sg_portrait('diaochan', 'unknown'))
        self.assertIn('_unknown.webp', markup)
        self.assertNotIn('diaochan', markup)
        self.assertNotIn('초선', markup)

    def test_female_and_hidden_portraits_are_distinct_assets(self):
        for code in ['daqiao', 'xiaoqiao', 'zhenji', 'diaochan', 'huangyueying', 'zhurong', 'himiko']:
            self.assertEqual(_portrait(code)[0], code)
