from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils.http import urlencode

from ..models import Category
from .base_views import category_counts_for, visible_questions

# 공지는 맨 앞, 문의는 맨 뒤. 목록에 없는 카테고리는 그 사이에 이름순.
CATEGORY_ORDER = ['공지사항', 'HRD', '데이터분석', '프로그래밍', '자유게시판', '앨범', '문의']
SORTS = {
    'latest': ('-create_date',),
    'popular': ('-voter_count', '-create_date'),
    'views': ('-view_count', '-create_date'),
}


def _ordered(categories):
    def key(cat):
        return (CATEGORY_ORDER.index(cat.name) if cat.name in CATEGORY_ORDER else len(CATEGORY_ORDER) - 1, cat.name)
    return sorted(categories, key=key)


def _with_counts(qs):
    return qs.select_related('author', 'author__profile', 'category').annotate(
        answer_count=Count('answer', filter=Q(answer__is_deleted=False), distinct=True),
        voter_count=Count('voter', distinct=True),
    )


def board_main(request):
    """커뮤니티 메인 - 카테고리별 최신 글 5개 (홈과 같은 노출 기준: 열람 불가 문의글 제외)"""
    visible = visible_questions(request.user)
    categories, _, total = category_counts_for(visible, request.user)
    categories = _ordered(categories)

    sections = [
        {
            'category': cat,
            'posts': _with_counts(visible.filter(category=cat)).order_by('-create_date')[:5],
            'total_count': cat.question_count,
        }
        for cat in categories
    ]

    context = {
        'sections': sections,
        'categories': categories,
        'total_questions': total,
    }
    template = 'community/mobile/board_main.html' if getattr(request, 'is_mobile', False) else 'community/board_main.html'
    return render(request, template, context)


def board_category(request, category_name):
    """카테고리별 게시글 목록 - 홈 게시판과 같은 카드 그리드 (12개/페이지 = 3열·2열 공배수)"""
    category = get_object_or_404(Category, name=category_name)
    visible = visible_questions(request.user)

    search_query = request.GET.get('search', '').strip()
    sort = request.GET.get('sort', 'latest')
    if sort not in SORTS:
        sort = 'latest'

    questions = _with_counts(visible.filter(category=category))
    if search_query:
        questions = questions.filter(
            Q(subject__icontains=search_query)
            | Q(content__icontains=search_query)
            | Q(author__username__icontains=search_query)
        )
    questions = questions.order_by(*SORTS[sort])

    page_obj = Paginator(questions, 12).get_page(request.GET.get('page', 1))

    all_categories, _, total = category_counts_for(visible, request.user)

    context = {
        'category': category,
        'page_obj': page_obj,
        'search_query': search_query,
        'sort': sort,
        'all_categories': _ordered(all_categories),
        'total_questions': total,
        # 페이지 링크가 검색어·정렬을 잃지 않도록 미리 인코딩
        'page_qs': urlencode({k: v for k, v in (
            ('search', search_query), ('sort', '' if sort == 'latest' else sort)) if v}),
    }
    return render(request, 'community/board_category.html', context)
