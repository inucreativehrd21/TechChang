
# from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.mail import send_mail
from django.core.cache import cache
import json
import logging
import requests
import secrets
from datetime import timedelta
from django.contrib.auth.models import User
from common.forms import UserForm, ProfileForm
from .models import Profile, EmailVerification, KakaoUser
from community.utils import award_points, deduct_points


logger = logging.getLogger(__name__)


def logout_view(request):
    logout(request)
    return redirect('community:index')

def signup(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            # 닉네임 처리
            nickname = form.cleaned_data.get('nickname')
            if nickname:
                profile, created = Profile.objects.get_or_create(user=user)
                profile.nickname = nickname
                profile.save()
            
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)  # 사용자 인증
            login(request, user)  # 로그인
            return redirect('community:index')
    else:
        form = UserForm()
    return render(request, 'common/signup.html', {'form': form})
# Create your views here.


@require_POST
def save_theme(request):
    """POST /common/theme/ : 사용자 테마 저장

    동작:
      - 파라미터: theme=light|dark|highcontrast
      - 로그인 사용자: Profile.theme 업데이트
      - 비로그인: 서버가 단순히 쿠키 설정으로 응답
      - 응답 JSON: {status: 'ok', theme: <theme>} 또는 오류
    """
    theme = request.POST.get('theme')
    valid = {'light', 'dark', 'highcontrast'}
    if theme not in valid:
        return JsonResponse({'status': 'error', 'error': 'invalid theme'}, status=400)

    if request.user.is_authenticated:
        profile, _ = Profile.objects.get_or_create(user=request.user)
        if profile.theme != theme:
            profile.theme = theme
            profile.save(update_fields=['theme', 'updated_at'])

    resp = JsonResponse({'status': 'ok', 'theme': theme})
    # 클라이언트 JS와 통일된 이름의 쿠키
    resp.set_cookie('site_theme', theme, max_age=3600*24*365, samesite='Lax')
    return resp


@login_required(login_url='common:login')
def profile_edit(request):
    """사용자 프로필 편집"""
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, '프로필이 성공적으로 업데이트되었습니다.')
            return redirect('common:profile_edit')
    else:
        form = ProfileForm(instance=profile)
    
    return render(request, 'common/profile_edit.html', {'form': form, 'profile': profile})

@login_required(login_url='common:login')
def account_delete(request):
    """안전한 회원 탈퇴 기능"""
    if request.method == 'POST':
        # 비밀번호 확인
        password = request.POST.get('password', '')
        if not request.user.check_password(password):
            messages.error(request, '비밀번호가 일치하지 않습니다.')
            return render(request, 'common/account_delete_confirm.html')
        
        # 확인 문구 검증
        confirm_text = request.POST.get('confirm_delete', '')
        if confirm_text != '회원탈퇴':
            messages.error(request, '확인 문구를 정확히 입력해주세요.')
            return render(request, 'common/account_delete_confirm.html')
        
        try:
            # 사용자 데이터 처리
            user = request.user
            
            # 프로필 이미지 삭제
            try:
                if hasattr(user, 'profile') and user.profile.profile_image:
                    user.profile.profile_image.delete(save=False)
            except Exception:
                pass  # 이미지 삭제 실패해도 계속 진행
            
            # 작성한 질문들을 삭제로 마킹 (soft delete)
            from community.models import Question, Answer
            
            user.author_question.filter(is_deleted=False).update(
                is_deleted=True, 
                deleted_date=timezone.now()
            )
            
            # 작성한 답변들을 삭제로 마킹 (soft delete)
            user.author_answer.filter(is_deleted=False).update(
                is_deleted=True, 
                deleted_date=timezone.now()
            )
            
            # 로그아웃 처리
            logout(request)
            
            # 계정 비활성화 (실제 삭제 대신 안전한 방법)
            user.is_active = False
            user.email = f"deleted_{user.id}_{user.email}"  # 이메일 중복 방지
            user.username = f"deleted_{user.id}_{user.username}"  # 사용자명 중복 방지
            user.save()

            messages.success(request, '회원 탈퇴가 완료되었습니다. 그동안 테크창을 이용해주셔서 감사합니다.')
            return redirect('community:index')
            
        except Exception as e:
            messages.error(request, '회원 탈퇴 처리 중 오류가 발생했습니다. 관리자에게 문의해주세요.')
            return render(request, 'common/account_delete_confirm.html')
    
    # GET 요청시 확인 페이지 표시
    return render(request, 'common/account_delete_confirm.html')

def send_verification_email(request):
    """이메일 인증 코드 발송 (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '요청 형식이 올바르지 않습니다.'}, status=400)

    email = data.get('email', '').strip().lower()
    if not email:
        return JsonResponse({'success': False, 'message': '이메일을 입력해주세요.'}, status=400)

    if User.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'message': '이미 사용 중인 이메일입니다.'}, status=400)

    # 이메일/아이피별 간단한 요청 속도 제한
    cooldown_key = f"email_verification:cooldown:{email}"
    if cache.get(cooldown_key):
        return JsonResponse({'success': False, 'message': '인증 코드를 잠시 후 다시 요청해주세요.'}, status=429)

    ip_address = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[-1].strip()
                  or request.META.get('REMOTE_ADDR'))
    if ip_address:
        ip_cooldown_key = f"email_verification:cooldown_ip:{ip_address}"
        if cache.get(ip_cooldown_key):
            return JsonResponse({'success': False, 'message': '요청이 너무 빈번합니다. 잠시 후 다시 시도해주세요.'}, status=429)

    # 진행 중인 인증 레코드 정리
    EmailVerification.objects.filter(email=email, is_verified=False).delete()

    code = EmailVerification.generate_code()
    verification = EmailVerification.objects.create(email=email, code=code)

    message_body = f'''
안녕하세요! 테크창입니다.

회원가입을 위한 이메일 인증 코드는 다음과 같습니다:

인증코드: {code}

이 코드는 10분간 유효합니다.
인증 코드를 입력하여 회원가입을 완료해주세요.

감사합니다.
'''

    try:
        send_mail(
            subject='[테크창] 이메일 인증 코드',
            message=message_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.exception("Failed to send verification email to %s", email)
        verification.delete()
        if settings.DEBUG:
            return JsonResponse({'success': True, 'message': f'개발 모드: 인증코드는 {code}입니다.', 'code': code})
        # 에러 타입과 메시지를 더 자세히 반환 (프로덕션에서 디버깅용)
        logger.error(f"Email send error - Type: {type(exc).__name__}, Message: {exc}")
        return JsonResponse({
            'success': False,
            'message': '이메일 발송 중 문제가 발생했습니다. 관리자에게 문의해주세요.',
        }, status=500)

    cache.set(cooldown_key, True, timeout=EmailVerification.RESEND_COOLDOWN_SECONDS)
    if ip_address:
        cache.set(f"email_verification:cooldown_ip:{ip_address}", True, timeout=EmailVerification.RESEND_COOLDOWN_SECONDS)

    return JsonResponse({'success': True, 'message': f'인증 코드가 {email}로 발송되었습니다.'})

def verify_email_code(request):
    """이메일 인증 코드 확인 (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '요청 형식이 올바르지 않습니다.'}, status=400)

    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()

    if not email or not code:
        return JsonResponse({'success': False, 'message': '이메일과 인증코드를 모두 입력해주세요.'}, status=400)

    verification = EmailVerification.objects.filter(
        email=email,
        is_verified=False
    ).order_by('-created_at').first()

    if not verification:
        return JsonResponse({'success': False, 'message': '인증 요청을 찾을 수 없습니다. 코드를 다시 요청해주세요.'}, status=404)

    if verification.is_expired():
        verification.delete()
        return JsonResponse({'success': False, 'message': '인증 코드가 만료되었습니다. 새로운 코드를 요청해주세요.'}, status=400)

    if not verification.can_retry():
        verification.delete()
        return JsonResponse({'success': False, 'message': '인증 시도 횟수를 초과했습니다. 새로운 코드를 요청해주세요.'}, status=429)

    if not secrets.compare_digest(verification.code, code):
        remaining = verification.increment_attempts()
        if remaining <= 0:
            verification.delete()
            return JsonResponse({'success': False, 'message': '인증 시도 횟수를 초과했습니다. 새로운 코드를 요청해주세요.'}, status=429)
        return JsonResponse({'success': False, 'message': f'인증 코드가 틀렸습니다. (남은 시도: {remaining}회)'}, status=400)

    verification.mark_verified()
    return JsonResponse({'success': True, 'message': '이메일 인증이 완료되었습니다.'})

@login_required
def send_profile_verification_email(request):
    """프로필 페이지에서 이메일 인증 코드 발송 (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '요청 형식이 올바르지 않습니다.'}, status=400)

    email = data.get('email', '').strip().lower()
    if not email:
        return JsonResponse({'success': False, 'message': '이메일을 입력해주세요.'}, status=400)

    # 이메일이 다른 사용자에게 사용 중인지 확인 (자신의 이메일은 허용)
    existing_user = User.objects.filter(email=email).exclude(id=request.user.id).first()
    if existing_user:
        return JsonResponse({'success': False, 'message': '이미 다른 사용자가 사용 중인 이메일입니다.'}, status=400)

    # 이메일/아이피별 간단한 요청 속도 제한
    cooldown_key = f"email_verification:cooldown:{email}"
    if cache.get(cooldown_key):
        return JsonResponse({'success': False, 'message': '인증 코드를 잠시 후 다시 요청해주세요.'}, status=429)

    ip_address = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[-1].strip()
                  or request.META.get('REMOTE_ADDR'))
    if ip_address:
        ip_cooldown_key = f"email_verification:cooldown_ip:{ip_address}"
        if cache.get(ip_cooldown_key):
            return JsonResponse({'success': False, 'message': '요청이 너무 빈번합니다. 잠시 후 다시 시도해주세요.'}, status=429)

    # 진행 중인 인증 레코드 정리
    EmailVerification.objects.filter(email=email, is_verified=False).delete()

    code = EmailVerification.generate_code()
    verification = EmailVerification.objects.create(email=email, code=code)

    # 이메일 변경인지 현재 이메일 인증인지 확인
    is_change = email != request.user.email
    action_text = "이메일 변경" if is_change else "이메일 인증"

    message_body = f'''
안녕하세요, {request.user.username}님!

{action_text}을 위한 인증 코드는 다음과 같습니다:

인증코드: {code}

이 코드는 10분간 유효합니다.
인증 코드를 입력하여 {action_text}을 완료해주세요.

감사합니다.
- 테크창
'''

    try:
        send_mail(
            subject=f'[테크창] {action_text} 인증 코드',
            message=message_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as exc:
        logger.exception("Failed to send profile verification email to %s", email)
        verification.delete()
        if settings.DEBUG:
            return JsonResponse({'success': True, 'message': f'개발 모드: 인증코드는 {code}입니다.', 'code': code})
        error_type = type(exc).__name__
        error_msg = str(exc)
        logger.error(f"Email send error - Type: {error_type}, Message: {error_msg}")
        return JsonResponse({
            'success': False,
            'message': f'이메일 발송 중 문제가 발생했습니다. 관리자에게 문의해주세요. (Error: {error_type})',
            'debug_info': error_msg if settings.DEBUG else None
        }, status=500)

    cache.set(cooldown_key, True, timeout=EmailVerification.RESEND_COOLDOWN_SECONDS)
    if ip_address:
        cache.set(f"email_verification:cooldown_ip:{ip_address}", True, timeout=EmailVerification.RESEND_COOLDOWN_SECONDS)

    return JsonResponse({'success': True, 'message': f'인증 코드가 {email}로 발송되었습니다.'})


@login_required
def verify_email_change(request):
    """프로필 페이지에서 이메일 인증/변경 (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '요청 형식이 올바르지 않습니다.'}, status=400)

    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()

    if not email or not code:
        return JsonResponse({'success': False, 'message': '이메일과 인증코드를 모두 입력해주세요.'}, status=400)

    # 이메일 인증 확인
    verification = EmailVerification.objects.filter(
        email=email,
        is_verified=False
    ).order_by('-created_at').first()

    if not verification:
        return JsonResponse({'success': False, 'message': '인증 요청을 찾을 수 없습니다. 코드를 다시 요청해주세요.'}, status=404)

    if verification.is_expired():
        verification.delete()
        return JsonResponse({'success': False, 'message': '인증 코드가 만료되었습니다. 새로운 코드를 요청해주세요.'}, status=400)

    if not verification.can_retry():
        verification.delete()
        return JsonResponse({'success': False, 'message': '인증 시도 횟수를 초과했습니다. 새로운 코드를 요청해주세요.'}, status=429)

    if not secrets.compare_digest(verification.code, code):
        remaining = verification.increment_attempts()
        if remaining <= 0:
            verification.delete()
            return JsonResponse({'success': False, 'message': '인증 시도 횟수를 초과했습니다. 새로운 코드를 요청해주세요.'}, status=429)
        return JsonResponse({'success': False, 'message': f'인증 코드가 틀렸습니다. (남은 시도: {remaining}회)'}, status=400)

    # 인증 성공 - 사용자 이메일 업데이트
    verification.mark_verified()
    user = request.user
    user.email = email
    user.save(update_fields=['email'])

    # 프로필의 is_email_verified를 True로 설정
    profile = user.profile
    profile.is_email_verified = True
    profile.save(update_fields=['is_email_verified'])

    return JsonResponse({'success': True, 'message': '이메일 인증이 완료되었습니다.'})


@login_required
def force_email_verification(request):
    """미인증(비카카오) 사용자 강제 이메일 인증 페이지.

    이메일을 입력/수정한 뒤 인증하면 verify_email_change(AJAX)가 user.email과
    profile.is_email_verified를 갱신한다 — 과거 더미 이메일 사용자가 올바른
    이메일로 교체할 수 있도록 입력 필드를 편집 가능하게 둔다.
    이미 인증됐거나 카카오 사용자는 들어올 필요가 없으므로 홈으로 보낸다.
    """
    user = request.user
    profile = getattr(user, 'profile', None)
    if user.username.startswith('kakao_') or (profile and profile.is_email_verified):
        return redirect('community:index')

    # 더미/플레이스홀더 이메일(빈 값·@kakao.user·@ 없음)이면 비워서 새 입력을 유도
    current = (user.email or '').strip()
    looks_dummy = (not current) or current.endswith('@kakao.user') or '@' not in current
    return render(request, 'common/force_email_verification.html', {
        'current_email': '' if looks_dummy else current,
        'looks_dummy': looks_dummy,
    })


def signup_with_email_verification(request):
    """이메일 인증이 포함된 회원가입"""
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data.get('email')

            # 이메일 인증 확인
            verification = EmailVerification.objects.filter(
                email=email,
                is_verified=True
            ).order_by('-verified_at').first()

            if not verification:
                messages.error(request, '이메일 인증을 먼저 완료해주세요.')
                return render(request, 'common/signup_with_verification.html', {'form': form})

            # 인증 후 30분 이내인지 확인 (보안상)
            from datetime import timedelta
            if timezone.now() > verification.verified_at + timedelta(minutes=30):
                messages.error(request, '이메일 인증이 만료되었습니다. 다시 인증해주세요.')
                verification.delete()
                return render(request, 'common/signup_with_verification.html', {'form': form})

            # 사용자 생성
            user = form.save()

            # 프로필 생성 및 이메일 인증 상태 설정
            nickname = form.cleaned_data.get('nickname')
            profile, created = Profile.objects.get_or_create(user=user)
            if nickname:
                profile.nickname = nickname
            profile.is_email_verified = True  # 이메일 인증 완료
            profile.save()

            # 인증 기록 삭제
            verification.delete()

            # 자동 로그인
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)
            login(request, user)

            messages.success(request, '회원가입이 완료되었습니다! 테크창에 오신 것을 환영합니다.')
            return redirect('community:index')
    else:
        form = UserForm()

    return render(request, 'common/signup_with_verification.html', {'form': form})


# ==================== 카카오 로그인 ====================
def kakao_login(request):
    """카카오 로그인 시작 (인가 코드 요청)"""
    import secrets
    from django.utils import timezone

    # 환경변수에서 카카오 REST API 키 가져오기
    kakao_rest_api_key = settings.KAKAO_REST_API_KEY

    # 도메인 기반 redirect_uri 생성
    host = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    redirect_uri = f"{scheme}://{host}/common/kakao/callback/"

    # State 토큰 생성 (CSRF 방지)
    state_token = secrets.token_urlsafe(32)

    # 세션에 state 저장 (검증용)
    request.session['kakao_oauth_state'] = state_token
    request.session['kakao_oauth_state_created'] = timezone.now().isoformat()

    kakao_auth_url = (
        f"https://kauth.kakao.com/oauth/authorize"
        f"?client_id={kakao_rest_api_key}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&state={state_token}"  # State 추가
    )

    return redirect(kakao_auth_url)


def kakao_callback(request):
    """카카오 로그인 콜백 (토큰 및 사용자 정보 받기)"""
    from django.utils import timezone
    from datetime import datetime, timedelta

    code = request.GET.get('code')
    state = request.GET.get('state')  # 수신된 state

    if not code:
        messages.error(request, '카카오 로그인에 실패했습니다.')
        return redirect('common:login')

    # State 검증
    saved_state = request.session.get('kakao_oauth_state')
    state_created = request.session.get('kakao_oauth_state_created')

    if not saved_state or not state:
        logger.warning(f"카카오 OAuth state 누락: saved={bool(saved_state)}, received={bool(state)}")
        messages.error(request, '인증 오류: State 토큰이 없습니다.')
        return redirect('common:login')

    if saved_state != state:
        logger.warning(f"카카오 OAuth state 불일치")
        messages.error(request, '인증 오류: 잘못된 요청입니다.')
        return redirect('common:login')

    # State 만료 검증 (5분)
    if state_created:
        created_time = datetime.fromisoformat(state_created)
        if timezone.now() - created_time > timedelta(minutes=5):
            logger.warning("카카오 OAuth state 만료")
            messages.error(request, '인증 시간이 만료되었습니다. 다시 시도해주세요.')
            return redirect('common:login')

    # State 세션 삭제 (재사용 방지)
    del request.session['kakao_oauth_state']
    if 'kakao_oauth_state_created' in request.session:
        del request.session['kakao_oauth_state_created']

    # 환경변수에서 키 가져오기
    kakao_rest_api_key = settings.KAKAO_REST_API_KEY
    kakao_client_secret = settings.KAKAO_CLIENT_SECRET

    # 도메인 기반 redirect_uri 생성
    host = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    redirect_uri = f"{scheme}://{host}/common/kakao/callback/"

    # 1. 토큰 요청
    token_url = "https://kauth.kakao.com/oauth/token"
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': kakao_rest_api_key,
        'client_secret': kakao_client_secret,
        'redirect_uri': redirect_uri,
        'code': code,
    }

    try:
        token_response = requests.post(token_url, data=token_data)
        token_json = token_response.json()

        if 'error' in token_json:
            messages.error(request, f'토큰 요청 실패: {token_json.get("error_description")}')
            return redirect('common:login')

        access_token = token_json.get('access_token')
        refresh_token = token_json.get('refresh_token')
        expires_in = token_json.get('expires_in', 21600)  # 기본 6시간

        # 2. 사용자 정보 요청
        user_info_url = "https://kapi.kakao.com/v2/user/me"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'
        }

        user_info_response = requests.get(user_info_url, headers=headers)
        user_info = user_info_response.json()

        if 'id' not in user_info:
            messages.error(request, '사용자 정보를 가져올 수 없습니다.')
            return redirect('common:login')

        # 3. 카카오 사용자 정보 파싱
        kakao_id = user_info['id']
        kakao_account = user_info.get('kakao_account', {})
        profile = kakao_account.get('profile', {})

        nickname = profile.get('nickname')
        email = kakao_account.get('email')
        profile_image = profile.get('profile_image_url')
        thumbnail_image = profile.get('thumbnail_image_url')

        # 4. KakaoUser DB에 저장 또는 업데이트
        kakao_user, created = KakaoUser.objects.get_or_create(
            kakao_id=kakao_id,
            defaults={
                'nickname': nickname,
                'email': email,
                'profile_image': profile_image,
                'thumbnail_image': thumbnail_image,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expires_at': timezone.now() + timedelta(seconds=expires_in),
            }
        )

        if not created:
            # 기존 사용자 정보 업데이트
            kakao_user.nickname = nickname
            kakao_user.email = email
            kakao_user.profile_image = profile_image
            kakao_user.thumbnail_image = thumbnail_image
            kakao_user.access_token = access_token
            kakao_user.refresh_token = refresh_token
            kakao_user.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            kakao_user.last_login = timezone.now()
            kakao_user.save()

        # 5. Django User 자동 생성 또는 로그인
        username = f'kakao_{kakao_id}'

        try:
            # 기존 Django User 확인
            django_user = User.objects.get(username=username)
        except User.DoesNotExist:
            # Django User 생성 (임의의 복잡한 비밀번호 설정)
            random_password = secrets.token_urlsafe(32)
            django_user = User.objects.create_user(
                username=username,
                email=email if email else f'kakao_{kakao_id}@kakao.user',
                password=random_password
            )

            # Profile 생성
            Profile.objects.get_or_create(user=django_user, defaults={'nickname': nickname})

        # Django 인증 시스템으로 로그인
        login(request, django_user, backend='django.contrib.auth.backends.ModelBackend')

        # 세션에 카카오 정보 추가 저장
        request.session['kakao_user_id'] = kakao_user.id
        request.session['kakao_nickname'] = kakao_user.nickname
        request.session['is_kakao_user'] = True

        messages.success(request, f'{nickname}님, 카카오 로그인에 성공했습니다!')
        return redirect('community:index')

    except requests.exceptions.RequestException as e:
        logger.error(f"카카오 API 요청 오류: {e}")
        messages.error(request, '카카오 로그인 중 오류가 발생했습니다.')
        return redirect('common:login')
    except Exception as e:
        logger.error(f"카카오 로그인 오류: {e}")
        messages.error(request, f'로그인 처리 중 오류가 발생했습니다: {str(e)}')
        return redirect('common:login')


def kakao_logout(request):
    """카카오 로그아웃"""
    kakao_user_id = request.session.get('kakao_user_id')

    if kakao_user_id:
        try:
            kakao_user = KakaoUser.objects.get(id=kakao_user_id)
            access_token = kakao_user.access_token

            # 카카오 로그아웃 API 호출
            logout_url = "https://kapi.kakao.com/v1/user/logout"
            headers = {'Authorization': f'Bearer {access_token}'}
            requests.post(logout_url, headers=headers)
        except Exception as e:
            logger.error(f"카카오 로그아웃 오류: {e}")

    # Django 로그아웃
    logout(request)

    # 세션 정리
    request.session.pop('kakao_user_id', None)
    request.session.pop('kakao_nickname', None)
    request.session.pop('is_kakao_user', None)

    messages.success(request, '로그아웃되었습니다.')
    return redirect('common:login')


# ==================== 관리자 기능 ====================

from functools import wraps
from django.http import HttpResponseForbidden
from django.db.models import Q, Count


def admin_required(view_func):
    """관리자 권한이 필요한 뷰를 위한 데코레이터"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, '로그인이 필요합니다.')
            return redirect('common:login')
        if not request.user.is_staff and not request.user.is_superuser:
            messages.error(request, '관리자 권한이 필요합니다.')
            return redirect('community:index')
        return view_func(request, *args, **kwargs)
    return wrapper


# ====================================================================== #
#  관리자 대시보드 2차 인증 (이메일 OTP + IP 바인딩)
#  민감한 서버 로그·모니터에 접근하기 전, 관리자 이메일로 8자리 영문+숫자
#  코드를 발송해 재인증한다. 인증 상태는 "요청한 IP"에 묶이며, 세션 쿠키를
#  탈취당하더라도 인증 시점과 다른 IP에서의 접근은 철저히 차단된다.
# ====================================================================== #
ADMIN_OTP_WINDOW_SECONDS   = 30 * 60   # 재인증 유지 시간 (이 안에서는 메일 재발송 없음)
ADMIN_OTP_CODE_TTL_SECONDS = 10 * 60   # 발송된 코드 유효 시간
ADMIN_OTP_RESEND_COOLDOWN  = 60        # 재발송 최소 간격
ADMIN_OTP_MAX_ATTEMPTS     = 5         # 코드 검증 시도 제한


def _client_ip(request):
    """클라이언트 IP. nginx 프록시 환경에서 보안 미들웨어와 동일 규칙(XFF 마지막 값)."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        ip = xff.split(',')[-1].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip or '0.0.0.0'


def _admin_otp_recipient():
    """OTP 수신 이메일 — .env DJANGO_ADMIN_EMAIL 고정 (없으면 settings.ADMINS)."""
    import os
    rcpt = os.environ.get('DJANGO_ADMIN_EMAIL', '').strip()
    if not rcpt and getattr(settings, 'ADMINS', None):
        rcpt = settings.ADMINS[0][1]
    return rcpt


def _generate_admin_otp(length=8):
    """영문 대소문자+숫자 혼합 8자리. 혼동 문자(O,I,l,0,1) 제외, 최소 1영문+1숫자 보장."""
    import secrets
    import string
    letters = ''.join(c for c in string.ascii_letters if c not in 'OIl')
    digits = ''.join(c for c in string.digits if c not in '01')
    alphabet = letters + digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if any(c in letters for c in code) and any(c in digits for c in code):
            return code


def _admin_otp_session_ok(request):
    """현재 세션이 OTP 인증 상태이고, 인증한 IP와 현재 접속 IP가 일치하는가.

    검증 로직은 보안 미들웨어와 공유한다(common.admin_security) — 인증된
    관리자 IP를 의심 분류에서 제외하는 데 동일 기준을 사용하기 위함.
    """
    from common.admin_security import admin_otp_session_valid
    return admin_otp_session_valid(request.session, _client_ip(request))


def admin_otp_required(view_func):
    """관리자 권한 + 이메일 OTP(IP 바인딩) 2차 인증을 요구하는 데코레이터."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, '로그인이 필요합니다.')
            return redirect('common:login')
        if not request.user.is_staff and not request.user.is_superuser:
            messages.error(request, '관리자 권한이 필요합니다.')
            return redirect('community:index')
        if not _admin_otp_session_ok(request):
            request.session['admin_otp_next'] = request.get_full_path()
            return redirect('common:admin_otp')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_otp(request):
    """관리자 대시보드 2차 인증 페이지 — 코드 발송 및 검증 (IP 바인딩)."""
    import time
    from django.urls import reverse

    if not request.user.is_authenticated:
        messages.error(request, '로그인이 필요합니다.')
        return redirect('common:login')
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, '관리자 권한이 필요합니다.')
        return redirect('community:index')

    ip = _client_ip(request)
    next_url = request.session.get('admin_otp_next') or reverse('common:admin_dashboard')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('common:admin_dashboard')

    # 이미 인증된 상태(IP 일치 + 유효시간 내)면 바로 통과
    if _admin_otp_session_ok(request):
        return redirect(next_url)

    recipient = _admin_otp_recipient()
    # 펜딩 코드/쿨다운은 세션(DB 백엔드, 워커 간 공유)에 저장한다.
    # CACHES가 LocMemCache(프로세스별)라 gunicorn 멀티워커에서는 발송 워커와
    # 검증 워커가 달라 캐시 기반 코드가 유실될 수 있으므로 세션을 사용한다.

    def _send_code(force=False):
        if not recipient:
            messages.error(request, '관리자 수신 이메일(.env DJANGO_ADMIN_EMAIL)이 설정되지 않았습니다.')
            return 'nomail'
        last_sent = request.session.get('admin_otp_sent_at', 0)
        if not force and (time.time() - last_sent) < ADMIN_OTP_RESEND_COOLDOWN:
            return 'cooldown'  # 쿨다운 중 — 기존 코드 유지(새로고침 시 메일 폭주 방지)
        code = _generate_admin_otp()
        request.session['admin_otp_pending'] = {
            'code': code, 'ip': ip, 'attempts': 0,
            'exp': time.time() + ADMIN_OTP_CODE_TTL_SECONDS,
        }
        body = (
            '테크창 관리자 대시보드 접속 인증 코드입니다.\n\n'
            f'인증코드: {code}\n\n'
            f'요청 IP: {ip}\n'
            f'유효시간: {ADMIN_OTP_CODE_TTL_SECONDS // 60}분 · 인증 후 {ADMIN_OTP_WINDOW_SECONDS // 60}분간 유지\n\n'
            '본인이 요청하지 않았다면 코드를 입력하지 말고 즉시 비밀번호를 변경하세요.'
        )
        try:
            send_mail(
                subject='[테크창] 관리자 대시보드 인증 코드',
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception:
            logger.exception('관리자 OTP 이메일 발송 실패')
            request.session.pop('admin_otp_pending', None)
            messages.error(request, '인증 코드 발송에 실패했습니다. 잠시 후 다시 시도해주세요.')
            return 'error'
        request.session['admin_otp_sent_at'] = time.time()
        logger.warning('관리자 OTP 발송: user=%s ip=%s', request.user.username, ip)
        return 'sent'

    def _get_pending():
        p = request.session.get('admin_otp_pending')
        if not p:
            return None
        if time.time() >= p.get('exp', 0):  # 만료
            request.session.pop('admin_otp_pending', None)
            return None
        return p

    if request.method == 'POST':
        action = request.POST.get('action', 'verify')

        if action == 'resend':
            status = _send_code(force=False)
            if status == 'sent':
                messages.success(request, '인증 코드를 발송했습니다. 이메일을 확인해주세요.')
            elif status == 'cooldown':
                messages.info(request, '이미 코드를 발송했습니다. 이메일을 확인하거나 잠시 후 다시 시도해주세요.')
            return redirect('common:admin_otp')

        # 코드 검증
        submitted = (request.POST.get('code') or '').strip()
        pending = _get_pending()
        if not pending:
            messages.error(request, '인증 코드가 만료되었습니다. 코드를 다시 받아주세요.')
            return redirect('common:admin_otp')
        if pending.get('ip') != ip:
            # 코드를 요청한 IP와 다른 IP에서의 검증 시도 → 철저히 차단.
            # (코드는 삭제하지 않는다: 정당한 IP의 관리자가 계속 사용할 수 있어야 하고,
            #  코드 값 비교 자체를 하지 않으므로 타 IP에서의 무차별 대입은 무의미하다.)
            logger.warning('관리자 OTP IP 불일치 차단: user=%s req_ip=%s code_ip=%s',
                           request.user.username, ip, pending.get('ip'))
            messages.error(request, '인증을 요청한 IP와 접속 IP가 일치하지 않아 차단되었습니다.')
            return redirect('common:admin_otp')
        if pending.get('attempts', 0) >= ADMIN_OTP_MAX_ATTEMPTS:
            request.session.pop('admin_otp_pending', None)
            messages.error(request, '시도 횟수를 초과했습니다. 코드를 다시 받아주세요.')
            return redirect('common:admin_otp')

        if secrets.compare_digest(str(pending.get('code', '')), submitted):
            request.session['admin_otp_until'] = time.time() + ADMIN_OTP_WINDOW_SECONDS
            request.session['admin_otp_ip'] = ip
            request.session.pop('admin_otp_next', None)
            request.session.pop('admin_otp_pending', None)
            request.session.pop('admin_otp_sent_at', None)
            messages.success(request, '인증되었습니다.')
            return redirect(next_url)

        pending['attempts'] = pending.get('attempts', 0) + 1
        remaining = max(ADMIN_OTP_MAX_ATTEMPTS - pending['attempts'], 0)
        request.session['admin_otp_pending'] = pending
        messages.error(request, f'인증 코드가 올바르지 않습니다. (남은 시도 {remaining}회)')
        return redirect('common:admin_otp')

    # GET — 코드 발송(쿨다운 고려) 후 폼 표시
    _send_code(force=False)

    masked = ''
    if recipient and '@' in recipient:
        name, domain = recipient.split('@', 1)
        masked = (name[:2] + '***') if len(name) > 2 else (name[:1] + '***')
        masked += '@' + domain

    return render(request, 'common/admin_otp.html', {
        'recipient_masked': masked,
        'window_minutes': ADMIN_OTP_WINDOW_SECONDS // 60,
        'code_ttl_minutes': ADMIN_OTP_CODE_TTL_SECONDS // 60,
        'client_ip': ip,
    })


@admin_otp_required
def admin_dashboard(request):
    """관리자 대시보드"""
    # 통계 정보
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    # 회원 등급별 통계
    from common.models import Profile
    rank_stats = Profile.objects.values('rank').annotate(count=Count('rank'))

    # 이메일 인증 통계
    email_verified_users = Profile.objects.filter(is_email_verified=True).count()

    # 최근 가입 사용자
    recent_users = User.objects.select_related('profile').order_by('-date_joined')[:10]

    # 칼럼 자동 작성 내역 (테크창 연구팀 봇)
    from community.models import Question
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    bot_cols = Question.objects.filter(
        is_deleted=False, author__username='techchang연구팀'
    ).select_related('category')
    column_total = bot_cols.count()
    column_week = bot_cols.filter(create_date__date__gte=week_ago).count()
    column_today = bot_cols.filter(create_date__date=today).count()
    recent_columns = bot_cols.order_by('-create_date')[:10]

    # 포트폴리오 게시 승인 대기 건수
    from community.models import Portfolio, PortfolioCollection
    portfolio_pending_count = (
        PortfolioCollection.objects.filter(approval_status='pending').count()
        + Portfolio.objects.filter(approval_status='pending').count()
    )

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': total_users - active_users,
        'email_verified_users': email_verified_users,
        'rank_stats': rank_stats,
        'recent_users': recent_users,
        'column_total': column_total,
        'column_week': column_week,
        'column_today': column_today,
        'recent_columns': recent_columns,
        'portfolio_pending_count': portfolio_pending_count,
    }

    return render(request, 'common/admin_dashboard.html', context)


# ====================================================================== #
#  포트폴리오 게시 승인 - 장난성 포트폴리오 방지
#  구성원이 게시 요청한 포트폴리오를 관리자가 내용 검토 후 승인/반려한다.
#  승인되어야만 구성원 목록 및 상세 페이지에 공개된다.
# ====================================================================== #
def _get_portfolio_for_review(kind, obj_id):
    """kind('collection' | 'legacy')에 따라 승인 대상 객체를 반환."""
    from community.models import Portfolio, PortfolioCollection
    if kind == 'collection':
        return get_object_or_404(PortfolioCollection, id=obj_id)
    elif kind == 'legacy':
        return get_object_or_404(Portfolio, id=obj_id)
    return None


@admin_required
def admin_portfolio_approval(request):
    """포트폴리오 게시 승인 대기 목록"""
    from community.models import Portfolio, PortfolioCollection

    pending_collections = PortfolioCollection.objects.filter(
        approval_status='pending'
    ).select_related('user').order_by('approval_requested_at')

    pending_legacy = Portfolio.objects.filter(
        approval_status='pending'
    ).select_related('user').order_by('approval_requested_at')

    # 현재 승인되어 공개 중인 포트폴리오 (사유와 함께 회수 가능)
    approved_collections = PortfolioCollection.objects.filter(
        approval_status='approved'
    ).select_related('user', 'reviewed_by').order_by('-reviewed_at')

    approved_legacy = Portfolio.objects.filter(
        approval_status='approved'
    ).select_related('user', 'reviewed_by').order_by('-reviewed_at')

    # 최근 처리 내역 (승인/반려) - 신규 컬렉션 + 레거시 포트폴리오 통합
    recent_collections = PortfolioCollection.objects.filter(
        approval_status__in=['approved', 'rejected']
    ).select_related('user', 'reviewed_by').order_by('-reviewed_at')

    recent_legacy = Portfolio.objects.filter(
        approval_status__in=['approved', 'rejected']
    ).select_related('user', 'reviewed_by').order_by('-reviewed_at')

    recent_items = []
    for c in recent_collections:
        recent_items.append({
            'name': c.portfolio_name,
            'is_legacy': False,
            'username': c.user.username,
            'approval_status': c.approval_status,
            'rejection_reason': c.rejection_reason,
            'reviewed_by': c.reviewed_by,
            'reviewed_at': c.reviewed_at,
        })
    for p in recent_legacy:
        recent_items.append({
            'name': '%s의 포트폴리오' % p.get_display_name(),
            'is_legacy': True,
            'username': p.user.username,
            'approval_status': p.approval_status,
            'rejection_reason': p.rejection_reason,
            'reviewed_by': p.reviewed_by,
            'reviewed_at': p.reviewed_at,
        })

    # 검토일 기준 최신순 정렬 (검토일 없는 항목은 뒤로)
    from datetime import datetime, timezone as _tz
    recent_items.sort(
        key=lambda x: x['reviewed_at'] or datetime.min.replace(tzinfo=_tz.utc),
        reverse=True,
    )
    recent_items = recent_items[:20]

    context = {
        'pending_collections': pending_collections,
        'pending_legacy': pending_legacy,
        'pending_count': pending_collections.count() + pending_legacy.count(),
        'approved_collections': approved_collections,
        'approved_legacy': approved_legacy,
        'approved_count': approved_collections.count() + approved_legacy.count(),
        'recent_items': recent_items,
    }
    return render(request, 'common/admin_portfolio_approval.html', context)


@admin_required
@require_POST
def admin_portfolio_approve(request, kind, obj_id):
    """포트폴리오 게시 승인"""
    obj = _get_portfolio_for_review(kind, obj_id)
    if obj is None:
        messages.error(request, '유효하지 않은 요청입니다.')
        return redirect('common:admin_portfolio_approval')

    obj.approval_status = 'approved'
    obj.reviewed_at = timezone.now()
    obj.reviewed_by = request.user
    obj.rejection_reason = ''
    if kind == 'collection':
        obj.is_published = True
        obj.save(update_fields=['approval_status', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'is_published'])
        name = obj.portfolio_name
    else:
        obj.is_public = True
        obj.save(update_fields=['approval_status', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'is_public'])
        name = f'{obj.user.username}의 포트폴리오'

    messages.success(request, f'"{name}"을(를) 승인하여 공개했습니다.')
    return redirect('common:admin_portfolio_approval')


@admin_required
@require_POST
def admin_portfolio_reject(request, kind, obj_id):
    """포트폴리오 게시 반려"""
    obj = _get_portfolio_for_review(kind, obj_id)
    if obj is None:
        messages.error(request, '유효하지 않은 요청입니다.')
        return redirect('common:admin_portfolio_approval')

    reason = request.POST.get('reason', '').strip()
    was_approved = obj.approval_status == 'approved'

    obj.approval_status = 'rejected'
    obj.reviewed_at = timezone.now()
    obj.reviewed_by = request.user
    obj.rejection_reason = reason
    if kind == 'collection':
        obj.is_published = False
        obj.save(update_fields=['approval_status', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'is_published'])
        name = obj.portfolio_name
    else:
        obj.is_public = False
        obj.save(update_fields=['approval_status', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'is_public'])
        name = f'{obj.user.username}의 포트폴리오'

    if was_approved:
        messages.success(request, f'"{name}"의 게시를 회수하여 비공개로 전환했습니다. 작성자는 수정 후 다시 게시 요청을 해야 합니다.')
    else:
        messages.success(request, f'"{name}"을(를) 반려했습니다.')
    return redirect('common:admin_portfolio_approval')


def _dispatch_finding_fix(finding):
    """승인된 지적사항을 GitHub repository_dispatch 로 보내 auto-fix 워크플로를 트리거.

    반환: (성공여부: bool, 메시지: str). 토큰 미설정/요청 실패 시 False.
    """
    token = getattr(settings, 'GITHUB_DISPATCH_TOKEN', '')
    repo = getattr(settings, 'GITHUB_REPO', '')
    if not token or not repo:
        return False, 'GITHUB_DISPATCH_TOKEN/GITHUB_REPO 미설정 — PR 트리거를 건너뜁니다.'

    try:
        resp = requests.post(
            f'https://api.github.com/repos/{repo}/dispatches',
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            json={
                'event_type': 'log-finding-approved',
                'client_payload': {
                    'finding_id': finding.id,
                    'title': finding.title,
                    'cause': finding.cause,
                    'action': finding.action,
                    'severity': finding.severity,
                },
            },
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f'GitHub 요청 실패: {e}'

    if resp.status_code == 204:
        return True, 'GitHub auto-fix 워크플로를 트리거했습니다.'
    return False, f'GitHub 응답 오류 {resp.status_code}: {resp.text[:200]}'


@admin_required
@require_POST
def finding_approve(request, finding_id):
    """AI 지적사항 승인 → GitHub auto-fix 워크플로 트리거."""
    from .models import LogFinding

    finding = LogFinding.objects.filter(pk=finding_id).first()
    if finding is None:
        messages.error(request, '존재하지 않는 지적사항입니다.')
        return redirect('common:server_monitor')

    finding.status = LogFinding.STATUS_APPROVED
    finding.decided_at = timezone.now()
    finding.decided_by = request.user

    ok, detail = _dispatch_finding_fix(finding)
    if ok:
        finding.status = LogFinding.STATUS_DISPATCHED
        finding.note = detail[:300]
        messages.success(request, f'"{finding.title}" 승인 — {detail}')
    else:
        finding.note = detail[:300]
        messages.warning(request, f'"{finding.title}" 승인은 기록했으나 PR 트리거 실패: {detail}')

    finding.save(update_fields=['status', 'decided_at', 'decided_by', 'note'])
    return redirect('common:server_monitor')


@admin_required
@require_POST
def finding_reject(request, finding_id):
    """AI 지적사항 거부 (PR 생성 안 함)."""
    from .models import LogFinding

    finding = LogFinding.objects.filter(pk=finding_id).first()
    if finding is None:
        messages.error(request, '존재하지 않는 지적사항입니다.')
        return redirect('common:server_monitor')

    finding.status = LogFinding.STATUS_REJECTED
    finding.decided_at = timezone.now()
    finding.decided_by = request.user
    finding.note = request.POST.get('reason', '').strip()[:300]
    finding.save(update_fields=['status', 'decided_at', 'decided_by', 'note'])
    messages.success(request, f'"{finding.title}"을(를) 거부했습니다.')
    return redirect('common:server_monitor')


@admin_required
def admin_user_list(request):
    """사용자 목록 관리"""
    # 검색 및 필터링
    search_query = request.GET.get('search', '')
    rank_filter = request.GET.get('rank', '')
    status_filter = request.GET.get('status', '')

    users = User.objects.select_related('profile').order_by('-date_joined')

    # 검색
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(profile__nickname__icontains=search_query)
        )

    # 회원 등급 필터
    if rank_filter:
        users = users.filter(profile__rank=rank_filter)

    # 활성화 상태 필터
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)

    # 페이지네이션
    from django.core.paginator import Paginator
    paginator = Paginator(users, 20)  # 페이지당 20명
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'rank_filter': rank_filter,
        'status_filter': status_filter,
        'rank_choices': Profile.RANK_CHOICES,
    }

    return render(request, 'common/admin_user_list.html', context)


@admin_required
@require_POST
def admin_change_rank(request, user_id):
    """사용자 등급 변경"""
    user = get_object_or_404(User, id=user_id)
    new_rank = request.POST.get('rank')

    if new_rank not in dict(Profile.RANK_CHOICES).keys():
        return JsonResponse({'success': False, 'message': '유효하지 않은 등급입니다.'})

    profile, created = Profile.objects.get_or_create(user=user)
    old_rank = profile.rank_display
    profile.rank = new_rank
    profile.save()

    messages.success(request, f'{user.username}님의 등급이 {old_rank}에서 {profile.rank_display}(으)로 변경되었습니다.')

    return JsonResponse({
        'success': True,
        'message': '등급이 변경되었습니다.',
        'new_rank': profile.rank_display,
        'new_rank_class': profile.rank_badge_class
    })


@admin_required
@require_POST
def admin_toggle_active(request, user_id):
    """사용자 활성화/비활성화"""
    user = get_object_or_404(User, id=user_id)

    # 자기 자신은 비활성화할 수 없음
    if user.id == request.user.id:
        return JsonResponse({'success': False, 'message': '자기 자신은 비활성화할 수 없습니다.'})

    # 슈퍼유저는 비활성화할 수 없음
    if user.is_superuser:
        return JsonResponse({'success': False, 'message': '슈퍼유저는 비활성화할 수 없습니다.'})

    user.is_active = not user.is_active
    user.save()

    status = '활성화' if user.is_active else '비활성화'
    messages.success(request, f'{user.username}님이 {status}되었습니다.')

    return JsonResponse({
        'success': True,
        'message': f'사용자가 {status}되었습니다.',
        'is_active': user.is_active
    })


@admin_required
def admin_user_detail(request, user_id):
    """사용자 상세 정보 및 수정"""
    user = get_object_or_404(User, id=user_id)
    profile, created = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        # 비밀번호 재설정 (선택적)
        pwd1 = request.POST.get('new_password', '').strip()
        pwd2 = request.POST.get('new_password_confirm', '').strip()

        if pwd1 or pwd2:
            if pwd1 != pwd2:
                messages.error(request, '새 비밀번호가 일치하지 않습니다.')
                return redirect('common:admin_user_detail', user_id=user.id)
            if len(pwd1) < 8:
                messages.error(request, '비밀번호는 8자 이상이어야 합니다.')
                return redirect('common:admin_user_detail', user_id=user.id)
            user.set_password(pwd1)
            messages.success(request, f'{user.username}님의 비밀번호가 재설정되었습니다.')

        # 닉네임 수정
        nickname = request.POST.get('nickname', '').strip()
        profile.nickname = nickname

        # 이메일 수정
        email = request.POST.get('email', '').strip()
        if email:
            user.email = email

        # 등급 수정
        rank = request.POST.get('rank')
        if rank in dict(Profile.RANK_CHOICES).keys():
            profile.rank = rank

        # staff 권한 수정
        if request.user.is_superuser:
            is_staff = request.POST.get('is_staff') == 'on'
            user.is_staff = is_staff

        user.save()
        profile.save()

        messages.success(request, f'{user.username}님의 정보가 수정되었습니다.')
        return redirect('common:admin_user_detail', user_id=user.id)

    # 사용자 활동 통계
    from community.models import Question, Answer, Comment
    question_count = Question.objects.filter(author=user).count()
    answer_count = Answer.objects.filter(author=user).count()
    comment_count = Comment.objects.filter(author=user).count()

    context = {
        'target_user': user,
        'profile': profile,
        'rank_choices': Profile.RANK_CHOICES,
        'question_count': question_count,
        'answer_count': answer_count,
        'comment_count': comment_count,
    }

    return render(request, 'common/admin_user_detail.html', context)


@login_required
def daily_checkin(request):
    """일일 출석 체크"""
    from .models import DailyCheckIn, PointHistory, Profile
    from datetime import date
    from django.http import JsonResponse
    from django.db import transaction

    # AJAX 요청인지 확인
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'

    today = date.today()
    user = request.user

    # 프로필 확인 및 생성
    profile, _ = Profile.objects.get_or_create(user=user)

    # atomic + get_or_create로 동시 요청 중복 지급 방지
    with transaction.atomic():
        checkin, created = DailyCheckIn.objects.get_or_create(
            user=user,
            check_in_date=today,
            defaults={'points_earned': 5}
        )

    if not created:
        if is_ajax:
            return JsonResponse({
                'success': False,
                'message': '오늘 이미 출석체크를 완료했습니다!'
            })
        messages.warning(request, '오늘 이미 출석체크를 완료했습니다!')
    else:
        points_earned = checkin.points_earned
        award_points(
            user=user,
            amount=points_earned,
            description='일일 출석 체크',
            reason='checkin'
        )

        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': '출석 체크 완료!',
                'points': points_earned
            })
        messages.success(request, f'출석 체크 완료! {points_earned} 포인트를 획득했습니다!')

    return redirect('community:index')


@login_required
def emoticon_shop(request):
    """이모티콘 상점"""
    from .models import Emoticon, UserEmoticon, Profile

    # 프로필 확인 및 생성
    profile, _ = Profile.objects.get_or_create(user=request.user)

    # 판매 중인 이모티콘 목록
    emoticons = Emoticon.objects.filter(is_available=True).order_by('price')

    # 사용자가 구매한 이모티콘 목록
    owned_emoticon_ids = UserEmoticon.objects.filter(
        user=request.user
    ).values_list('emoticon_id', flat=True)

    context = {
        'emoticons': emoticons,
        'owned_emoticon_ids': list(owned_emoticon_ids),
        'user_points': profile.points,
    }

    return render(request, 'common/emoticon_shop.html', context)


@login_required
def purchase_emoticon(request, emoticon_id):
    """이모티콘 구매"""
    from .models import Emoticon, UserEmoticon, PointHistory, Profile
    from django.db import transaction

    emoticon = get_object_or_404(Emoticon, id=emoticon_id, is_available=True)
    user = request.user

    # 프로필 확인 및 생성
    profile, _ = Profile.objects.get_or_create(user=user)

    # 이미 구매했는지 확인
    if UserEmoticon.objects.filter(user=user, emoticon=emoticon).exists():
        messages.warning(request, '이미 구매한 이모티콘입니다!')
        return redirect('common:emoticon_shop')

    # 포인트가 충분한지 확인
    if profile.points < emoticon.price:
        messages.error(request, f'포인트가 부족합니다! (필요: {emoticon.price}P, 보유: {profile.points}P)')
        return redirect('common:emoticon_shop')

    # 구매 처리
    with transaction.atomic():
        # 포인트 차감 - 유틸리티 함수 사용
        deduct_points(
            user=user,
            amount=emoticon.price,
            description=f'이모티콘 구매: {emoticon.name}',
            reason='purchase'
        )

        # 이모티콘 구매 기록
        UserEmoticon.objects.create(user=user, emoticon=emoticon)

    messages.success(request, f'{emoticon.name} 이모티콘을 구매했습니다!')
    return redirect('common:emoticon_shop')


@login_required
def select_emoticon(request, emoticon_id):
    """이모티콘 선택 (닉네임 옆에 표시)"""
    from .models import Emoticon, UserEmoticon, Profile

    user = request.user

    # 프로필 확인 및 생성
    profile, _ = Profile.objects.get_or_create(user=user)

    if emoticon_id == 0:
        # 이모티콘 해제
        profile.selected_emoticon = None
        profile.save()
        messages.success(request, '이모티콘을 해제했습니다.')
    else:
        emoticon = get_object_or_404(Emoticon, id=emoticon_id)

        # 구매한 이모티콘인지 확인
        if not UserEmoticon.objects.filter(user=user, emoticon=emoticon).exists():
            messages.error(request, '구매하지 않은 이모티콘입니다!')
            return redirect('common:emoticon_shop')

        # 이모티콘 선택
        profile.selected_emoticon = emoticon
        profile.save()
        messages.success(request, f'{emoticon.name} 이모티콘을 선택했습니다!')

    return redirect('common:emoticon_shop')


@login_required
def point_history(request):
    """포인트 히스토리"""
    from .models import PointHistory, Profile
    from django.core.paginator import Paginator

    # 프로필 확인 및 생성
    profile, _ = Profile.objects.get_or_create(user=request.user)

    history_list = PointHistory.objects.filter(user=request.user).order_by('-created_at')

    paginator = Paginator(history_list, 20)
    page = request.GET.get('page', 1)
    page_obj = paginator.get_page(page)

    context = {
        'page_obj': page_obj,
        'user_points': profile.points,
    }

    return render(request, 'common/point_history.html', context)


# ==================== IP 차단 관리 ====================

@admin_required
def admin_blocked_ip_list(request):
    """차단된 IP 목록"""
    from .models import BlockedIP
    from django.core.paginator import Paginator

    # 활성 상태 필터
    status_filter = request.GET.get('status', 'active')
    search_query = request.GET.get('search', '')

    ip_list = BlockedIP.objects.select_related('blocked_by').order_by('-created_at')

    # 상태 필터
    if status_filter == 'active':
        ip_list = ip_list.filter(is_active=True)
    elif status_filter == 'inactive':
        ip_list = ip_list.filter(is_active=False)

    # 검색
    if search_query:
        ip_list = ip_list.filter(
            Q(ip_address__icontains=search_query) |
            Q(reason__icontains=search_query)
        )

    paginator = Paginator(ip_list, 50)
    page = request.GET.get('page', 1)
    page_obj = paginator.get_page(page)

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
    }

    return render(request, 'common/admin_blocked_ip_list.html', context)


@admin_required
@require_POST
def admin_block_ip(request):
    """IP 차단"""
    from .models import BlockedIP

    ip_address = request.POST.get('ip_address', '').strip()
    reason = request.POST.get('reason', '').strip()

    if not ip_address:
        messages.error(request, 'IP 주소를 입력해주세요.')
        return redirect('common:admin_dashboard')

    # 이미 차단된 IP인지 확인
    existing = BlockedIP.objects.filter(ip_address=ip_address).first()
    if existing:
        if existing.is_active:
            messages.warning(request, f'{ip_address}는 이미 차단된 IP입니다.')
        else:
            # 비활성화된 IP를 다시 활성화
            existing.is_active = True
            existing.reason = reason or '관리자에 의한 재차단'
            existing.blocked_by = request.user
            existing.save()
            messages.success(request, f'{ip_address}를 다시 차단했습니다.')
        return redirect('common:admin_blocked_ip_list')

    # 새 IP 차단
    BlockedIP.objects.create(
        ip_address=ip_address,
        reason=reason or '관리자에 의한 차단',
        blocked_by=request.user,
        is_active=True
    )

    messages.success(request, f'{ip_address}를 차단했습니다.')
    return redirect(request.META.get('HTTP_REFERER', 'common:admin_blocked_ip_list'))


@admin_required
@require_POST
def admin_unblock_ip(request, ip_id):
    """IP 차단 해제"""
    from .models import BlockedIP

    blocked_ip = get_object_or_404(BlockedIP, id=ip_id)
    ip_address = blocked_ip.ip_address
    blocked_ip.is_active = False
    blocked_ip.save()

    messages.success(request, f'{ip_address}의 차단을 해제했습니다.')
    return redirect(request.META.get('HTTP_REFERER', 'common:admin_blocked_ip_list'))


# ==================== 비밀번호 찾기 ====================
def password_reset(request):
    """비밀번호 찾기 - 임시 비밀번호 발송"""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip().lower()

        if not username or not email:
            messages.error(request, '사용자명과 이메일을 모두 입력해주세요.')
            return render(request, 'common/password_reset.html')

        # 사용자 확인
        try:
            user = User.objects.get(username=username, email=email)
        except User.DoesNotExist:
            messages.error(request, '일치하는 사용자 정보를 찾을 수 없습니다. 사용자명과 이메일을 확인해주세요.')
            return render(request, 'common/password_reset.html')

        # 이메일 인증 여부 확인 (미인증 계정도 동일 메시지로 처리 — 계정 존재 여부 노출 방지)
        try:
            profile = user.profile
            if not profile.is_email_verified:
                messages.error(request, '일치하는 사용자 정보를 찾을 수 없습니다. 사용자명과 이메일을 확인해주세요.')
                return render(request, 'common/password_reset.html')
        except Profile.DoesNotExist:
            messages.error(request, '일치하는 사용자 정보를 찾을 수 없습니다. 사용자명과 이메일을 확인해주세요.')
            return render(request, 'common/password_reset.html')

        # 임시 비밀번호 생성 (암호학적으로 안전한 12자리)
        temp_password = secrets.token_urlsafe(12)

        # 사용자 비밀번호 변경
        user.set_password(temp_password)
        user.save()

        # 이메일 발송
        try:
            send_mail(
                subject='[테크창] 임시 비밀번호 안내',
                message=f'''
안녕하세요, {username}님!

비밀번호 찾기 요청에 따라 임시 비밀번호를 발송합니다.

임시 비밀번호: {temp_password}

로그인 후 반드시 비밀번호를 변경해주세요.

감사합니다.
- 테크창 운영팀
                ''',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            messages.success(request, f'{email}로 임시 비밀번호가 발송되었습니다. 이메일을 확인해주세요.')
            return redirect('common:login')
        except Exception:
            logger.exception("임시 비밀번호 이메일 발송 실패")
            messages.error(request, '임시 비밀번호 발송 중 오류가 발생했습니다. 관리자에게 문의해주세요.')
            return render(request, 'common/password_reset.html')

    return render(request, 'common/password_reset.html')


# ==================== 포인트 랭킹 ====================
def point_ranking(request):
    """포인트 랭킹 페이지 (N+1 쿼리 최적화)"""
    from .models import Profile

    # N+1 방지: select_related로 user, selected_emoticon 조인
    # only()로 필요한 필드만 가져와 성능 향상
    top_users = Profile.objects.select_related('user', 'selected_emoticon').filter(
        points__gt=0
    ).exclude(
        user__is_staff=True
    ).exclude(
        user__is_superuser=True
    ).only(
        'user__username', 'user__email',
        'nickname', 'points', 'profile_image',
        'selected_emoticon__name', 'selected_emoticon__image'
    ).order_by('-points')[:100]

    # 현재 로그인한 사용자의 순위 (있는 경우)
    current_user_rank = None
    current_user_profile = None
    if request.user.is_authenticated and not request.user.is_staff and not request.user.is_superuser:
        try:
            current_user_profile = Profile.objects.select_related('user').only(
                'user__username', 'nickname', 'points', 'profile_image'
            ).get(user=request.user)
            # 현재 사용자보다 포인트가 높은 사용자 수 + 1 (0포인트 및 스태프 제외)
            current_user_rank = Profile.objects.filter(
                points__gt=current_user_profile.points
            ).exclude(user__is_staff=True).exclude(user__is_superuser=True).count() + 1
        except Profile.DoesNotExist:
            pass

    context = {
        'top_users': top_users,
        'current_user_rank': current_user_rank,
        'current_user_profile': current_user_profile,
    }

    return render(request, 'common/point_ranking.html', context)


@admin_otp_required
def server_monitor(request):
    """서버 모니터링 대시보드 (관리자 전용 + 이메일 OTP 2차 인증)"""
    from common.management.commands.send_log_report import Command as ReportCmd
    from community.models import Question, DailyVisitor
    from datetime import date

    hours = int(request.GET.get('hours', 24))
    cmd = ReportCmd()

    db_stats       = cmd._collect_db_stats()
    journal_stats  = cmd._collect_journal(hours)
    security_stats = cmd._collect_security_logs(hours)
    sys_stats      = cmd._collect_system_stats()

    # AI 에러 분석관 — 대시보드는 60초마다 자동 새로고침되므로 Claude 호출을 캐시한다.
    # (성공/스킵 30분, 호출 실패 5분 캐시) → 새 에러는 최대 30분 내 반영되며 API 비용을 제한.
    from django.core.cache import cache
    ai_key = f'monitor_ai_analysis_{hours}'
    ai_analysis = cache.get(ai_key)
    if ai_analysis is None:
        ai_analysis = cmd._analyze_errors(hours, journal_stats)
        cache.set(ai_key, ai_analysis, 1800 if ai_analysis.get('available') else 300)

    # 분석된 findings 를 DB에 저장(중복 지문은 무시) → 승인 대기 목록으로 노출
    from .models import LogFinding
    if ai_analysis.get('available') and not ai_analysis.get('skipped'):
        for f in ai_analysis.get('findings', []):
            if isinstance(f, dict):
                LogFinding.record(f, ai_analysis.get('severity', ''), ai_analysis.get('overview', ''))
    pending_findings = LogFinding.objects.filter(status=LogFinding.STATUS_PENDING)
    recent_decided = LogFinding.objects.exclude(status=LogFinding.STATUS_PENDING)[:10]

    # 최근 7일 방문자 추이
    today = date.today()
    visitor_trend = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        try:
            vc = DailyVisitor.objects.filter(date=d).first()
            visitor_trend.append({'date': d.strftime('%m/%d'), 'count': vc.visitor_count if vc else 0})
        except Exception:
            visitor_trend.append({'date': d.strftime('%m/%d'), 'count': 0})

    # 최근 7일 질문 추이
    question_trend = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        cnt = Question.objects.filter(is_deleted=False, create_date__date=d).count()
        question_trend.append({'date': d.strftime('%m/%d'), 'count': cnt})

    context = {
        'hours': hours,
        'db': db_stats,
        'journal': journal_stats,
        'security': security_stats,
        'sys': sys_stats,
        'ai': ai_analysis,
        'visitor_trend': visitor_trend,
        'question_trend': question_trend,
        'pending_findings': pending_findings,
        'recent_decided': recent_decided,
    }
    return render(request, 'common/server_monitor.html', context)


@admin_otp_required
def server_logs(request):
    """실시간 로그 전용 뷰어 페이지 (대시보드에서 분리, 관리자 + OTP)."""
    return render(request, 'common/server_logs.html', {})


@admin_required
def server_live_logs(request):
    """
    실시간 로그 조회 (관리자 전용, 읽기 전용 JSON).
    대시보드 라이브 로그 뷰어가 폴링한다. 어떤 입력도 받지 않고 조회만 수행한다.
    OTP 미인증/IP 불일치 시에는 로그를 노출하지 않고 403으로 차단한다 (AJAX이므로 리다이렉트 대신 JSON).
    """
    from django.http import JsonResponse
    from common.management.commands.send_log_report import Command as ReportCmd
    from datetime import datetime as _dt

    if not _admin_otp_session_ok(request):
        return JsonResponse(
            {'available': False, 'lines': [], 'error': 'reauth_required',
             'message': '재인증이 필요합니다. 페이지를 새로고침하세요.'},
            status=403,
        )

    lines = request.GET.get('lines', 120)
    data = ReportCmd()._tail_logs(lines)
    data['server_time'] = _dt.now().strftime('%H:%M:%S')
    return JsonResponse(data)


@require_POST
@admin_otp_required
def send_monitor_email(request):
    """모니터 대시보드에서 즉시 이메일 발송"""
    import os
    from common.management.commands.send_log_report import Command as ReportCmd
    from datetime import datetime as dt
    from django.core.mail import send_mail as _send_mail

    hours = int(request.POST.get('hours', 24))
    recipient = os.environ.get('DJANGO_ADMIN_EMAIL', '')
    if not recipient and settings.ADMINS:
        recipient = settings.ADMINS[0][1]

    if not recipient:
        messages.error(request, '수신자 이메일 미설정 (.env DJANGO_ADMIN_EMAIL 확인)')
        return redirect('common:server_monitor')

    try:
        report = ReportCmd()._build_report(hours)
        _send_mail(
            subject=f'[테크창] 서버 리포트 {dt.now():%Y-%m-%d %H:%M} ({hours}h)',
            message=report['text'],
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            html_message=report['html'],
            fail_silently=False,
        )
        messages.success(request, f'리포트를 {recipient}로 발송했습니다.')
    except Exception as e:
        messages.error(request, f'발송 실패: {e}')

    return redirect(f'/common/admin/monitor/?hours={hours}')


def toggle_version(request):
    """PC/모바일 버전 전환"""
    current = request.COOKIES.get('force_version', '')

    if current == 'mobile':
        new_version = 'desktop'
    elif current == 'desktop':
        new_version = 'mobile'
    else:
        new_version = 'desktop' if getattr(request, 'is_mobile', False) else 'mobile'

    referer = request.META.get('HTTP_REFERER', '/')
    if not url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        referer = '/'
    response = redirect(referer)
    response.set_cookie('force_version', new_version, max_age=365 * 24 * 3600, samesite='Lax')
    return response


def reset_version(request):
    """자동 감지 모드로 되돌리기"""
    referer = request.META.get('HTTP_REFERER', '/')
    if not url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        referer = '/'
    response = redirect(referer)
    response.delete_cookie('force_version')
    return response
