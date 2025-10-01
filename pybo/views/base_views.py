
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Count, F
from django.http import Http404
from django.core.cache import cache
from django.conf import settings
import time


from ..models import Question, Answer, Comment, Category

def index(request):
    """메인 질문 목록 페이지 - 검색, 카테고리 필터링, 페이징 기능"""
    try:
        page = int(request.GET.get('page', '1'))
    except (ValueError, TypeError):
        page = 1
    
    kw = request.GET.get('kw', '').strip()  # 검색어
    category_name = request.GET.get('category', '').strip()  # 카테고리
    sort = request.GET.get('sort', 'recent')  # 정렬 방식
    
    # 기본 쿼리셋 - select_related로 성능 최적화 (삭제되지 않은 질문만)
    question_list = Question.objects.filter(is_deleted=False).select_related('author', 'category').prefetch_related('voter')
    
    # 정렬 처리
    if sort == 'recommend':
        question_list = question_list.annotate(num_voter=Count('voter')).order_by('-num_voter', '-create_date')
    elif sort == 'popular':
        question_list = question_list.order_by('-view_count', '-create_date')
    else:  # recent
        question_list = question_list.order_by('-create_date')
    
    # 검색 처리
    if kw:
        question_list = question_list.filter(
            Q(subject__icontains=kw) |  # 제목 검색
            Q(content__icontains=kw) |  # 내용 검색
            Q(answer__content__icontains=kw) |  # 답변 내용 검색
            Q(author__username__icontains=kw) |  # 질문 글쓴이 검색
            Q(answer__author__username__icontains=kw)  # 답변 글쓴이 검색
        ).distinct()
    
    # 카테고리 필터링
    if category_name:
        try:
            category = Category.objects.get(name=category_name)
            question_list = question_list.filter(category=category)
        except Category.DoesNotExist:
            pass  # 잘못된 카테고리는 무시
    
    # 페이징 처리
    paginator = Paginator(question_list, 10)
    try:
        page_obj = paginator.get_page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.get_page(1)
    
    # 카테고리 목록 가져오기
    categories = Category.objects.all().order_by('name')
    
    context = {
        'question_list': page_obj, 
        'page': page, 
        'kw': kw, 
        'category': category_name,
        'sort': sort,
        'categories': categories,
    }
    return render(request, 'pybo/question_list.html', context)

def detail(request, question_id):
    # 질문 객체 조회 (삭제되지 않은 것만)
    question = get_object_or_404(
        Question.objects.filter(is_deleted=False)
                        .select_related('author', 'category')
                        .prefetch_related('voter', 'comment_set__author'),
        pk=question_id
    )

    # 조회수 중복 방지 (5분)
    session_key = f'viewed_question_{question_id}'
    last_view = request.session.get(session_key, 0)
    now = int(time.time())
    if now - last_view > 300:
        Question.objects.filter(pk=question_id).update(view_count=F('view_count') + 1)
        request.session[session_key] = now

    # 답변 정렬 방식
    sort = request.GET.get('sort', 'recent')

    # 답변 쿼리셋 최적화
    answer_qs = question.answer_set.filter(is_deleted=False) \
                     .select_related('author')           \
                     .prefetch_related('voter', 'comment_set__author')

    # 정렬
    if sort == 'recommend':
        answer_qs = answer_qs.annotate(num_voter=Count('voter')) \
                             .order_by('-num_voter', '-create_date')
    else:
        answer_qs = answer_qs.order_by('-create_date')

    # 답변 페이징
    try:
        answer_page = int(request.GET.get('answer_page', '1'))
    except (ValueError, TypeError):
        answer_page = 1
    paginator = Paginator(answer_qs, 5)
    try:
        answer_page_obj = paginator.get_page(answer_page)
    except (EmptyPage, PageNotAnInteger):
        answer_page_obj = paginator.get_page(1)

    context = {
        'question': question,
        'answer_list': answer_page_obj,  # 템플릿에서 for answer in answer_list
        'sort': sort,
        'answer_page': answer_page_obj.number,
    }
    return render(request, 'pybo/question_detail.html', context)

def recent_answers(request):
    """최근 답변 목록 - 성능 최적화된 버전"""
    try:
        page = int(request.GET.get('page', '1'))
    except (ValueError, TypeError):
        page = 1
    
    # select_related로 쿼리 최적화
    answer_list = Answer.objects.select_related('author', 'question', 'question__category').order_by('-create_date')
    
    paginator = Paginator(answer_list, 10)
    try:
        page_obj = paginator.get_page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.get_page(1)
        
    context = {'answer_list': page_obj, 'page': page}
    return render(request, 'pybo/recent_answers.html', context)

def recent_comments(request):
    """최근 댓글 목록 - 성능 최적화된 버전"""
    try:
        page = int(request.GET.get('page', '1'))
    except (ValueError, TypeError):
        page = 1
    
    # select_related로 쿼리 최적화
    comment_list = Comment.objects.select_related(
        'author', 'question', 'answer__question'
    ).order_by('-create_date')
    
    paginator = Paginator(comment_list, 10)
    try:
        page_obj = paginator.get_page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.get_page(1)
        
    context = {'comment_list': page_obj, 'page': page}
    return render(request, 'pybo/recent_comments.html', context)