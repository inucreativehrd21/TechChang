
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
import requests
import secrets
from datetime import timedelta
from django.contrib.auth.models import User
from common.forms import UserForm, ProfileForm
from .models import Profile, EmailVerification, KakaoUser


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


# ==================== 카카오 로그인 ====================
def kakao_login(request):
    """카카오 로그인 시작 (인가 코드 요청)"""
    # 환경변수에서 카카오 REST API 키 가져오기
    kakao_rest_api_key = settings.KAKAO_REST_API_KEY

    # 도메인 기반 redirect_uri 생성
    host = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    redirect_uri = f"{scheme}://{host}/common/kakao/callback/"

    kakao_auth_url = (
        f"https://kauth.kakao.com/oauth/authorize"
        f"?client_id={kakao_rest_api_key}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
    )

    return redirect(kakao_auth_url)


def kakao_callback(request):
    """카카오 로그인 콜백 (토큰 및 사용자 정보 받기)"""
    code = request.GET.get('code')

    if not code:
        messages.error(request, '카카오 로그인에 실패했습니다.')
        return redirect('common:login')

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
        return redirect('pybo:index')

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
            return redirect('index')
        return view_func(request, *args, **kwargs)
    return wrapper


@admin_required
def admin_dashboard(request):
    """관리자 대시보드"""
    # 통계 정보
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    # 회원 등급별 통계
    from common.models import Profile
    rank_stats = Profile.objects.values('rank').annotate(count=Count('rank'))

    # 최근 가입 사용자
    recent_users = User.objects.select_related('profile').order_by('-date_joined')[:10]

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': total_users - active_users,
        'rank_stats': rank_stats,
        'recent_users': recent_users,
    }

    return render(request, 'common/admin_dashboard.html', context)


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

    # AJAX 요청인지 확인
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'

    today = date.today()
    user = request.user

    # 프로필 확인 및 생성
    profile, _ = Profile.objects.get_or_create(user=user)

    # 오늘 이미 출석했는지 확인
    already_checked = DailyCheckIn.objects.filter(
        user=user,
        check_in_date=today
    ).exists()

    if already_checked:
        if is_ajax:
            return JsonResponse({
                'success': False,
                'message': '오늘 이미 출석체크를 완료했습니다!'
            })
        messages.warning(request, '오늘 이미 출석체크를 완료했습니다!')
    else:
        # 출석 체크 생성
        points_earned = 5
        DailyCheckIn.objects.create(
            user=user,
            points_earned=points_earned
        )

        # 포인트 지급
        profile.points += points_earned
        profile.save()

        # 포인트 히스토리 기록
        PointHistory.objects.create(
            user=user,
            amount=points_earned,
            reason='checkin',
            description='일일 출석 체크'
        )

        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': '출석 체크 완료!',
                'points': points_earned
            })
        messages.success(request, f'출석 체크 완료! {points_earned} 포인트를 획득했습니다!')

    return redirect(request.META.get('HTTP_REFERER', 'community:index'))


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
        # 포인트 차감
        profile.points -= emoticon.price
        profile.save()

        # 이모티콘 구매 기록
        UserEmoticon.objects.create(user=user, emoticon=emoticon)

        # 포인트 히스토리 기록
        PointHistory.objects.create(
            user=user,
            amount=-emoticon.price,
            reason='purchase',
            description=f'이모티콘 구매: {emoticon.name}'
        )

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
        return redirect(request.META.get('HTTP_REFERER', 'common:admin_dashboard'))

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
        return redirect(request.META.get('HTTP_REFERER', 'common:admin_blocked_ip_list'))

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
