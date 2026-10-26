"""사이트 공개 통계와 사이트 주인 — 홈 첫 화면과 주인의 HTML 포트폴리오가 같은 값을 쓴다.

- launch_days: 서비스 런칭일(2025-10-01)부터 지난 날수
- visitors_total / visitors_today: 일별 방문자(DailyVisitor) 합계 / 오늘
- lab_columns: 연구팀이 발행한 칼럼·연재 회차 수(삭제 제외)
- lab_essays / lab_episodes: 그중 단편 칼럼 / 연재 회차(예약 공개 글은 공개될 때 만들어지므로 대기 중인 글은 세지 않는다)
- as_of: 오늘 날짜(YYYY.MM.DD)

사이트 주인(settings.SITE_OWNER_USERNAME)의 HTML 포트폴리오만 `<span data-tc-stat="launch_days">376</span>` 처럼
적어 두면 raw 뷰가 내보낼 때 안의 글자를 최신 값으로 바꾼다(fill_stat_tags). 업로드 HTML 을 템플릿으로 해석하지
않고, 정해진 키의 값만 넣는다. 다른 회원의 포트폴리오는 손대지 않는다.
"""
import re
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

LAUNCH_DATE = date(2025, 10, 1)
CACHE_KEY = 'site_stats:v2'
CACHE_SECONDS = 60


def owner_username() -> str:
    return getattr(settings, 'SITE_OWNER_USERNAME', '') or ''


def is_site_owner(user) -> bool:
    name = owner_username()
    return bool(name) and getattr(user, 'username', None) == name


def launch_days(today: date | None = None) -> int:
    return max(((today or timezone.localdate()) - LAUNCH_DATE).days, 0)


def visitors_total() -> int:
    from community.models import DailyVisitor
    return DailyVisitor.objects.aggregate(s=Sum('visitor_count'))['s'] or 0


def _compute() -> dict:
    from community.models import DailyVisitor, Question
    today = timezone.localdate()
    row = DailyVisitor.objects.filter(date=today).first()
    lab = Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False)
    episodes = lab.filter(series__isnull=False).count()
    total = lab.count()
    return {
        'launch_days': launch_days(today),
        'visitors_total': visitors_total(),
        'visitors_today': row.visitor_count if row else 0,
        'lab_columns': total,
        'lab_essays': total - episodes,
        'lab_episodes': episodes,
        'as_of': today.strftime('%Y.%m.%d'),
    }


def stats() -> dict:
    return cache.get_or_set(CACHE_KEY, _compute, CACHE_SECONDS)


def display(key: str, values: dict) -> str:
    v = values[key]
    return f'{v:,}' if isinstance(v, int) else str(v)


# <태그 ... data-tc-stat="키" ...>글자</태그> — 안쪽이 태그 없는 글자일 때만 바꾼다
_TAG = re.compile(r'(<(?P<tag>[a-zA-Z][\w-]*)\b[^<>]*\bdata-tc-stat=["\'](?P<key>[a-z_]+)["\'][^<>]*>)'
                  r'(?P<inner>[^<]*)(</(?P=tag)\s*>)')


def fill_stat_tags(html: str) -> str:
    """HTML 안의 data-tc-stat 자리에 최신 통계를 넣는다. 모르는 키나 표시가 없으면 그대로 둔다."""
    if 'data-tc-stat' not in html:
        return html
    values = stats()

    def sub(m):
        if m.group('key') not in values:
            return m.group(0)
        return m.group(1) + display(m.group('key'), values) + m.group(5)

    return _TAG.sub(sub, html)
