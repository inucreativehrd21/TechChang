"""
모바일 자동 템플릿 로더

- request.is_mobile == True 일 때 templates 내 mobile/ 하위 경로를 먼저 탐색
- 예: community/question_form.html → community/mobile/question_form.html 우선 시도
- 없으면 기본 경로로 fallback
- 미들웨어가 설정한 thread-local로 request 접근
"""
import threading
from django.template.loaders.filesystem import Loader as FsLoader
from django.template.loaders.app_directories import Loader as AppLoader

_thread_local = threading.local()


def set_mobile_request(request):
    _thread_local.is_mobile = getattr(request, 'is_mobile', False)


def clear_mobile_request():
    _thread_local.is_mobile = False


def _is_mobile():
    return getattr(_thread_local, 'is_mobile', False)


def _to_mobile_path(template_name):
    """community/foo.html → community/mobile/foo.html"""
    parts = template_name.rsplit('/', 1)
    if len(parts) == 2:
        return f"{parts[0]}/mobile/{parts[1]}"
    return f"mobile/{template_name}"


class MobileFsLoader(FsLoader):
    """DIRS 기반 파일시스템 로더 (모바일 우선)"""

    def get_template(self, template_name, skip=None):
        if _is_mobile():
            mobile_name = _to_mobile_path(template_name)
            try:
                return super().get_template(mobile_name, skip=skip)
            except Exception:
                pass
        return super().get_template(template_name, skip=skip)


class MobileAppLoader(AppLoader):
    """앱 templates 디렉토리 로더 (모바일 우선)"""

    def get_template(self, template_name, skip=None):
        if _is_mobile():
            mobile_name = _to_mobile_path(template_name)
            try:
                return super().get_template(mobile_name, skip=skip)
            except Exception:
                pass
        return super().get_template(template_name, skip=skip)
