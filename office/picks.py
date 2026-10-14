"""프리미엄 칼럼 — 편집 심사 최종 점수가 PREMIUM_SCORE(90) 이상인 연구팀 칼럼.

발행 기준과 프리미엄 기준은 다르다(2026-10-14 운영자 결정).
  - 발행: 필수 수정과 치명 결함이 없으면 나간다(office.review_protocol.accept_after_revision).
  - 프리미엄: 그중 최종 점수 90점 이상. 홈 카드·칼럼 상세·메이킹 오브에 표시.
    80점(64편 중 61편) → 85점(50편) → 90점으로 올렸다. 10월 초 리메이크 일괄 점수가 90점대로 후해 변별력이 없었다.
예전의 '추천'(85점)은 프리미엄 하나로 합쳤다 — 배지가 두 단계면 독자에게 구분이 안 된다.

최종 점수는 그 글의 마지막 판 기준이다. 처음 발행(ColumnDraft) 뒤에 리메이크·교열본 심사로 제자리 갱신됐으면
그 실행의 점수가 최종이다(StageRun question=…: 'applied', 또는 예전 리메이크의 통과 'final').
발행·갱신 기록(WorkLog publish '… (id=N, 83점)')도 원천이다 — 10월 초 리메이크 일괄은 점수를 여기에만 남겼다.

단, 심사 개편(REVIEW_REFORM, 2026-10-10 필수/제안 분리·근거 묶음) 전에 받은 **리메이크** 점수는 세지 않는다.
그 일괄 리메이크는 지금보다 후한 심사로 90점대를 받아, 리메이크한 글이 전부 프리미엄으로 떴다(운영자 지적).
처음 제작 때 받은 점수와 개편 뒤 리메이크·교열본 심사 점수는 그대로 센다. 옛 리메이크 점수뿐인 글은
다시 심사받기 전까지 프리미엄이 아니다.
점수 체계가 생기기 전에 쓰인 칼럼은 점수가 없어 대상이 아니다. 홈은 자주 열리므로 10분 캐시한다.
"""
from __future__ import annotations

import re

from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

PREMIUM_SCORE = 90
CACHE_KEY = 'home:premium:v6'
REVIEW_REFORM = datetime(2026, 10, 10, 12, 0)    # 79ee858 배포 — 이 전의 리메이크 점수는 세지 않는다
_LOG_SCORE = re.compile(r'\(id=(\d+),\s*(\d+)점')


def _score(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def final_scores() -> dict:
    """{question_id: 마지막 판의 편집 심사 점수} — 연구팀 칼럼 전부(점수 있는 것만)."""
    from office.models import ColumnDraft, StageRun, WorkLog
    from office.publiclog import is_remake
    latest = {}
    reform = timezone.make_aware(REVIEW_REFORM)

    def put(qid, at, score, remake=False):
        if remake and at < reform:          # 개편 전 리메이크 점수 — 후한 심사라 세지 않는다
            return
        if qid and score is not None and (qid not in latest or at >= latest[qid][0]):
            latest[qid] = (at, score)

    for d in (ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED)
              .only('question_id', 'target_question_id', 'qa_report', 'created_at', 'decided_at')):
        at = d.decided_at or d.created_at
        put(d.question_id or d.target_question_id, at, d.qa_score, remake=not d.question_id)
    for r in StageRun.objects.filter(question__isnull=False, stage__in=('applied', 'final')).only(
            'question_id', 'stage', 'output', 'created_at'):
        o = r.output or {}
        if r.stage == 'applied' or o.get('verdict') == 'accept':   # 리메이크는 통과해야만 반영됐다
            put(r.question_id, r.created_at, _score(o.get('score')), remake=True)
    for w in WorkLog.objects.filter(action='publish', text__contains='id=').only('action', 'text', 'created_at'):
        m = _LOG_SCORE.search(w.text or '')
        if m:
            put(int(m.group(1)), w.created_at, int(m.group(2)), remake=is_remake(w))
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
