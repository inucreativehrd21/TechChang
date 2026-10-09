from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Question, PortfolioCollection


class StaticViewSitemap(Sitemap):
    """정적/주요 공개 페이지 (홈, 커뮤니티, 게임, 구성원, 랭킹)

    로그인이 필요한 페이지는 넣지 않는다 — 크롤러에게는 robots.txt 가 막아 둔
    로그인 페이지로 리다이렉트되는 막다른 길이라, 색인은 안 되고 크롤링 예산만 쓴다.
    (방명록 guestbook_list 는 @login_required 라 2026-09-26 에 제외)
    """
    protocol = 'https'

    # (URL name, priority, changefreq) — 홈을 최상위 우선순위로
    PAGES = [
        ('community:index',          1.0, 'daily'),
        ('community:board_main',     0.9, 'daily'),
        ('community:games_index',    0.7, 'weekly'),
        ('community:members_list',   0.7, 'weekly'),
        ('common:point_ranking',     0.6, 'weekly'),
        ('community:series_index',   0.8, 'weekly'),  # 연재 시리즈 목록
        ('office:home',              0.6, 'daily'),   # 연구실 — 칼럼이 만들어지는 곳
        ('sitemap_page',             0.4, 'daily'),   # 사람이 보는 사이트맵 = 내부링크 허브
    ]

    def items(self):
        return self.PAGES

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]

    def changefreq(self, item):
        return item[2]


class QuestionSitemap(Sitemap):
    """질문/답변 게시글 — 비로그인 방문자가 실제로 읽을 수 있는 글만"""
    protocol = 'https'
    changefreq = 'daily'
    priority = 0.7

    # community.views.base_views.detail 이 비로그인 사용자를 돌려보내는 조건과 짝을 이룬다.
    # 여기 조건을 바꾸면 detail 쪽도 함께 봐야 한다.
    RESTRICTED_CATEGORIES = ('문의',)

    def public_queryset(self):
        return Question.objects.filter(
            is_deleted=False,
            is_locked=False,                       # 회원 전용 글 → 로그인 페이지로 302
        ).exclude(
            category__name__in=self.RESTRICTED_CATEGORIES,   # 문의글 → 홈으로 302
        ).order_by('-create_date').select_related('author', 'category')

    def items(self):
        # 본문이 빈약한 회원 글은 상세에서 noindex 이므로 사이트맵에도 넣지 않는다 (Question.is_indexable)
        return [q for q in self.public_queryset()[:1000] if q.is_indexable][:500]

    def lastmod(self, obj):
        return obj.modify_date or obj.create_date

    def location(self, obj):
        return reverse('community:detail', kwargs={'question_id': obj.id})


class ColumnSitemap(QuestionSitemap):
    """연구팀 칼럼 — 사이트의 핵심 콘텐츠. 편집 심사 추천(85점+) 칼럼은 최우선."""
    changefreq = 'weekly'

    def items(self):
        return list(self.public_queryset().filter(author__username=Question.BOT_USERNAME)[:1000])

    def priority(self, obj):
        from office.picks import pick_scores
        return 1.0 if obj.id in pick_scores() else 0.9


class PostSitemap(QuestionSitemap):
    """회원 글 — 본문이 충분한 글만."""
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        qs = self.public_queryset().exclude(author__username=Question.BOT_USERNAME)[:1000]
        return [q for q in qs if q.is_indexable][:500]


class SeriesSitemap(Sitemap):
    """연재 시리즈 목차 페이지"""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        from .models import ColumnSeries
        return [s for s in ColumnSeries.objects.order_by('-create_date') if s.published_episodes.exists()]

    def lastmod(self, obj):
        last = obj.published_episodes.order_by('-create_date').first()
        return (last.modify_date or last.create_date) if last else obj.create_date

    def location(self, obj):
        return reverse('community:series_detail', kwargs={'slug': obj.slug})


class MakingSitemap(Sitemap):
    """칼럼 메이킹 오브 — 검증 과정을 공개한 페이지(신뢰 신호)"""
    protocol = 'https'
    changefreq = 'monthly'
    priority = 0.4

    def items(self):
        from office.models import ColumnDraft
        return list(ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED, question__isnull=False,
                                               question__is_deleted=False)
                    .select_related('question').order_by('-question__create_date')[:500])

    def lastmod(self, obj):
        return obj.question.modify_date or obj.question.create_date

    def location(self, obj):
        return reverse('office:making', kwargs={'question_id': obj.question_id})


class PortfolioCollectionSitemap(Sitemap):
    """공개 포트폴리오 (slug 기반)"""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return PortfolioCollection.objects.filter(
            is_published=True, approval_status='approved'
        ).select_related('user').order_by('-modify_date')

    def lastmod(self, obj):
        return obj.modify_date

    def location(self, obj):
        return reverse('community:portfolio_collection_detail', kwargs={'slug': obj.slug})
