"""연구팀 칼럼 RSS — /rss.xml

네이버 서치어드바이저에 제출하면 새 칼럼을 사이트맵보다 빨리 수집한다. RSS 리더 구독·외부 자동 연동
(슬랙·뉴스레터)도 이 주소 하나로 된다. 본문 전체가 아니라 요약(seo_description)만 내보낸다 —
독자는 사이트로 와서 읽게 하고, 피드를 긁어 가는 복제 사이트에 원문을 통째로 넘기지 않기 위해서다.
"""
from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed

from .models import Question

SITE = 'https://techchang.com'


class ColumnFeed(Feed):
    feed_type = Rss201rev2Feed
    title = '테크창 — HRD·데이터분석·프로그래밍 칼럼'
    # 절대 주소로 고정 — 요청 스킴(프록시 뒤 http)에 따라 http:// 링크가 나가지 않게
    link = f'{SITE}/'
    feed_url = f'{SITE}/rss.xml'
    description = '팩트체크와 편집 심사를 통과한 HRD·데이터분석·프로그래밍 칼럼을 누구나 무료로 읽을 수 있는 지식 플랫폼, 테크창.'
    language = 'ko'
    author_name = '테크창 연구팀'

    def items(self):
        return (Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False, is_locked=False)
                .select_related('category').order_by('-create_date')[:30])

    def item_title(self, item):
        return item.subject

    def item_description(self, item):
        return item.seo_description

    def item_link(self, item):
        return SITE + reverse('community:detail', kwargs={'question_id': item.id})

    def item_guid(self, item):
        return f'{SITE}/{item.id}/'

    item_guid_is_permalink = True

    def item_pubdate(self, item):
        return item.create_date

    def item_updateddate(self, item):
        return item.modify_date or item.create_date

    def item_author_name(self, item):
        return '테크창 연구팀'

    def item_categories(self, item):
        return [item.category.name] if item.category else []
