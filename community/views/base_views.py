
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Count, F, Sum
from django.http import Http404, FileResponse, HttpResponse
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.contrib import messages
from django.db import transaction
from django.utils.http import urlencode
import logging
import time
import os
import mimetypes


from ..models import Question, Answer, Comment, Category, DailyVisitor

DEFAULT_CATEGORIES = ['HRD', '데이터분석', '프로그래밍', '자유게시판', '앨범', '공지사항', '문의']


ROBOTS_PATH = settings.BASE_DIR / 'static' / 'robots.txt'


def robots_txt(request):
    """검색엔진 크롤러용 robots.txt.

    **운영에서는 nginx 가 static/robots.txt 를 직접 서빙하므로 이 뷰를 타지 않는다**
    (`location /robots.txt { alias .../static/robots.txt; }`). 예전에는 이 뷰가 내용을
    따로 만들어 두 벌이 갈라졌고, 뷰만 고치면 운영에 반영되지 않았다. 그래서 같은
    파일을 읽어 내보낸다 — 내용을 바꿀 곳은 static/robots.txt 한 곳뿐이다.
    """
    try:
        body = ROBOTS_PATH.read_text(encoding='utf-8')
    except OSError:
        body = 'User-agent: *\nAllow: /\n\nSitemap: https://techchang.com/sitemap.xml\n'
    return HttpResponse(body, content_type='text/plain; charset=utf-8')


def indexnow_key(request, key):
    """IndexNow 소유 확인 파일 — /<INDEXNOW_KEY>.txt 가 키를 그대로 돌려준다."""
    if not settings.INDEXNOW_KEY or key != settings.INDEXNOW_KEY:
        raise Http404
    return HttpResponse(key, content_type='text/plain; charset=utf-8')


def sitemap_page(request):
    """사람이 보는 사이트맵 — sitemap.xml 과 같은 범위를 카테고리별로 묶어 보여준다.

    크롤러용 XML 에 XSL 을 붙이는 방법도 있으나 Chrome 이 XSLT 를 제거하는 중이라
    경고 배너가 뜨고 곧 깨진다. 별도 HTML 페이지면 방문자에게도, 내부링크에도 이득이다.
    목록 기준은 QuestionSitemap 과 같아야 하므로 같은 쿼리셋을 가져다 쓴다.
    """
    from django.urls import reverse

    from ..sitemaps import PortfolioCollectionSitemap, QuestionSitemap, StaticViewSitemap

    posts = list(QuestionSitemap().items())
    groups = {}
    for q in posts:
        groups.setdefault(q.category.name if q.category else '기타', []).append(q)

    # 카테고리 순서는 사이트 기본 순서를 따르고, 그 밖의 것은 뒤에 붙인다
    ordered = [(name, groups.pop(name)) for name in DEFAULT_CATEGORIES if name in groups]
    ordered += sorted(groups.items())

    labels = {
        'community:index': '홈 — 최신 글',
        'community:board_main': '게시판',
        'community:games_index': '게임',
        'community:members_list': '구성원',
        'common:point_ranking': '포인트 랭킹',
        'sitemap_page': '사이트맵',
    }
    return render(request, 'community/sitemap_page.html', {
        # 이 페이지 자신은 뺀다 (자기 자신으로 가는 링크)
        'static_pages': [(reverse(name), labels.get(name, name))
                         for name, _p, _f in StaticViewSitemap.PAGES if name != 'sitemap_page'],
        'groups': ordered,
        'portfolios': PortfolioCollectionSitemap().items(),
        'total': len(posts),
    })


def ensure_default_categories():
    """필수 카테고리가 없으면 생성"""
    for name in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(name=name, defaults={'description': name})

# 연구실 칼럼 발행 일정 (office_publish cron: 화 HRD / 목 데이터분석 / 토 프로그래밍, 10:00)
LAB_SLOTS = [(1, 'hrd', 'HRD'), (3, 'data', '데이터분석'), (5, 'coding', '프로그래밍')]
WEEKDAYS = '월화수목금토일'


def _home_live_data():
    """홈 라이브 패널의 연구실 소식(다음 칼럼 주제·연재 진행)·게임 누적 판수 (5분 캐시)."""
    from office.agents import MEETING_ORDER
    from office.services import take_column_brief
    from ..models import ColumnSeries, NumberBaseballGame, Game2048, MinesweeperGame

    # 회의에서 정해졌고 아직 쓰지 않은 분야별 주제 (공개 페이지에 쓰는 것과 같은 값).
    # 연구실은 별도 하위 시스템이라 여기서 실패해도 홈은 떠야 한다 → 실패 시 블록만 숨김.
    try:
        briefs = {}
        for _wd, key, _label in LAB_SLOTS:
            d = take_column_brief(key)
            briefs[key] = (d.chosen or {}).get('title', '') if d else ''
        s = ColumnSeries.objects.filter(is_active=True).first()
        series = ({'title': s.title, 'slug': s.slug, 'published': s.published_count, 'planned': s.total_episodes}
                  if s else None)
        lab = {'agents': len(MEETING_ORDER), 'briefs': briefs, 'series': series}
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception('home lab block unavailable')
        lab = None

    games_played_total = (
        NumberBaseballGame.objects.count()
        + Game2048.objects.count()
        + MinesweeperGame.objects.count()
    )
    return {'lab': lab,
            'games_played_total': games_played_total}


def _next_column_slot(briefs):
    """지금 이후 가장 가까운 칼럼 발행 시각 + 그 분야의 예정 주제. 캐시와 별개로 요청마다 계산."""
    from datetime import datetime, time as dtime, timedelta
    now = timezone.localtime()
    for add in range(8):
        day = now.date() + timedelta(days=add)
        for wd, key, label in LAB_SLOTS:
            if day.weekday() != wd:
                continue
            at = datetime.combine(day, dtime(10), tzinfo=now.tzinfo)
            if at <= now:
                continue
            when = '오늘' if add == 0 else '내일' if add == 1 else WEEKDAYS[wd]
            return {'when': when, 'label': label, 'title': briefs.get(key, '')}
    return None


def _hidden_inquiry_q(user):
    """홈 목록에서 숨길 문의글 조건. 문의글은 관리자·작성자만 열람 가능하므로
    누를 수 없는 제목을 보여주지 않는다 (관리자: 전부 보임, 회원: 본인 글만, 비회원: 숨김)."""
    if user.is_staff or user.is_superuser:
        return None
    hidden = Q(category__name='문의')
    if user.is_authenticated:
        hidden &= ~Q(author=user)
    return hidden


def visible_questions(user):
    """목록에 노출할 글 (삭제·연재 회차 제외, 열람 불가 문의글 제외). 홈과 커뮤니티 공용."""
    qs = Question.objects.filter(is_deleted=False, series__isnull=True)
    hidden = _hidden_inquiry_q(user)
    return qs.exclude(hidden) if hidden is not None else qs


def category_counts_for(visible, user):
    """(카테고리 목록, {이름: 개수}, 전체 개수). 개수는 노출 기준으로 세고,
    볼 수 있는 문의글이 없는 사용자에게는 문의 카테고리를 숨긴다."""
    counts = dict(visible.order_by().values_list('category__name').annotate(n=Count('id')))
    hide_inquiry = _hidden_inquiry_q(user) is not None
    categories = []
    for cat in Category.objects.order_by('name'):
        cat.question_count = counts.get(cat.name, 0)
        if cat.name == '문의' and hide_inquiry and not cat.question_count:
            continue
        categories.append(cat)
    return categories, {c.name: c.question_count for c in categories}, sum(counts.values())


def _pick_scores():
    from office.picks import pick_scores
    return pick_scores()


def index(request):
    """메인 질문 목록 페이지 - 검색, 카테고리 필터링, 페이징 기능"""
    ensure_default_categories()
    try:
        page = int(request.GET.get('page', '1'))
    except (ValueError, TypeError):
        page = 1
    
    kw = request.GET.get('kw', '').strip()  # 검색어
    category_name = request.GET.get('category', '').strip()  # 카테고리
    sort = request.GET.get('sort', 'recent')
    if sort not in ('recent', 'recommend', 'popular'):
        sort = 'recent'

    # 기본 쿼리셋 - select_related로 성능 최적화 (삭제되지 않은 질문만)
    # annotate로 voter_count, answer_count 미리 계산 (N+1 쿼리 방지)
    # distinct=True로 Cartesian product에 의한 중복 카운트 방지
    # series__isnull=True: 연재 시리즈 회차는 게시글 목록에서 제외 (별도 [시리즈] 탭에서 노출)
    visible = visible_questions(request.user)

    question_list = visible\
        .select_related('author', 'category')\
        .prefetch_related('voter')\
        .annotate(
            voter_count=Count('voter', distinct=True),
            answer_count=Count('answer', filter=Q(answer__is_deleted=False), distinct=True)
        )

    # 정렬 처리
    if sort == 'recommend':
        question_list = question_list.order_by('-voter_count', '-create_date')
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
    
    # 페이징 처리 (3열/2열 그리드 어느 쪽에서도 마지막 줄이 혼자 남지 않도록 12 = 3과 2의 공배수)
    paginator = Paginator(question_list, 12)
    try:
        page_obj = paginator.get_page(page)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.get_page(1)
    
    # 카테고리 목록 및 각 카테고리별 글 개수 가져오기 (단일 쿼리로 최적화)
    categories, category_counts, total_count = category_counts_for(visible, request.user)

    # 인기 게시글 TOP 5 (조회수 기준, 필터/검색과 무관하게 항상 전체 기준)
    popular_posts = visible\
        .select_related('author', 'category')\
        .order_by('-view_count', '-create_date')[:5]

    # 히어로 라이브 패널용 최신 글 (문의글 제목은 새 노출면에 내보내지 않음)
    recent_posts = Question.objects.filter(is_deleted=False, series__isnull=True)\
        .exclude(category__name='문의')\
        .select_related('category')\
        .order_by('-create_date')[:3]

    live = cache.get_or_set('home:live:v2', _home_live_data, 300)

    # 페이지 링크가 검색어·카테고리·정렬을 잃지 않도록 미리 인코딩
    page_qs = urlencode({k: v for k, v in (
        ('kw', kw), ('category', category_name), ('sort', '' if sort == 'recent' else sort)
    ) if v})

    # 서비스 런칭일 기준 경과 일수 (2025-10-01)
    from datetime import date
    launch_date = date(2025, 10, 1)
    launch_days = (date.today() - launch_date).days
    if launch_days < 0:
        launch_days = 0

    # 총 회원 수
    total_users = User.objects.count()

    # 오늘 방문자 수 (DB 기반)
    today = date.today()
    session_key = f'visited_{today}'

    # 현재 사용자가 오늘 처음 방문했는지 확인
    if not request.session.get(session_key):
        request.session[session_key] = True

        # DB에서 오늘 방문자 수 증가 (원자적 업데이트)
        with transaction.atomic():
            daily_visitor, created = DailyVisitor.objects.get_or_create(
                date=today,
                defaults={'visitor_count': 1}
            )
            if not created:
                daily_visitor.visitor_count = F('visitor_count') + 1
                daily_visitor.save(update_fields=['visitor_count'])

    # 오늘 방문자 수 가져오기
    try:
        visitors_today = DailyVisitor.objects.get(date=today).visitor_count
    except DailyVisitor.DoesNotExist:
        visitors_today = 0
    visitors_total = DailyVisitor.objects.aggregate(s=Sum('visitor_count'))['s'] or 0

    context = {
        'question_list': page_obj,
        'page': page,
        'kw': kw,
        'category': category_name,
        'sort': sort,
        'categories': categories,
        'category_counts': category_counts,
        'total_count': total_count,
        'popular_posts': popular_posts,
        'recent_posts': recent_posts,
        'picks': _pick_scores(),       # {question_id: 점수} — 편집 심사 85점 이상 칼럼에 '추천' 표시
        'lab': live['lab'],
        'next_slot': _next_column_slot(live['lab']['briefs']) if live['lab'] else None,
        'games_played_total': live['games_played_total'],
        'page_qs': page_qs,
        'launch_days': launch_days,
        'total_users': total_users,
        'visitors_today': visitors_today,
        'visitors_total': f'{visitors_total:,}',
    }
    template = 'community/mobile/question_list.html' if getattr(request, 'is_mobile', False) else 'community/question_list.html'
    return render(request, template, context)

def detail(request, question_id):
    # 질문 객체 조회 (삭제되지 않은 것만)
    question = get_object_or_404(
        Question.objects.filter(is_deleted=False)
                        .select_related('author', 'category')
                        .prefetch_related('voter', 'comment_set__author'),
        pk=question_id
    )

    # 잠금된 글은 로그인한 사용자만 볼 수 있음 (로그인 후 이 글로 돌아오도록 next 전달)
    if question.is_locked and not request.user.is_authenticated:
        messages.error(request, '회원 전용 글입니다. 로그인 후 이용해주세요.')
        return redirect_to_login(request.get_full_path())

    # 문의 게시판은 관리자/작성자만 열람 가능
    if question.category and question.category.name == '문의':
        if not (request.user.is_staff or request.user == question.author):
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
        answer_qs = answer_qs.annotate(num_voter=Count('voter', distinct=True)) \
                             .order_by('-num_voter', 'create_date')
    else:
        answer_qs = answer_qs.order_by('create_date')

    # 페이지네이션 제거 - 모든 댓글을 한 페이지에 표시
    answer_list = list(answer_qs)

    # 시리즈 연재 네비게이션 (연재 회차인 경우에만)
    series_nav = None
    if question.series_id and question.episode_number is not None:
        episodes = list(
            question.series.episodes.filter(is_deleted=False)
                          .order_by('episode_number')
                          .values('id', 'subject', 'episode_number')
        )
        idx = next((i for i, e in enumerate(episodes) if e['id'] == question.id), None)
        if idx is not None:
            series_nav = {
                'series': question.series,
                'episodes': episodes,
                'prev': episodes[idx - 1] if idx > 0 else None,
                'next': episodes[idx + 1] if idx < len(episodes) - 1 else None,
                'position': idx + 1,
                'total': len(episodes),
            }

    # 연구팀이 만든 칼럼이면 제작 과정 요약 (본문 아래 카드 → /lab/making/<id>/)
    making = None
    try:
        from office.making import build_making
        making = build_making(question.office_draft)
    except ObjectDoesNotExist:  # 연구팀 칼럼이 아님
        pass
    except Exception:  # noqa: BLE001 — 부가 카드 하나 때문에 본문 페이지가 500 이 나면 안 된다
        logging.getLogger(__name__).exception('메이킹 카드 생성 실패: question=%s', question.id)

    # 본문 아래 '함께 읽으면 좋은 칼럼' — 내부 링크(검색엔진 주제 묶음·크롤링 동선)
    from office.related import related_columns
    related = related_columns(question) if question.is_indexable else []

    context = {
        'question': question,
        'answer_list': answer_list,  # 템플릿에서 for answer in answer_list
        'sort': sort,
        'series_nav': series_nav,
        'making': making,
        'related': related,
    }
    template = 'community/mobile/question_detail.html' if getattr(request, 'is_mobile', False) else 'community/question_detail.html'
    return render(request, template, context)

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


@login_required(login_url='common:login')
def download_file(request, question_id):
    """파일 다운로드 - 권한 검증 포함"""
    question = get_object_or_404(Question, pk=question_id, is_deleted=False)

    # 권한 검사: 잠긴 글은 회원만, 문의 게시판은 작성자/관리자만
    if question.is_locked and not request.user.is_authenticated:
        messages.error(request, '회원 전용 글입니다.')
        return redirect('community:index')

    if question.category and question.category.name == '문의':
        if not (request.user.is_staff or request.user == question.author):
            messages.error(request, '문의글은 작성자와 관리자만 확인할 수 있습니다.')
            return redirect('community:index')

    if not question.file:
        raise Http404("파일이 존재하지 않습니다.")

    MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100MB
    if question.file.size > MAX_DOWNLOAD_SIZE:
        messages.error(request, '파일이 너무 큽니다.')
        return redirect('community:detail', question_id=question.id)

    # FileField를 직접 사용하여 파일 제공 (경로 조작 방지)
    try:
        response = FileResponse(question.file.open('rb'))
        response['Content-Type'] = mimetypes.guess_type(question.file.name)[0] or 'application/octet-stream'
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(question.file.name)}"'
        return response
    except FileNotFoundError:
        raise Http404("파일이 존재하지 않습니다.")


def _kdate(dt) -> str:
    """'10월 26일(월)' — 공개 예정일 표기."""
    if not dt:
        return ''
    dt = timezone.localtime(dt)
    return f"{dt.month}월 {dt.day}일({'월화수목금토일'[dt.weekday()]})"


def _series_toc(series):
    """시리즈 목차 행 — 발행된 회차와 기획서(series_catalog)의 예정 회차를 한 줄로 잇는다.

    반환 dict: rows(목차), count(발행 수), total(기획 회차 수), first·latest(발행 회차), next_at(다음 공개 예정),
    views(누적 조회). 기획서에 없는 시리즈는 발행된 회차만 보여 준다.
    """
    from ..series_catalog import OUTLINES, key_for_slug, next_publish_at

    episodes = list(series.published_episodes.only('id', 'subject', 'content', 'episode_number',
                                                   'create_date', 'view_count'))
    by_no = {e.episode_number: e for e in episodes}
    key = key_for_slug(series.slug)
    outline = OUTLINES.get(key, [])
    last = episodes[-1] if episodes else None
    planned = [o for o in outline if o['no'] not in by_no and (last is None or o['no'] > last.episode_number)]
    next_at = next_publish_at(key, last.create_date if last else None) if (planned and series.is_active) else None

    rows = []
    for e in episodes:
        rows.append({'no': e.episode_number, 'title': e.subject, 'id': e.id, 'state': 'published',
                     'date': e.create_date, 'views': e.view_count,
                     'minutes': max(1, round(len(e.content or '') / 500)),
                     'is_new': (timezone.now() - e.create_date).days < 14})
    for i, o in enumerate(planned):
        rows.append({'no': o['no'], 'title': o['title'], 'state': 'next' if i == 0 else 'planned',
                     'date': next_at if i == 0 else None, 'date_label': _kdate(next_at) if i == 0 else ''})
    return {'rows': rows, 'count': len(episodes), 'total': series.total_episodes or len(outline) or len(episodes),
            'first': episodes[0] if episodes else None, 'latest': last, 'next_at': next_at, 'next_label': _kdate(next_at),
            'views': sum(e.view_count for e in episodes)}


def series_index(request):
    """연재 시리즈 목록 — 연재마다 카드 한 장, 화살표로 넘기는 캐러셀(가장 최근에 시작한 연재가 첫 장)."""
    from ..models import ColumnSeries

    cards = [{'series': s, **_series_toc(s)}
             for s in ColumnSeries.objects.select_related('category').order_by('-create_date')]
    # 회차가 하나도 없는 시리즈는 목록에 내놓지 않는다(빈 표지). 가장 최근에 시작한(0편이 새로운) 연재가 맨 위
    cards = sorted([c for c in cards if c['count']], key=lambda c: c['first'].create_date, reverse=True)
    context = {
        'cards': cards,
        'stats': {'series': len(cards), 'episodes': sum(c['count'] for c in cards),
                  'views': sum(c['views'] for c in cards)},
    }
    return render(request, 'community/series_list.html', context)


def series_detail(request, slug):
    """특정 시리즈의 목차 — 발행 회차 + 예정 회차 + 다음 공개일."""
    from ..models import ColumnSeries
    from ..series_catalog import SCHEDULE, key_for_slug

    series = get_object_or_404(ColumnSeries.objects.select_related('category'), slug=slug)
    toc = _series_toc(series)
    context = {'series': series, 'has_schedule': key_for_slug(slug) in SCHEDULE, **toc}
    return render(request, 'community/series_detail.html', context)


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

    template = 'community/mobile/games_index.html' if getattr(request, 'is_mobile', False) else 'community/games_index.html'
    return render(request, template, context)
