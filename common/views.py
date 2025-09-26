
# from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from common.forms import UserForm
from .models import Profile


def logout_view(request):
    logout(request)
    return redirect('index')

def signup(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
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
