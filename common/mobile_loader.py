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
from django.template.loaders.cached import Loader as CachedLoader

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


class MobileCachedLoader(CachedLoader):
    """컴파일한 템플릿을 워커 메모리에 보관한다 — 로더를 직접 지정하면 Django 가 캐시 로더를 씌우지 않아
    요청마다 템플릿 파일을 다시 읽고 파싱했다.

    캐시 로더는 하위 로더의 get_template 을 거치지 않고 get_template_sources 만 쓰므로, 모바일 우선 탐색을
    여기서 같은 순서(로더마다 mobile/ 경로 → 기본 경로)로 만든다. 같은 이름도 PC·모바일 결과가 달라
    모바일 여부를 캐시 키에 넣는다.
    """

    def get_template_sources(self, template_name):
        mobile = _is_mobile()
        for loader in self.loaders:
            if mobile:
                yield from loader.get_template_sources(_to_mobile_path(template_name))
            yield from loader.get_template_sources(template_name)

    def cache_key(self, template_name, skip=None):
        # 기본 키는 skip 중 같은 이름의 원본만 본다. 모바일 판이 PC 판을 extends 하면 skip 에 mobile/ 원본이
        # 들어오므로 그 이름도 함께 봐야 같은 키로 자기 자신을 다시 받지 않는다.
        mobile = _is_mobile()
        names = {template_name, _to_mobile_path(template_name)} if mobile else {template_name}
        matching = [origin.name for origin in skip or () if origin.template_name in names]
        return '-'.join(s for s in ('m' if mobile else 'd', str(template_name),
                                    self.generate_hash(matching) if matching else '') if s)
