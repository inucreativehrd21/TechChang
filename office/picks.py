"""프리미엄 칼럼 — 편집 심사 최종 점수가 PREMIUM_SCORE(80) 이상인 연구팀 칼럼.

발행 기준과 프리미엄 기준은 다르다(2026-10-14 운영자 결정).
  - 발행: 필수 수정과 치명 결함이 없으면 나간다(office.review_protocol.accept_after_revision).
  - 프리미엄: 그중 최종 점수 80점 이상(루브릭 전 항목 4점 수준). 홈 카드·칼럼 상세·메이킹 오브에 표시.
예전의 '추천'(85점)은 프리미엄 하나로 합쳤다 — 배지가 두 단계면 독자에게 구분이 안 된다.

최종 점수는 그 글의 마지막 판 기준이다. 처음 발행(ColumnDraft) 뒤에 리메이크·교열본 심사로 제자리 갱신됐으면
그 실행의 점수가 최종이다(StageRun question=…: 'applied', 또는 예전 리메이크의 통과 'final').
점수 체계가 생기기 전에 쓰인 칼럼은 점수가 없어 대상이 아니다. 홈은 자주 열리므로 10분 캐시한다.
"""
from __future__ import annotations

from django.core.cache import cache

PREMIUM_SCORE = 80
CACHE_KEY = 'home:premium:v2'


def _score(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def final_scores() -> dict:
    """{question_id: 마지막 판의 편집 심사 점수} — 연구팀 칼럼 전부(점수 있는 것만)."""
    from office.models import ColumnDraft, StageRun
    latest = {}

    def put(qid, at, score):
        if qid and score is not None and (qid not in latest or at >= latest[qid][0]):
            latest[qid] = (at, score)

    for d in (ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED)
              .only('question_id', 'target_question_id', 'qa_report', 'created_at', 'decided_at')):
        at = d.decided_at or d.created_at
        put(d.question_id or d.target_question_id, at, d.qa_score)
    for r in StageRun.objects.filter(question__isnull=False, stage__in=('applied', 'final')).only(
            'question_id', 'stage', 'output', 'created_at'):
        o = r.output or {}
        if r.stage == 'applied' or o.get('verdict') == 'accept':   # 리메이크는 통과해야만 반영됐다
            put(r.question_id, r.created_at, _score(o.get('score')))
    return {qid: s for qid, (_at, s) in latest.items()}


def _compute() -> dict:
    from community.models import Question
    live = set(Question.objects.filter(is_deleted=False).values_list('id', flat=True))
    return {qid: s for qid, s in final_scores().items() if s >= PREMIUM_SCORE and qid in live}


def premium_scores() -> dict:
    """{question_id: 최종 점수} — 프리미엄 칼럼만."""
    try:
        return cache.get_or_set(CACHE_KEY, _compute, 600)
    except Exception:  # noqa: BLE001 — 배지 표시 실패로 페이지가 깨지면 안 된다
        return {}


pick_scores = premium_scores     # 예전 이름(홈·사이트맵)
