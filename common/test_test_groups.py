"""scripts/test_groups.py — 묶음이 모든 테스트 모듈을 빠짐없이·겹침 없이 나누는지, 경로 규칙이 맞는지."""
import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

_spec = importlib.util.spec_from_file_location(
    'test_groups', Path(__file__).resolve().parent.parent / 'scripts' / 'test_groups.py')
TG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TG)


class TestGroupsTests(SimpleTestCase):
    def test_groups_cover_every_test_module_once(self):
        every = sorted('.'.join(p.relative_to(TG.ROOT).with_suffix('').parts)
                       for app in ('common', 'community', 'office') for p in TG.ROOT.glob(f'{app}/test*.py'))
        grouped = [m for g in TG.GROUPS for m in TG.labels(g)]
        self.assertEqual(sorted(grouped), every)        # 빠짐도 겹침도 없다

    def test_security_modules_stay_in_security_group(self):
        sec = TG.labels('security')
        self.assertIn('common.test_security_middleware', sec)
        self.assertIn('community.test_media_security', sec)
        self.assertNotIn('community.test_media_security', TG.labels('community'))

    def test_path_rules(self):
        cases = {
            'community/views/rookie_lite_views.py': 'rookie',
            'templates/community/samguk/board.html': 'samguk',
            'office/views.py': 'lab',
            'common/views.py': 'security',
            'community/views/base_views.py': 'community',
            'common/middleware.py': 'all',
            'config/settings/base.py': 'all',
            'docs/lab-handoff.md': None,
            'static/css/home.css': None,
        }
        for path, group in cases.items():
            self.assertEqual(TG.group_for(path), group, path)
