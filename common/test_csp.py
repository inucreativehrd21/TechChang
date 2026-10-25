"""CSP 단계적 적용 검증.

- 템플릿의 nonce="{{ csp_nonce }}" 와 헤더의 'nonce-…' 가 같은 값이다(theme_context 가 만든 값을 django-csp 가 쓴다)
- /csp-report/ 는 두 보고 형식을 받아 같은 위반을 한 번만 로그에 남기고, IP 당 상한을 넘으면 버린다
- 보고 요청은 SecurityMiddleware 의 요청 수 집계에서 빠진다(정상 사용자 차단 방지)
"""
import json
import re

from csp.constants import NONCE, SELF
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from common import csp as csp_module
from common.middleware import SecurityMiddleware

REPORT_ONLY_POLICY = {
    'DIRECTIVES': {
        'default-src': [SELF],
        'script-src': [SELF, NONCE],
        'report-uri': ['/csp-report/'],
    },
}


def _legacy_report(directive='script-src-elem', blocked='inline', page='https://techchang.com/board/?token=secret'):
    return json.dumps({'csp-report': {
        'document-uri': page,
        'effective-directive': directive,
        'blocked-uri': blocked,
        'source-file': 'https://techchang.com/board/',
        'line-number': 120,
    }})


class CspHeaderNonceTests(TestCase):
    @override_settings(CONTENT_SECURITY_POLICY_REPORT_ONLY=REPORT_ONLY_POLICY, CONTENT_SECURITY_POLICY=None)
    def test_header_nonce_matches_template_nonce(self):
        response = self.client.get('/terms/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(response.status_code, 200)
        header = response.get('Content-Security-Policy-Report-Only', '')
        self.assertIn("'self'", header)
        header_nonce = re.search(r"'nonce-([^']+)'", header)
        self.assertIsNotNone(header_nonce, header)
        page_nonces = set(re.findall(r'nonce="([^"]+)"', response.content.decode()))
        self.assertTrue(page_nonces, '페이지에 nonce 속성이 없음')
        self.assertEqual(page_nonces, {header_nonce.group(1)})
        self.assertNotIn('Content-Security-Policy', {k for k in response.headers if k == 'Content-Security-Policy'})

    @override_settings(CONTENT_SECURITY_POLICY_REPORT_ONLY=None, CONTENT_SECURITY_POLICY=None)
    def test_no_policy_means_no_header(self):
        response = self.client.get('/terms/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertNotIn('Content-Security-Policy-Report-Only', response.headers)
        self.assertNotIn('Content-Security-Policy', response.headers)


class CspReportEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def _post(self, body, content_type='application/csp-report', ip='203.0.113.7'):
        return self.client.post('/csp-report/', data=body, content_type=content_type,
                                REMOTE_ADDR=ip, HTTP_USER_AGENT='Mozilla/5.0')

    def test_legacy_report_is_logged_once_and_strips_query(self):
        with self.assertLogs('security.csp', level='WARNING') as logs:
            self.assertEqual(self._post(_legacy_report()).status_code, 204)
            self.assertEqual(self._post(_legacy_report()).status_code, 204)   # 같은 위반 → 로그 생략
        self.assertEqual(len(logs.output), 1)
        self.assertIn('directive=script-src-elem', logs.output[0])
        self.assertIn('page=https://techchang.com/board/', logs.output[0])
        self.assertNotIn('secret', logs.output[0])

    def test_reporting_api_format(self):
        body = json.dumps([{'type': 'csp-violation', 'url': 'https://techchang.com/',
                            'body': {'effectiveDirective': 'script-src-attr', 'blockedURL': 'inline',
                                     'documentURL': 'https://techchang.com/', 'lineNumber': 9}}])
        with self.assertLogs('security.csp', level='WARNING') as logs:
            self.assertEqual(self._post(body, 'application/reports+json').status_code, 204)
        self.assertIn('directive=script-src-attr', logs.output[0])

    def test_garbage_and_oversized_bodies_are_ignored(self):
        self.assertEqual(self._post('not json').status_code, 204)
        big = json.dumps({'csp-report': {'blocked-uri': 'x' * (csp_module.MAX_BODY_BYTES + 10)}})
        self.assertEqual(self._post(big).status_code, 204)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get('/csp-report/', HTTP_USER_AGENT='Mozilla/5.0').status_code, 405)

    def test_per_ip_limit_drops_excess_reports(self):
        for i in range(csp_module.PER_IP_LIMIT):
            self._post(_legacy_report(blocked=f'https://evil.example/{i}.js'))
        with self.assertNoLogs('security.csp', level='WARNING'):
            self._post(_legacy_report(blocked='https://evil.example/over-limit.js'))


class CspReportRateLimitExemptionTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(RATE_LIMIT_REQUESTS=3, DDOS_THRESHOLD=3)
    def test_report_path_does_not_count_toward_rate_limit(self):
        middleware = SecurityMiddleware(get_response=lambda request: HttpResponse())
        factory = RequestFactory()
        for _ in range(10):
            request = factory.post('/csp-report/', REMOTE_ADDR='198.51.100.4', HTTP_USER_AGENT='Mozilla/5.0')
            self.assertIsNone(middleware.check_security(request))
        # 일반 경로는 여전히 한도가 적용된다
        responses = [middleware.check_security(factory.get('/', REMOTE_ADDR='198.51.100.4',
                                                           HTTP_USER_AGENT='Mozilla/5.0')) for _ in range(5)]
        self.assertTrue(any(r is not None and r.status_code in (403, 429) for r in responses))
