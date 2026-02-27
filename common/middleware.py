"""
테크창 보안 미들웨어
- Rate Limiting (요청 제한)
- DDoS 방지
- 비정상 행동 감지
- IP 차단
"""

from django.http import HttpResponse
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
import logging
import re
from datetime import timedelta

logger = logging.getLogger(__name__)

class SecurityMiddleware:
    """종합 보안 미들웨어"""
    
    def __init__(self, get_response):
        self.get_response = get_response

        # 설정값들 (환경 설정 우선)
        self.RATE_LIMIT_REQUESTS = getattr(settings, 'RATE_LIMIT_REQUESTS', 300)  # 시간당 요청 수
        self.RATE_LIMIT_WINDOW = getattr(settings, 'RATE_LIMIT_WINDOW', 3600)  # 1시간 윈도우
        self.DDOS_THRESHOLD = getattr(settings, 'DDOS_THRESHOLD', 120)  # 1분에 120회 초과시 의심
        self.BLOCK_DURATION = getattr(settings, 'BLOCK_DURATION', 180)  # 3분간 차단
        self.SUSPICION_SCORE_THRESHOLD = getattr(settings, 'SUSPICION_SCORE_THRESHOLD', 10)
        self.PROTECTED_PATH_ATTEMPTS_LIMIT = getattr(settings, 'PROTECTED_PATH_ATTEMPTS_LIMIT', 20)
        self.TRUSTED_PATHS = getattr(settings, 'TRUSTED_HEALTHCHECK_PATHS', ['/health', '/status'])

        # 게임 경로 (relaxed rate limit - 2048는 키보드 입력마다 요청)
        self.GAME_EXEMPT_PATHS = [
            '/pybo/baseball/',
            '/pybo/2048/',
            '/pybo/minesweeper/',
            '/pybo/wordchain/',
        ]
        # 게임용 relaxed rate limits (일반보다 2배 관대)
        self.GAME_DDOS_THRESHOLD = 200  # 1분에 200회까지 허용 (일반 120회의 1.67배)
        self.GAME_RATE_LIMIT_REQUESTS = 600  # 시간당 600회 (일반 300회의 2배)

        suspicious_patterns = getattr(settings, 'SUSPICIOUS_USER_AGENT_PATTERNS', [
            r'bot', r'crawler', r'spider', r'scraper'
        ])
        trusted_patterns = getattr(settings, 'TRUSTED_USER_AGENT_PATTERNS', [
            'curl', 'python-requests', 'wget', 'uptimerobot'
        ])
        self.SUSPICIOUS_AGENT_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in suspicious_patterns]
        self.TRUSTED_AGENT_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in trusted_patterns]
        
        # 보호할 경로들
        self.PROTECTED_PATHS = [
            '/common/signup/',
            '/common/send-verification-email/',
            '/pybo/question/create/',
            '/pybo/answer/create/',
        ]
        
        # 의심스러운 User-Agent 패턴은 설정으로 대체됨
    
    def __call__(self, request):
        # 보안 검사 실행
        security_response = self.check_security(request)
        if security_response:
            return security_response
        
        response = self.get_response(request)
        return response
    
    def check_security(self, request):
        """종합 보안 검사"""
        client_ip = self.get_client_ip(request)
        is_game_path = self.is_game_path(request.path)

        # 1. IP 차단 확인 (모든 경로 적용)
        if self.is_ip_blocked(client_ip):
            logger.warning(f"Blocked IP attempted access: {client_ip}")
            return HttpResponse("Access Denied", status=403)

        # 2. Rate Limiting 확인 (게임 경로는 더 관대한 제한)
        if is_game_path:
            if self.is_game_rate_limited(client_ip):
                self.block_ip(client_ip, "Game rate limit exceeded")
                logger.warning(f"Game rate limit exceeded for IP: {client_ip}")
                return HttpResponse("너무 빠르게 플레이하고 있습니다. 잠시 후 다시 시도해주세요.", status=429)
        else:
            if self.is_rate_limited(client_ip):
                self.block_ip(client_ip, "Rate limit exceeded")
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return HttpResponse("Rate limit exceeded. Please try again later.", status=429)

        # 3. DDoS 패턴 감지 (게임 경로는 더 관대한 임계값)
        if is_game_path:
            if self.detect_game_ddos_pattern(client_ip):
                self.block_ip(client_ip, "Game DDoS pattern detected")
                logger.error(f"Game DDoS pattern detected from IP: {client_ip}")
                return HttpResponse("비정상적인 게임 플레이가 감지되었습니다.", status=403)
        else:
            if self.detect_ddos_pattern(client_ip):
                self.block_ip(client_ip, "DDoS pattern detected")
                logger.error(f"DDoS pattern detected from IP: {client_ip}")
                return HttpResponse("Suspicious activity detected", status=403)

        # 4. 의심스러운 User-Agent 확인 (신뢰 경로와 게임 경로 제외)
        if not self.is_trusted_path(request.path) and not is_game_path and self.is_suspicious_user_agent(request):
            self.increase_suspicion_score(client_ip)
            logger.info(f"Suspicious User-Agent from IP {client_ip}: {request.META.get('HTTP_USER_AGENT', '')}")

        # 5. 보호된 경로에 대한 추가 검사
        if self.is_protected_path(request.path):
            if not self.check_protected_path_access(request, client_ip):
                return HttpResponse("Access Denied", status=403)

        return None
    
    def get_client_ip(self, request):
        """클라이언트 IP 주소 확인 (프록시 고려)"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # 보안: 마지막 IP 사용 (클라이언트에 가장 가까운 신뢰 프록시가 추가)
            # 첫 번째 IP는 공격자가 위조 가능
            ip = x_forwarded_for.split(',')[-1].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip if ip else '0.0.0.0'
    
    def is_ip_blocked(self, ip):
        """IP가 차단되어 있는지 확인"""
        return cache.get(f"blocked_ip:{ip}", False)
    
    def block_ip(self, ip, reason="Security violation"):
        """IP를 일시적으로 차단"""
        cache.set(f"blocked_ip:{ip}", True, self.BLOCK_DURATION)
        cache.set(f"block_reason:{ip}", reason, self.BLOCK_DURATION)
        logger.error(f"IP {ip} blocked for {self.BLOCK_DURATION} seconds. Reason: {reason}")
    
    def is_rate_limited(self, ip):
        """Rate Limiting 확인"""
        cache_key = f"rate_limit:{ip}"
        requests = cache.get(cache_key, 0)

        if requests >= self.RATE_LIMIT_REQUESTS:
            return True

        # 요청 카운트 증가
        cache.set(cache_key, requests + 1, self.RATE_LIMIT_WINDOW)
        return False

    def is_game_rate_limited(self, ip):
        """게임 경로용 Rate Limiting (더 관대한 제한)"""
        cache_key = f"game_rate_limit:{ip}"
        requests = cache.get(cache_key, 0)

        if requests >= self.GAME_RATE_LIMIT_REQUESTS:
            return True

        # 요청 카운트 증가
        cache.set(cache_key, requests + 1, self.RATE_LIMIT_WINDOW)
        return False

    def detect_ddos_pattern(self, ip):
        """DDoS 패턴 감지 (1분 윈도우)"""
        cache_key = f"ddos_detection:{ip}"
        requests_per_minute = cache.get(cache_key, 0)

        if requests_per_minute >= self.DDOS_THRESHOLD:
            return True

        # 1분간 요청 카운트
        cache.set(cache_key, requests_per_minute + 1, 60)
        return False

    def detect_game_ddos_pattern(self, ip):
        """게임 경로용 DDoS 패턴 감지 (더 관대한 임계값)"""
        cache_key = f"game_ddos_detection:{ip}"
        requests_per_minute = cache.get(cache_key, 0)

        if requests_per_minute >= self.GAME_DDOS_THRESHOLD:
            return True

        # 1분간 요청 카운트
        cache.set(cache_key, requests_per_minute + 1, 60)
        return False
    
    def is_suspicious_user_agent(self, request):
        """의심스러운 User-Agent 확인"""
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        if not user_agent.strip():
            return True

        if any(pattern.search(user_agent) for pattern in self.TRUSTED_AGENT_PATTERNS):
            return False

        return any(pattern.search(user_agent) for pattern in self.SUSPICIOUS_AGENT_PATTERNS)
    
    def increase_suspicion_score(self, ip):
        """IP의 의심 점수 증가"""
        cache_key = f"suspicion_score:{ip}"
        score = cache.get(cache_key, 0)
        new_score = score + 1
        
        cache.set(cache_key, new_score, 3600)  # 1시간 유지
        
        # 의심 점수가 높으면 차단
        if new_score >= self.SUSPICION_SCORE_THRESHOLD:
            self.block_ip(ip, "High suspicion score")

    def is_game_path(self, path):
        """게임 경로인지 확인"""
        return any(path.startswith(game_path) for game_path in self.GAME_EXEMPT_PATHS)

    def is_trusted_path(self, path):
        """신뢰된 경로(헬스체크 등)인지 확인"""
        return any(path.startswith(trusted) for trusted in self.TRUSTED_PATHS)

    def is_protected_path(self, path):
        """보호된 경로인지 확인"""
        return any(path.startswith(protected) for protected in self.PROTECTED_PATHS)
    
    def check_protected_path_access(self, request, ip):
        """보호된 경로 접근 검사"""
        # 로그인한 사용자는 통과
        if request.user.is_authenticated:
            return True
        
        # 보호된 경로에 대한 추가 제한
        cache_key = f"protected_access:{ip}"
        attempts = cache.get(cache_key, 0)
        
        if attempts >= self.PROTECTED_PATH_ATTEMPTS_LIMIT:
            self.block_ip(ip, "Excessive protected path access")
            return False
        
        cache.set(cache_key, attempts + 1, 3600)
        return True


class RequestLoggingMiddleware:
    """요청 로깅 미들웨어 (보안 모니터링용)"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # 게임 플레이 경로는 로깅 제외 (성능 최적화)
        GAME_PATHS = ['/pybo/baseball/', '/pybo/2048/', '/pybo/minesweeper/']
        if any(request.path.startswith(game_path) for game_path in GAME_PATHS):
            return self.get_response(request)

        # 요청 시작 시간
        start_time = timezone.now()

        # 기본 정보 수집
        client_ip = self.get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        referer = request.META.get('HTTP_REFERER', '')

        response = self.get_response(request)
        
        # 응답 시간 계산
        end_time = timezone.now()
        response_time = (end_time - start_time).total_seconds()
        
        # 의심스러운 패턴 로깅
        if self.is_suspicious_request(request, response, response_time):
            logger.warning(f"Suspicious request detected - IP: {client_ip}, "
                         f"Path: {request.path}, Status: {response.status_code}, "
                         f"Time: {response_time:.3f}s, Agent: {user_agent[:100]}")
        
        return response
    
    def get_client_ip(self, request):
        """클라이언트 IP 주소 확인"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # 보안: 마지막 IP 사용 (클라이언트에 가까운 신뢰 프록시가 추가)
            ip = x_forwarded_for.split(',')[-1].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip if ip else '0.0.0.0'
    
    def is_suspicious_request(self, request, response, response_time):
        """의심스러운 요청 패턴 확인"""
        # 1. 너무 빠른 응답 (봇 가능성)
        if response_time < 0.1:
            return True
        
        # 2. 404 오류가 많은 경우 (스캐닝 가능성)
        if response.status_code == 404:
            return True
        
        # 3. POST 요청에서 CSRF 오류
        if request.method == 'POST' and response.status_code == 403:
            return True
        
        # 4. 관리자 페이지 접근 시도
        if '/admin' in request.path and not request.user.is_staff:
            return True
        
        return False


class MobileDetectionMiddleware:
    """모바일 기기 감지 미들웨어 - User-Agent 기반 + 쿠키 수동 전환"""

    MOBILE_KEYWORDS = [
        'mobile', 'android', 'iphone', 'ipad', 'ipod',
        'windows phone', 'blackberry', 'opera mini', 'iemobile',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        is_mobile_device = any(kw in user_agent for kw in self.MOBILE_KEYWORDS)

        # 쿠키로 사용자 수동 전환 확인 (우선)
        user_preference = request.COOKIES.get('force_version')  # 'mobile' or 'desktop'

        if user_preference in ('mobile', 'desktop'):
            request.is_mobile = (user_preference == 'mobile')
            request.is_forced = True
        else:
            request.is_mobile = is_mobile_device
            request.is_forced = False

        return self.get_response(request)


# 안전한 설정 검사
def validate_security_settings():
    """보안 설정 유효성 검사"""
    warnings = []
    
    # DEBUG 모드 체크
    if getattr(settings, 'DEBUG', False):
        warnings.append("DEBUG mode is enabled - should be False in production")
    
    # SECRET_KEY 체크
    secret_key = getattr(settings, 'SECRET_KEY', '')
    if not secret_key or len(secret_key) < 50:
        warnings.append("SECRET_KEY is too short or missing")
    
    # ALLOWED_HOSTS 체크
    allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
    if '*' in allowed_hosts:
        warnings.append("ALLOWED_HOSTS contains '*' - security risk")
    
    # CSRF 설정 체크
    csrf_cookie_secure = getattr(settings, 'CSRF_COOKIE_SECURE', False)
    if not csrf_cookie_secure:
        warnings.append("CSRF_COOKIE_SECURE should be True in production")
    
    if warnings:
        logger.warning("Security configuration warnings: " + "; ".join(warnings))
    
    return warnings