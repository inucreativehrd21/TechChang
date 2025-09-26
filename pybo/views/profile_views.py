from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.models import User

from ..models import Question, Answer, Comment


@login_required(login_url='common:login')
def profile(request, user_id):
    """사용자 프로필"""
    profile_user = get_object_or_404(User, pk=user_id)
    
    # 사용자가 작성한 질문
    question_list = Question.objects.filter(author=profile_user).order_by('-create_date')
    question_paginator = Paginator(question_list, 5)
    question_page = request.GET.get('question_page', '1')
    question_page_obj = question_paginator.get_page(question_page)
    
    # 사용자가 작성한 답변
    answer_list = Answer.objects.filter(author=profile_user).order_by('-create_date')
    answer_paginator = Paginator(answer_list, 5)
    answer_page = request.GET.get('answer_page', '1')
    answer_page_obj = answer_paginator.get_page(answer_page)
    
    # 사용자가 작성한 댓글
    comment_list = Comment.objects.filter(author=profile_user).order_by('-create_date')
    comment_paginator = Paginator(comment_list, 5)
    comment_page = request.GET.get('comment_page', '1')
    comment_page_obj = comment_paginator.get_page(comment_page)
    
    context = {
        'profile_user': profile_user,
        'question_list': question_page_obj,
        'answer_list': answer_page_obj,
        'comment_list': comment_page_obj,
        'question_page': question_page,
        'answer_page': answer_page,
        'comment_page': comment_page,
    }
    return render(request, 'pybo/profile.html', context)