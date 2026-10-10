"""칼럼 지도 — 칼럼마다 소주제·키워드·요약을 만들어 두고, 칼럼이 바뀌면 다시 만든다.

- content_hash(): 제목+본문 해시. 저장된 요약의 해시와 다르면 낡은 것(stale)으로 본다.
- pending(): 요약이 없거나 낡은 연구팀 칼럼.
- make(): 편집장이 요약을 쓴다. 같은 카테고리의 기존 소주제를 보여 줘서 이름을 맞추게 하고(지도가 잘게 쪼개지지
  않게), 요약에 나온 수치가 본문에 실제로 있는지 코드로 대조한다(office.evidence) — 없으면 한 번 다시 쓰게 하고,
  그래도 남으면 그 문장을 지운다. 연재 회차는 소주제를 연재 제목으로 고정한다.
- 갱신은 저장 신호(office.signals)가 백그라운드 명령(update_column_map)을 띄워서 한다 — 요청 안에서 모델을 부르지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

AGENT = 'editor'
MAX_BODY = 9000          # 요약에 넘길 본문 길이 상한(참고 자료·이미지 제외 뒤)

PROMPT = (
    '칼럼 지도에 실을 항목을 만듭니다. 아래 칼럼을 끝까지 읽고 정리하세요. 평가는 하지 않습니다.\n\n'
    '[카테고리] {category}\n[이 카테고리에서 이미 쓰는 소주제] {subtopics}\n\n'
    '[칼럼]\nTITLE: {subject}\n---\n{content}\n\n'
    '출력 JSON: {{"subtopic": "소주제(2~6어절)", "keywords": ["키워드", ...], "summary": "요약"}}\n'
    '규칙:\n'
    '- subtopic: 위 기존 소주제 중 맞는 것이 있으면 **그 이름을 그대로** 쓰세요. 정말 맞는 것이 없을 때만 새 이름을 짓습니다.\n'
    '- keywords: 칼럼이 실제로 다루는 개념·방법·도구·자료·기관 4~6개. "HRD"·"데이터"·"개발" 같은 일반어는 빼세요.\n'
    '- summary: 2~3문장, 120~200자, 존댓말(~합니다). 칼럼의 핵심 질문·주장, 핵심 근거(주요 자료 이름과, 있으면 핵심 수치 하나), '
    '실무 시사점을 담습니다. **칼럼에 적힌 것만** 쓰고 바깥 사실이나 평가를 더하지 마세요. 수치는 본문에 있는 값 그대로 옮깁니다.'
    '{retry}'
)

_IMG = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_REFS = re.compile(r'\n##\s*참고 자료.*', re.S)


def content_hash(q) -> str:
    return hashlib.sha1(f'{q.subject}\n{q.content}'.encode('utf-8')).hexdigest()


def category_key(q) -> str:
    if q.series_id:
        return 'series'
    return {'HRD': 'hrd', '데이터분석': 'data', '프로그래밍': 'coding'}.get(q.category.name if q.category else '', 'etc')


def columns():
    """지도에 오르는 글 — 연구팀이 쓴, 지워지지 않은 글."""
    from community.models import Question
    return (Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False)
            .select_related('category', 'series'))


def pending(only_id: int | None = None) -> list:
    from .models import ColumnDigest
    qs = columns()
    if only_id:
        qs = qs.filter(pk=only_id)
    have = dict(ColumnDigest.objects.filter(question__in=qs).values_list('question_id', 'content_hash'))
    return [q for q in qs.order_by('create_date') if have.get(q.pk) != content_hash(q)]


def existing_subtopics(cat: str) -> list[str]:
    from collections import Counter
    from .models import ColumnDigest
    c = Counter(d.subtopic for d in ColumnDigest.objects.select_related('question__category', 'question__series')
                if category_key(d.question) == cat)
    return [t for t, _ in c.most_common()]


def _loose_numbers(summary: str, content: str) -> list[str]:
    from . import evidence as E
    have = E.keys_in(content)
    return [n for n in E.significant(summary) if E.key(n) not in have]


def _clean(res: dict) -> dict | None:
    if not isinstance(res, dict):
        return None
    kws = [str(k).strip() for k in (res.get('keywords') or []) if str(k).strip()][:8]
    summary = str(res.get('summary') or '').strip()
    subtopic = str(res.get('subtopic') or '').strip()[:60]
    if not summary or not kws or not subtopic:
        return None
    return {'subtopic': subtopic, 'keywords': kws, 'summary': summary}


def make(q, *, ask_json=None) -> dict | None:
    """칼럼 하나의 지도 항목. 실패하면 None."""
    from . import evidence as E
    if ask_json is None:
        from .services import ask_agent_json as ask_json
    cat = category_key(q)
    body = _REFS.sub('', _IMG.sub('', q.content or ''))[:MAX_BODY]
    subs = existing_subtopics(cat)
    category = f'연재 「{q.series.title}」' if q.series_id else (q.category.name if q.category else '기타')
    retry = ''
    item = None
    for _ in range(2):
        try:
            res = ask_json(AGENT, PROMPT.format(category=category, subtopics=', '.join(subs) or '(아직 없음)',
                                                subject=q.subject, content=body, retry=retry), max_tokens=1500)
        except Exception as exc:  # noqa: BLE001
            logger.warning('칼럼 지도 요약 실패 #%s: %s', q.pk, exc)
            return None
        item = _clean(res)
        if item is None:
            retry = '\n\n직전 응답에 subtopic·keywords·summary 중 빠진 것이 있었습니다. 세 항목을 모두 채우세요.'
            continue
        loose = _loose_numbers(item['summary'], q.content)
        if not loose:
            break
        retry = (f"\n\n직전 요약의 수치 {', '.join(loose)}은(는) 칼럼 본문에 없습니다. 본문에 있는 값만 쓰거나 "
                 '그 수치를 빼고 다시 쓰세요.')
    if item is None:
        return None
    loose = _loose_numbers(item['summary'], q.content)
    if loose:      # 두 번째에도 본문에 없는 수치가 남으면 그 문장을 지운다
        item['summary'], _removed = E.drop_sentences(item['summary'], loose)
        item['summary'] = item['summary'].strip()
        if not item['summary']:
            return None
    if q.series_id:
        item['subtopic'] = q.series.title          # 연재 회차는 연재 제목 아래에 모은다
    return item


def save(q, item: dict, *, source: str = 'lab'):
    from .models import ColumnDigest
    ColumnDigest.objects.update_or_create(question=q, defaults={**item, 'content_hash': content_hash(q),
                                                                'source': source})


def refresh(*, only_id: int | None = None, limit: int = 50, out=None, ask_json=None) -> dict:
    """요약이 없거나 낡은 칼럼을 다시 만든다. 반환 {'done': n, 'failed': [id], 'left': n}."""
    todo = pending(only_id)
    done, failed = 0, []
    for q in todo[:limit]:
        item = make(q, ask_json=ask_json)
        if item is None:
            failed.append(q.pk)
            continue
        save(q, item)
        done += 1
        if out:
            out(f'  #{q.pk} [{item["subtopic"]}] {q.subject[:40]}')
    return {'done': done, 'failed': failed, 'left': max(0, len(todo) - limit)}


def import_items(rows: list) -> int:
    """미리 만든 요약(JSON: id·subtopic·keywords·summary)을 현재 본문 해시로 들여온다."""
    from community.models import Question
    n = 0
    for r in rows:
        q = Question.objects.filter(pk=r.get('id')).select_related('series').first()
        item = _clean(r)
        if q is None or item is None:
            continue
        if q.series_id:
            item['subtopic'] = q.series.title
        save(q, item, source='import')
        n += 1
    return n
