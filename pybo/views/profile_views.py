from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.models import User

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
    return render(request, 'pybo/profile.html', context)