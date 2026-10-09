"""글 하단 '함께 읽으면 좋은 칼럼' — 본문 소재가 가까운 연구팀 칼럼 3편.

내부 링크는 검색엔진이 칼럼끼리의 주제 묶음을 파악하고 크롤러가 오래된 칼럼까지 다시 찾아오게 하는
가장 값싼 수단이다(2026-10-09 SEO 2단계). 유사도는 검증관이 쓰는 office.similarity 를 그대로 쓰고,
모델 호출은 없다. 칼럼 60여 편을 매 요청마다 토큰화하면 느리므로 글별로 하루 캐시한다 —
칼럼 수가 바뀌면 캐시 키가 바뀌어 새 칼럼이 바로 후보에 들어온다.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

LIMIT = 3
MIN_TOPIC = 0.15        # 이보다 소재가 멀면 '관련'이라 부르기 어렵다
CACHE_TTL = 60 * 60 * 24


def related_columns(question, limit: int = LIMIT) -> list[dict]:
    """[{id, subject, category}] — 실패하거나 후보가 없으면 []."""
    from community.models import Question

    try:
        count = Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False).count()
        key = f'related:v1:{question.id}:{count}:{int(question.modify_date.timestamp()) if question.modify_date else 0}'
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = _compute(question, limit)
        cache.set(key, result, CACHE_TTL)
        return result
    except Exception:  # noqa: BLE001 — 부가 블록 때문에 본문 페이지가 깨지면 안 된다
        logger.exception('관련 칼럼 계산 실패: question=%s', getattr(question, 'id', None))
        return []


def _compute(question, limit: int) -> list[dict]:
    from community.models import Question
    from office.similarity import compare

    # 같은 시리즈 회차는 이미 이전·다음 편 안내가 있으니 뺀다
    qs = (Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False, is_locked=False)
          .exclude(id=question.id).select_related('category').only('id', 'subject', 'content', 'series_id',
                                                                     'category__name'))
    if question.series_id:
        qs = qs.exclude(series_id=question.series_id)
    scored = []
    for q in qs:
        r = compare(question.content or '', q.content or '')
        if r['topic'] >= MIN_TOPIC:
            scored.append((r['topic'] + r['shingle'] * 3, q))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{'id': q.id, 'subject': q.subject, 'category': q.category.name if q.category else ''}
            for _s, q in scored[:limit]]
