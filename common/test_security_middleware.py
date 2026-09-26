"""RequestLoggingMiddleware.is_suspicious_request 동작 검증.

- 응답 속도만으로는 의심 판정하지 않는다 (정적/캐시 응답 오탐 방지)
- /lab/state.json, /lab/admin/activity.json 같은 폴링 엔드포인트는
  빠른 응답이어도 경고를 만들지 않는다
- 404 / POST 403 / 비스태프의 Django 관리자(/admin/) 접근은 그대로 의심 판정한다
"""
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from common.middleware import RequestLoggingMiddleware


class IsSuspiciousRequestTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RequestLoggingMiddleware(get_response=lambda request: HttpResponse())

    def _request(self, path='/', method='GET'):
        req = getattr(self.factory, method.lower())(path)
        req.user = AnonymousUser()
        return req

    def test_fast_response_alone_is_not_suspicious(self):
        request = self._request('/')
        response = HttpResponse(status=200)
        self.assertFalse(self.middleware.is_suspicious_request(request, response, 0.01))

    def test_polling_endpoint_fast_response_is_not_suspicious(self):
        request = self._request('/lab/state.json')
        response = HttpResponse(status=200)
        self.assertFalse(self.middleware.is_suspicious_request(request, response, 0.02))

        request2 = self._request('/lab/admin/activity.json')
        response2 = HttpResponse(status=200)
        self.assertFalse(self.middleware.is_suspicious_request(request2, response2, 0.01))

    def test_sitemap_fast_response_is_not_suspicious(self):
        request = self._request('/sitemap.xml')
        response = HttpResponse(status=200)
        self.assertFalse(self.middleware.is_suspicious_request(request, response, 0.03))

    def test_404_is_suspicious(self):
        request = self._request('/does-not-exist')
        response = HttpResponse(status=404)
        self.assertTrue(self.middleware.is_suspicious_request(request, response, 0.5))

    def test_post_403_csrf_is_suspicious(self):
        request = self._request('/some-form/', method='POST')
        response = HttpResponse(status=403)
        self.assertTrue(self.middleware.is_suspicious_request(request, response, 0.5))

    def test_non_staff_django_admin_access_is_suspicious(self):
        request = self._request('/admin/')
        response = HttpResponse(status=200)
        self.assertTrue(self.middleware.is_suspicious_request(request, response, 0.5))

    def test_staff_django_admin_access_is_not_suspicious(self):
        request = self._request('/admin/')
        request.user = SimpleNamespace(is_staff=True)
        response = HttpResponse(status=200)
        self.assertFalse(self.middleware.is_suspicious_request(request, response, 0.5))

    def test_app_internal_admin_path_is_not_treated_as_django_admin(self):
        # /lab/admin/... 은 Django 관리자와 무관한 앱 내부 경로 — 오탐 금지
        request = self._request('/lab/admin/')
        response = HttpResponse(status=200)
        self.assertFalse(self.middleware.is_suspicious_request(request, response, 0.5))