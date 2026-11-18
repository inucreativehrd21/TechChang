"""정상 HTML 방문을 한국 시간 기준 세션당 하루 한 번 집계해요."""
import re
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from community.models import DailyVisitor


class VisitorTrackingMiddleware:
    # 검색엔진의 크롤링 허용 여부와 방문자 통계 포함 여부는 별개예요.
    AUTOMATED_AGENT = re.compile(
        r'bot|crawler|spider|scraper|slurp|yeti|facebookexternalhit|'
        r'curl|wget|python|httpx|headless|uptime|monitor|healthcheck|'
        r'Go-http-client|Apache-HttpClient|aiohttp|node-fetch|axios|libwww|okhttp|'
        r'zgrab|masscan|nmap|nikto|sqlmap|gobuster|dirbuster|nuclei|WebSiphon|'
        r'meta-(?:externalagent|externalfetcher|webindexer)|'
        r'ChatGPT-User|Claude-User|ExaUser|GoogleOther|Google-InspectionTool|'
        r'TechChang(?:ReleaseCheck|[ -](?:release|verification|approval))|'
        r'Chrome Privacy Preserving Prefetch Proxy', re.I,
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self.excluded_prefixes = tuple(dict.fromkeys((
            '/static/', '/media/', '/api/', '/admin/', '/common/admin/', '/lab/admin/',
            '/' + getattr(settings, 'ADMIN_URL', 'secret-control-panel/').strip('/') + '/',
            urlsplit(settings.STATIC_URL).path or '/static/',
            urlsplit(settings.MEDIA_URL).path or '/media/',
        )))
        self.scanner_patterns = [re.compile(pattern, re.I) for pattern in
                                 getattr(settings, 'SCANNER_PATH_PATTERNS', ())]

    def __call__(self, request):
        response = self.get_response(request)
        self.record_visit(request, response)
        return response

    def process_template_response(self, request, response):
        # 홈에는 이번 방문을 포함한 숫자를 표시하되, DB 기록은 렌더링 성공 후에 해요.
        # 템플릿 오류로 500 응답이 된 방문은 집계하지 않아요.
        match = request.resolver_match
        if match and match.view_name == 'community:index':
            from community import site_stats
            today = timezone.localdate()
            new_visit = int(self.is_page_visit(request, response)
                            and not request.session.get(f'visited_{today}'))
            row = DailyVisitor.objects.filter(date=today).first()
            response.context_data.update(
                visitors_today=(row.visitor_count if row else 0) + new_visit,
                visitors_total=f'{site_stats.visitors_total() + new_visit:,}',
            )
        return response

    def record_visit(self, request, response):
        if not self.is_page_visit(request, response):
            return
        today = timezone.localdate()
        session_key = f'visited_{today}'  # 이전 홈 집계와 호환해 당일 중복을 피해요.
        if request.session.get(session_key):
            return
        with transaction.atomic():
            row, created = DailyVisitor.objects.get_or_create(
                date=today, defaults={'visitor_count': 1},
            )
            if not created:
                DailyVisitor.objects.filter(pk=row.pk).update(visitor_count=F('visitor_count') + 1)
        request.session[session_key] = True
        # 날짜별 플래그가 세션에 계속 쌓이지 않게 해요.
        for key in list(request.session.keys()):
            if key.startswith('visited_') and key != session_key:
                del request.session[key]
        from community.site_stats import CACHE_KEY
        cache.delete(CACHE_KEY)

    def is_page_visit(self, request, response):
        if request.method != 'GET' or response.status_code != 200:
            return False
        if response.get('Content-Type', '').split(';')[0].strip().lower() != 'text/html':
            return False
        if response.get('Content-Disposition') or request.path_info.startswith(self.excluded_prefixes):
            return False
        match = getattr(request, 'resolver_match', None)
        if match and (match.app_name == 'admin' or match.url_name == 'portfolio_collection_raw'):
            return False
        agent = request.headers.get('User-Agent', '').strip()
        if not agent or agent == '-' or self.AUTOMATED_AGENT.search(agent):
            return False
        # 브라우저 UA만 복사한 HTTP 수집기를 방문으로 세지 않아요.
        # Safari·인앱 브라우저처럼 Fetch Metadata가 없는 정상 탐색은 HTML Accept로 허용해요.
        if not self.accepts_html(request.headers.get('Accept', '')):
            return False
        if request.headers.get('Sec-Fetch-Mode', 'navigate') != 'navigate':
            return False
        path = unquote(request.path_info)
        if any(pattern.search(path) for pattern in self.scanner_patterns):
            return False
        if request.headers.get('X-Requested-With', '').lower() == 'xmlhttprequest':
            return False
        # fetch로 받는 HTML 조각·iframe·미리 읽기는 실제 페이지 방문이 아니에요.
        if request.headers.get('Sec-Fetch-Dest', 'document') != 'document':
            return False
        if 'prefetch' in (request.headers.get('Purpose', '') + request.headers.get('Sec-Purpose', '')).lower():
            return False
        return True

    @staticmethod
    def accepts_html(accept):
        """와일드카드만 보내는 수집기 대신 HTML을 명시한 탐색을 집계해요."""
        for value in accept.lower().split(','):
            media, *params = (part.strip() for part in value.split(';'))
            if media not in ('text/html', 'application/xhtml+xml'):
                continue
            try:
                quality = next((float(p[2:]) for p in params if p.startswith('q=')), 1)
            except ValueError:
                continue
            if 0 < quality <= 1:
                return True
        return False
