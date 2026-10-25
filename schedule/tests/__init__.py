"""schedule 모듈 테스트.

사이트에 연결하기 전(INSTALLED_APPS 에 없을 때)에는 사이트 CI 의 `manage.py test` 에서 통째로 건너뛴다.
모듈만 검증할 때:
    py -3.10 manage.py test schedule.tests --settings=schedule.testing.settings
"""
import unittest

from django.apps import apps

if not apps.is_installed('schedule'):
    raise unittest.SkipTest('schedule 앱이 INSTALLED_APPS 에 없어 건너뜀 '
                            '(단독 실행: manage.py test schedule.tests --settings=schedule.testing.settings)')
