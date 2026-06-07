"""관리자 OTP 세션 검증 — 뷰와 보안 미들웨어가 공유하는 단일 진실 소스.

관리자 대시보드 OTP 인증에 성공하면 세션에 다음이 저장된다(common/views.py):
  - admin_otp_until : 인증 만료 타임스탬프
  - admin_otp_ip    : 인증 시점의 클라이언트 IP (IP 바인딩)

이 두 값이 유효하면 '인증된 관리자 요청'으로 간주하여 보안 미들웨어의
의심(suspicious) 분류에서 제외한다(대시보드 실시간 로그 폴링 노이즈 제거).

세션은 DB 백엔드라 gunicorn 멀티워커에서 공유되며(CACHES는 LocMemCache라
워커별로 분리됨 — 그래서 캐시가 아닌 세션을 쓴다), 인증이 만료되거나 IP가
바뀌면 검증이 False가 되어 자동으로 '안심 IP'에서 빠진다 — 별도 정리 불필요.
"""
import time


def admin_otp_session_valid(session, client_ip):
    """세션이 OTP 인증 상태이고, 인증한 IP와 현재 IP가 일치하는가."""
    if not session:
        return False
    if time.time() >= session.get('admin_otp_until', 0):
        return False
    return session.get('admin_otp_ip') == client_ip


def is_trusted_admin_request(request, client_ip):
    """staff/superuser 이면서 유효한 OTP 세션(IP 바인딩 일치)을 가진 요청인가.

    True면 보안 미들웨어의 의심 분류/점수에서 제외한다. 인증 만료 시 자동 False.
    """
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and (user.is_staff or user.is_superuser)):
        return False
    return admin_otp_session_valid(getattr(request, 'session', None), client_ip)
