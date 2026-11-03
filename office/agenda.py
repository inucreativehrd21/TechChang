"""공개 화면용 안건 — 회의 선택지 제목(내부 기획 문장)을 독자가 읽을 형태로 바꾼다.

회의 선택지 제목은 편집회의가 쓰는 작업 지시라 '기존 칼럼 /123/ 보강: 제목·도입부에 … 앞세우기',
''AI 에이전트, 직접 만들어 봅니다' 3회 발행' 같은 모양이다. 공개 연구실·위클리에는 무엇이 나오는지만 보여 준다.
  - 새 글: 제목 그대로
  - 다듬는 글: 글 번호를 실제 글 제목·링크로(무엇을 고치는지는 public_note 가 설명한다)
  - 연재: 연재 이름 + 회차, 연재 페이지 링크
"""
from __future__ import annotations

import re

from django.urls import reverse

KIND_NEW, KIND_REFRESH, KIND_SERIES = 'new', 'refresh', 'series'
KIND_LABEL = {KIND_NEW: '새 글', KIND_REFRESH: '다듬는 글', KIND_SERIES: '연재'}

_REF = re.compile(r'(?<![\w/])/(\d+)/')
_REFRESH_WORDS = re.compile(r'보강|손질|다듬|고치|수정|개편')
_EPISODE = re.compile(r'(\d+)\s*(?:회|편)')


def _series_for(text: str):
    from community.models import ColumnSeries
    for s in ColumnSeries.objects.all():
        if s.title and s.title in text:
            return s
    # 'Django 시리즈 8편'처럼 연재 이름을 줄여 쓴 경우 — 연재 제목의 영문 핵심어로 찾는다
    for s in ColumnSeries.objects.all():
        words = re.findall(r'[A-Za-z][A-Za-z0-9+.#-]{2,}', s.title or '')
        if any(re.search(rf'\b{re.escape(w)}\b', text, re.I) for w in words):
            return s
    return None


def public_item(decision) -> dict | None:
    """선택된 안건 하나 → {'kind', 'kind_label', 'title', 'url', 'episode', 'note', 'topic'}. 선택이 없으면 None."""
    from community.models import Question
    from office.models import Decision
    chosen = decision.chosen or {}
    raw = str(chosen.get('title') or '').strip()
    if not raw:
        return None
    item = {'kind': KIND_NEW, 'title': raw, 'url': '', 'episode': '', 'note': decision.public_note or '',
            'topic': decision.topic}
    if decision.kind == Decision.KIND_SERIES:
        series = _series_for(raw)
        ep = _EPISODE.search(raw)
        item.update(kind=KIND_SERIES, episode=f'{ep.group(1)}회' if ep else '')
        if series:
            item.update(title=series.title, url=reverse('community:series_detail', args=[series.slug]))
        else:       # 연재를 못 찾으면 따옴표 안의 이름만 남긴다
            quoted = re.search(r"[‘'\"“](.+?)[’'\"”]", raw)
            item['title'] = quoted.group(1) if quoted else _EPISODE.sub('', raw).replace('발행', '').strip(' ·')
    else:
        ref = _REF.search(raw)
        if ref and _REFRESH_WORDS.search(raw):
            q = Question.objects.filter(pk=int(ref.group(1)), is_deleted=False).only('id', 'subject').first()
            item['kind'] = KIND_REFRESH
            if q:
                item.update(title=q.subject, url=reverse('community:detail', args=[q.pk]))
            else:   # 글이 없으면 번호와 작업 지시를 걷어 낸다
                item['title'] = re.sub(r'\s+', ' ', _REF.sub('', raw.split(':', 1)[-1])).strip(' ,·')
    item['kind_label'] = KIND_LABEL[item['kind']] + (f' {item["episode"]}' if item['episode'] else '')
    return item


def reader_title(decision) -> str:
    """한 줄로 쓸 곳(위클리 일정 등) — '다듬는 글 · 제목', '연재 3회 · 연재 이름'. 새 글은 제목만."""
    item = public_item(decision)
    if not item:
        return ''
    return item['title'] if item['kind'] == KIND_NEW else f"{item['kind_label']} · {item['title']}"
