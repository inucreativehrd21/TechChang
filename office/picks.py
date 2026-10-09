"""추천 칼럼 — 홈 카드에 '추천' 표시를 붙일 글.

기준: 연구팀 파이프라인을 거쳐 발행됐고, 편집 심사 점수가 PICK_SCORE 이상인 칼럼.
발행 기준(80점)보다 한 단계 높아야 '추천'이라는 말이 의미를 가진다. 점수 체계가 생기기 전에 쓰인
칼럼은 점수가 없어 대상이 아니다(리메이크로 다시 심사받으면 자동으로 들어온다).
홈은 자주 열리므로 10분 캐시한다.
"""
from __future__ import annotations

from django.core.cache import cache

PICK_SCORE = 85
CACHE_KEY = 'home:picks:v1'


def _compute() -> dict:
    from office.models import ColumnDraft
    out = {}
    drafts = ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED, question__isnull=False,
                                        question__is_deleted=False).only('question_id', 'qa_report')
    for d in drafts:
        score = d.qa_score
        if score is not None and score >= PICK_SCORE:
            out[d.question_id] = score
    return out


def pick_scores() -> dict:
    """{question_id: 편집 심사 점수} — 추천 칼럼만."""
    try:
        return cache.get_or_set(CACHE_KEY, _compute, 600)
    except Exception:  # noqa: BLE001 — 추천 표시 실패로 홈이 깨지면 안 된다
        return {}
