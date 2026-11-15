"""콘텐츠 통합 탐색과 브라우저에 보관한 읽기 목록의 진입 화면."""
from urllib.parse import urlsplit

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import Resolver404, resolve, reverse

from common.navigation import safe_destination
from ..models import Category, Question
from .base_views import readable_questions


def explore(request):
    query = (request.GET.get('q') or request.GET.get('kw') or '').strip()[:100]
    category = request.GET.get('category', '')
    kind = request.GET.get('kind', '')
    if kind not in ('column', 'series', 'post'):
        kind = ''
    categories = Category.objects.exclude(name='문의').order_by('name')
    if not categories.filter(name=category).exists():
        category = ''
    posts = readable_questions(request.user).exclude(category__name='문의')
    if category:
        posts = posts.filter(category__name=category)
    if kind == 'series':
        posts = posts.filter(series__isnull=False)
    elif kind == 'column':
        posts = posts.filter(author__username=Question.BOT_USERNAME, series__isnull=True)
    elif kind == 'post':
        posts = posts.exclude(author__username=Question.BOT_USERNAME).filter(series__isnull=True)
    if query:
        for word in query.split():
            posts = posts.filter(
                Q(subject__icontains=word) | Q(content__icontains=word)
                | Q(author__username__icontains=word)
                | Q(answer__content__icontains=word, answer__is_deleted=False)
            )
    posts = posts.select_related('author', 'category', 'series').annotate(
        answer_count=Count('answer', filter=Q(answer__is_deleted=False), distinct=True),
    ).distinct().order_by('-create_date', '-pk')
    page = Paginator(posts, 12).get_page(request.GET.get('page'))
    return render(request, 'community/explore.html', {
        'query': query, 'selected_category': category, 'kind': kind,
        'explore_categories': categories, 'results': page,
    })


def reading_list(request):
    return render(request, 'community/reading_list.html')


def detail_return(request, question):
    """명시적인 원래 목록을 우선하고, 없으면 같은 사이트의 목록 Referer를 사용해요."""
    allowed = {'index': '홈', 'explore': '탐색 결과', 'column_map': '칼럼 지도',
               'board_main': '커뮤니티', 'board_category': '게시판',
               'series_index': '연재 목록', 'series_detail': '시리즈 목차',
               'reading_list': '내 활동'}
    for value in (request.GET.get('from'), request.META.get('HTTP_REFERER')):
        target = safe_destination(request, value, fallback='')
        if not target:
            continue
        try:
            match = resolve(urlsplit(target).path)
        except Resolver404:
            continue
        if match.namespace == 'community' and match.url_name in allowed:
            return target, allowed[match.url_name]
    if question.series_id:
        return reverse('community:series_detail', args=[question.series.slug]), '시리즈 목차'
    return reverse('community:explore'), '콘텐츠 탐색'
