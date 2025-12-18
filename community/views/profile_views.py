from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from common.models import Profile

from ..models import Question, Answer


@login_required(login_url='common:login')
def profile(request, user_id):
    """사용자 프로필"""
    profile_user = get_object_or_404(User, pk=user_id)

    # 사용자가 작성한 질문
    question_list = Question.objects.filter(author=profile_user).order_by('-create_date')
    question_paginator = Paginator(question_list, 5)
    question_page = request.GET.get('question_page', '1')
    question_page_obj = question_paginator.get_page(question_page)

    # 사용자가 작성한 댓글 (원래 답변 기능)
    # 페이지네이션 없이 전체 리스트, 최신이 맨 아래 (오래된 것부터)
    comment_list = Answer.objects.filter(author=profile_user).order_by('create_date')

    context = {
        'profile_user': profile_user,
        'question_list': question_page_obj,
        'comment_list': comment_list,
        'question_page': question_page,
    }
    return render(request, 'community/profile.html', context)


@login_required(login_url='common:login')
def profile_update(request):
    """개인정보 수정"""
    if request.method == 'POST':
        # 이메일 업데이트
        email = request.POST.get('email', '')
        if email:
            request.user.email = email
            request.user.save()

        # 프로필 가져오기 또는 생성
        profile, created = Profile.objects.get_or_create(user=request.user)

        # 닉네임 업데이트
        nickname = request.POST.get('nickname', '')
        profile.nickname = nickname

        # 프로필 이미지 업데이트
        if 'profile_image' in request.FILES:
            profile.profile_image = request.FILES['profile_image']

        profile.save()

        messages.success(request, '개인정보가 성공적으로 수정되었습니다.')
        return redirect('community:profile', user_id=request.user.id)

    return redirect('community:profile', user_id=request.user.id)


@login_required(login_url='common:login')
def password_change(request):
    """비밀번호 변경"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # 비밀번호 변경 후 세션 유지
            update_session_auth_hash(request, user)
            messages.success(request, '비밀번호가 성공적으로 변경되었습니다.')
            return redirect('community:profile', user_id=request.user.id)
        else:
            # 에러 메시지 표시
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)

    return redirect('community:profile', user_id=request.user.id)