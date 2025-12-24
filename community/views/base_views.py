
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Count, F
from django.http import Http404, FileResponse, HttpResponse
from django.core.cache import cache
from django.conf import settings
from django.contrib.auth.models import User
import time
import os
import mimetypes


from ..models import Question, Answer, Comment, Category

DEFAULT_CATEGORIES = ['HRD', '데이터분석', '프로그래밍', '자유게시판', '앨범', '공지사항', '문의']


def ensure_default_categories():
    """필수 카테고리가 없으면 생성"""
    for name in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(name=name, defaults={'description': name})

def index(request):
    """메인 질문 목록 페이지 - 검색, 카테고리 필터링, 페이징 기능"""
    ensure_default_categories()
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
    
    # 카테고리 목록 및 각 카테고리별 글 개수 가져오기
    categories = Category.objects.all().order_by('name')
    category_counts = {}
    for cat in categories:
        category_counts[cat.name] = Question.objects.filter(is_deleted=False, category=cat).count()
    total_count = Question.objects.filter(is_deleted=False).count()

    # 서비스 런칭일 기준 경과 일수 (2025-10-01)
    from datetime import date
    launch_date = date(2025, 10, 1)
    launch_days = (date.today() - launch_date).days
    if launch_days < 0:
        launch_days = 0

    # 총 회원 수
    total_users = User.objects.count()

    # 오늘 방문자 수 (세션 기반)
    today_str = date.today().strftime('%Y-%m-%d')
    session_key = f'visited_{today_str}'

    # 현재 사용자가 오늘 처음 방문했는지 확인
    if not request.session.get(session_key):
        request.session[session_key] = True
        # 캐시에서 오늘 방문자 수 증가
        cache_key = f'visitors_{today_str}'
        visitors_today = cache.get(cache_key, 0)
        cache.set(cache_key, visitors_today + 1, 86400)  # 24시간 유지

    # 오늘 방문자 수 가져오기
    visitors_today = cache.get(f'visitors_{today_str}', 0)

    context = {
        'question_list': page_obj,
        'page': page,
        'kw': kw,
        'category': category_name,
        'sort': sort,
        'categories': categories,
        'category_counts': category_counts,
        'total_count': total_count,
        'launch_days': launch_days,
        'total_users': total_users,
        'visitors_today': visitors_today,
    }
    return render(request, 'community/question_list.html', context)

def detail(request, question_id):
    # 질문 객체 조회 (삭제되지 않은 것만)
    question = get_object_or_404(
        Question.objects.filter(is_deleted=False)
                        .select_related('author', 'category')
                        .prefetch_related('voter', 'comment_set__author'),
        pk=question_id
    )

    # 잠금된 글은 로그인한 사용자만 볼 수 있음
    if question.is_locked and not request.user.is_authenticated:
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.error(request, '회원 전용 글입니다. 로그인 후 이용해주세요.')
        return redirect('common:login')

    # 문의 게시판은 관리자/작성자만 열람 가능
    if question.category and question.category.name == '문의':
        if not (request.user.is_staff or request.user == question.author):
            from django.contrib import messages
            messages.error(request, '문의글은 관리자만 확인할 수 있습니다.')
            return redirect('community:index')

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

    # 정렬 (오래된 댓글이 위, 최신 댓글이 아래)
    if sort == 'recommend':
        answer_qs = answer_qs.annotate(num_voter=Count('voter')) \
                             .order_by('-num_voter', 'create_date')
    else:
        answer_qs = answer_qs.order_by('create_date')

    # 페이지네이션 제거 - 모든 댓글을 한 페이지에 표시
    answer_list = list(answer_qs)

    context = {
        'question': question,
        'answer_list': answer_list,  # 템플릿에서 for answer in answer_list
        'sort': sort,
    }
    return render(request, 'community/question_detail.html', context)

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
    return render(request, 'community/recent_answers.html', context)

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
    return render(request, 'community/recent_comments.html', context)


def download_file(request, question_id):
    """파일 다운로드"""
    question = get_object_or_404(Question, pk=question_id)

    if not question.file:
        raise Http404("파일이 존재하지 않습니다.")

    file_path = question.file.path

    if not os.path.exists(file_path):
        raise Http404("파일이 존재하지 않습니다.")

    # 파일명 추출
    filename = os.path.basename(file_path)

    # MIME 타입 추측
    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = 'application/octet-stream'

    # 파일 응답
    response = FileResponse(open(file_path, 'rb'), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response


def games_index(request):
    """게임 대시보드 - 모든 게임 목록"""
    from ..models import NumberBaseballGame, Game2048, GuestBook, MinesweeperGame
    from django.db.models import F

    # 각 게임의 통계 정보
    games_info = [
        {
            'name': '숫자야구',
            'title': 'Number Baseball',
            'description': '숨겨진 4자리 숫자를 맞춰보세요. 스트라이크와 볼 힌트로 추리하는 게임!',
            'url': 'community:baseball_start',
            'icon': '⚾',
            'color': 'warning',
            'total_games': NumberBaseballGame.objects.count(),
            'active_games': NumberBaseballGame.objects.filter(status='playing').count(),
            'features': ['싱글 플레이', '논리 퍼즐', '추리 게임'],
        },
        {
            'name': '2048',
            'title': '2048 Puzzle',
            'description': '타일을 합쳐 2048을 만드세요! 중독성 강한 퍼즐 게임.',
            'url': 'community:game2048_start',
            'icon': '🎮',
            'color': 'info',
            'total_games': Game2048.objects.count(),
            'active_games': Game2048.objects.filter(status='playing').count(),
            'features': ['퍼즐', '싱글 플레이', '키보드 조작'],
        },
        {
            'name': '지뢰찾기',
            'title': 'Minesweeper',
            'description': '클래식 지뢰찾기 게임. 숫자 힌트를 보고 지뢰를 피하세요!',
            'url': 'community:minesweeper_start',
            'icon': '💣',
            'color': 'danger',
            'total_games': MinesweeperGame.objects.count(),
            'active_games': MinesweeperGame.objects.filter(status='playing').count(),
            'features': ['논리 퍼즐', '싱글 플레이', '3가지 난이도'],
        },
    ]

    # 최근 활동 통계
    recent_stats = {
        'total_games_played': (
            NumberBaseballGame.objects.count() +
            Game2048.objects.count() +
            MinesweeperGame.objects.count()
        ),
        'active_players': request.user.is_authenticated,
    }

    context = {
        'games_info': games_info,
        'recent_stats': recent_stats,
    }

    return render(request, 'community/games_index.html', context)
