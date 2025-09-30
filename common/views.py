
# from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from django.core.cache import cache
import json
import logging
from django.contrib.auth.models import User
from common.forms import UserForm, ProfileForm
from .models import Profile, EmailVerification


logger = logging.getLogger(__name__)


def logout_view(request):
    logout(request)
    return redirect('index')

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
            return redirect('index')
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
            from pybo.models import Question, Answer
            
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
            return redirect('pybo:index')
            
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

    ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR')
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
        return JsonResponse({'success': False, 'message': '이메일 발송 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'}, status=500)

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

    if verification.code != code:
        remaining = verification.increment_attempts()
        if remaining <= 0:
            verification.delete()
            return JsonResponse({'success': False, 'message': '인증 시도 횟수를 초과했습니다. 새로운 코드를 요청해주세요.'}, status=429)
        return JsonResponse({'success': False, 'message': f'인증 코드가 틀렸습니다. (남은 시도: {remaining}회)'}, status=400)

    verification.mark_verified()
    return JsonResponse({'success': True, 'message': '이메일 인증이 완료되었습니다.'})

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
            
            # 프로필 생성
            nickname = form.cleaned_data.get('nickname')
            if nickname:
                profile, created = Profile.objects.get_or_create(user=user)
                profile.nickname = nickname
                profile.save()
            
            # 인증 기록 삭제
            verification.delete()
            
            # 자동 로그인
            username = form.cleaned_data.get('username')
            raw_password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=raw_password)
            login(request, user)
            
            messages.success(request, '회원가입이 완료되었습니다! 테크창에 오신 것을 환영합니다.')
            return redirect('pybo:index')
    else:
        form = UserForm()
    
    return render(request, 'common/signup_with_verification.html', {'form': form})
