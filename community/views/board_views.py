from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Count, Q
from ..models import Category, Question


def board_main(request):
    """커뮤니티 메인 페이지 - 카테고리별 최신 게시글 미리보기"""
    # 모든 카테고리 가져오기
    categories = Category.objects.all().order_by('id')

    # 각 카테고리별 최신 게시글 5개씩 가져오기
    category_posts = {}
    for category in categories:
        posts = Question.objects.filter(
            category=category,
            is_deleted=False
        ).select_related('author', 'author__profile').annotate(
            answer_count=Count('answer', filter=Q(answer__is_deleted=False)),
            voter_count=Count('voter')
        ).order_by('-create_date')[:5]

        category_posts[category.name] = {
            'category': category,
            'posts': posts,
            'total_count': Question.objects.filter(category=category, is_deleted=False).count()
        }

    # 전체 통계
    total_questions = Question.objects.filter(is_deleted=False).count()

    context = {
        'categories': categories,
        'category_posts': category_posts,
        'total_questions': total_questions,
    }

    return render(request, 'community/board_main.html', context)


def board_category(request, category_name):
    """카테고리별 게시글 목록"""
    category = get_object_or_404(Category, name=category_name)

    # 검색어
    search_query = request.GET.get('search', '')

    # 정렬 기준
    sort = request.GET.get('sort', 'latest')  # latest, popular, views

    # 기본 쿼리셋
    questions = Question.objects.filter(
        category=category,
        is_deleted=False
    ).select_related('author', 'author__profile').annotate(
        answer_count=Count('answer', filter=Q(answer__is_deleted=False)),
        voter_count=Count('voter')
    )

    # 검색
    if search_query:
        questions = questions.filter(
            Q(subject__icontains=search_query) |
            Q(content__icontains=search_query) |
            Q(author__username__icontains=search_query)
        )

    # 정렬
    if sort == 'popular':
        questions = questions.order_by('-voter_count', '-create_date')
    elif sort == 'views':
        questions = questions.order_by('-view_count', '-create_date')
    else:  # latest
        questions = questions.order_by('-create_date')

    # 페이지네이션
    paginator = Paginator(questions, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 모든 카테고리 (사이드바용)
    all_categories = Category.objects.all().annotate(
        post_count=Count('question', filter=Q(question__is_deleted=False))
    )

    context = {
        'category': category,
        'page_obj': page_obj,
        'search_query': search_query,
        'sort': sort,
        'all_categories': all_categories,
    }

    return render(request, 'community/board_category.html', context)
