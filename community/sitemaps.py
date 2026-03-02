from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Question, PortfolioCollection


class StaticViewSitemap(Sitemap):
    """정적 페이지 (홈, 멤버, 게임 등)"""
    protocol = 'https'
    priority = 0.5
    changefreq = 'weekly'

    def items(self):
        return ['index', 'board_main', 'members_list', 'games_index']

    def location(self, item):
        return reverse(f'community:{item}')


class QuestionSitemap(Sitemap):
    """질문/답변 게시글"""
    protocol = 'https'
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return Question.objects.filter(
            is_deleted=False
        ).order_by('-create_date').select_related('author')[:500]

    def lastmod(self, obj):
        return obj.modify_date or obj.create_date

    def location(self, obj):
        return reverse('community:detail', kwargs={'question_id': obj.id})


class PortfolioCollectionSitemap(Sitemap):
    """공개 포트폴리오 (slug 기반)"""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return PortfolioCollection.objects.filter(
            is_published=True
        ).select_related('user').order_by('-modify_date')

    def lastmod(self, obj):
        return obj.modify_date

    def location(self, obj):
        return reverse('community:portfolio_collection_detail', kwargs={'slug': obj.slug})
