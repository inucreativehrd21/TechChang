"""연구원 무기고 P1 — 분야 지식 팩·모범 칼럼 서고·링크 점검. 모델 호출 없음.

- knowledge_pack(topic): office/knowledge/*.md — 하우스 스타일 + 분야별 핵심 틀·근거 약한 통념·국내 자료원.
  writing_standard(topic) 에 붙어 집필·재작성·운영자 재작성·리메이크 모든 경로에 들어간다.
- exemplar(topic): 같은 분야에서 85점 이상으로 발행된 최고 점수 칼럼의 도입·구성·데이터 절·편집장 강점 발췌.
  칼럼니스트에게는 '이 수준', 편집장에게는 채점 기준점(점수 흔들림을 줄인다).
- dead_links(content): 본문·참고 자료의 URL 을 실제로 열어 보고, 없어진 링크(404·410·연결 실패)를 찾는다.
  차단(401·403·429)은 '확인 불가'로 따로 둔다 — 봇을 막는 정상 사이트를 죽은 링크로 몰지 않기 위해.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent / 'knowledge'
EXEMPLAR_MIN_SCORE = 85


@lru_cache(maxsize=8)
def _read(name: str) -> str:
    path = KNOWLEDGE_DIR / f'{name}.md'
    return path.read_text(encoding='utf-8').strip() if path.exists() else ''


def knowledge_pack(topic_key: str = '') -> str:
    parts = [_read('house')] + ([_read(topic_key)] if topic_key else [])
    return '\n\n'.join(p for p in parts if p)


# ───────────────────────────── 모범 칼럼 서고
def _section(content: str, name: str, limit: int) -> str:
    m = re.search(rf'^##\s*{name}[^\n]*\n+(.+?)(?:\n\n|\Z)', content or '', re.M | re.S)
    return re.sub(r'\s+', ' ', m.group(1)).strip()[:limit] if m else ''


def exemplar(topic_key: str = '') -> dict | None:
    """같은 분야 → 없으면 전체에서, 85점 이상으로 발행된 최고 점수 칼럼."""
    from office.models import ColumnDraft
    try:
        qs = ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED, question__isnull=False,
                                        question__is_deleted=False).select_related('question')
        best = None
        for d in qs:
            score = d.qa_score or 0
            if score < EXEMPLAR_MIN_SCORE:
                continue
            rank = (d.topic == topic_key, score, d.created_at)
            if best is None or rank > best[0]:
                best = (rank, d)
        if not best:
            return None
        d = best[1]
        content = d.question.content or ''
        lede = next((p.strip() for p in content.split('\n\n') if p.strip() and not p.lstrip().startswith(('#', '!', '|', '>'))), '')
        return {
            'title': d.question.subject, 'score': d.qa_score, 'same_topic': d.topic == topic_key,
            'lede': re.sub(r'\s+', ' ', lede)[:300],
            'headings': re.findall(r'^##\s+(.+)$', content, re.M)[:10],
            'data_para': _section(content, '숫자로 보는 현황', 350),
            'strengths': str((d.qa_report or {}).get('strengths', ''))[:300],
        }
    except Exception:  # noqa: BLE001 — 서고 조회 실패가 집필을 막으면 안 된다
        logger.exception('모범 칼럼 조회 실패')
        return None


def exemplar_block(topic_key: str = '', *, for_editor: bool = False) -> str:
    ex = exemplar(topic_key)
    if not ex:
        return ''
    if for_editor:
        return (f"\n\n[채점 기준점 — 발행된 모범 칼럼]\n「{ex['title']}」 {ex['score']}점. 강점: {ex['strengths']}\n"
                '이 글과 비교해 점수를 매기세요. 이 수준이면 해당 항목 4~5점입니다.\n')
    lines = ['', '', f"[모범 칼럼 — 이 수준을 목표로 하세요: 「{ex['title']}」 편집 심사 {ex['score']}점]",
             f"도입: {ex['lede']}", f"구성: {' / '.join(ex['headings'])}"]
    if ex['data_para']:
        lines.append(f"데이터 절 첫 문단: {ex['data_para']}")
    if ex['strengths']:
        lines.append(f"편집장이 꼽은 강점: {ex['strengths']}")
    lines.append('구성·밀도·데이터 다루는 방식을 참고하되, 문장과 소재를 베끼지 마세요.')
    return '\n'.join(lines) + '\n'


# ───────────────────────────── 링크 점검
_URL = re.compile(r'https?://[^\s)\]」>"\'<,]+')
DEAD = {404, 410}
BLOCKED = {401, 403, 405, 429}
UA = 'Mozilla/5.0 (compatible; TechChangLinkCheck/1.0; +https://techchang.com)'


def _status(url: str) -> int:
    """HTTP 상태 코드. 연결 자체가 안 되면 0."""
    for method in ('HEAD', 'GET'):
        req = urllib.request.Request(url, method=method, headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if method == 'HEAD' and e.code in (403, 405, 501):
                continue          # HEAD 를 막는 사이트 — GET 으로 한 번 더
            return e.code
        except Exception:  # noqa: BLE001
            if method == 'HEAD':
                continue
            return 0
    return 0


def dead_links(content: str, limit: int = 20) -> dict:
    """{'dead': [(url, code)], 'blocked': [(url, code)]} — 정상 링크는 돌려주지 않는다."""
    urls = list(dict.fromkeys(u.rstrip('.') for u in _URL.findall(content or '')))[:limit]
    if not urls:
        return {'dead': [], 'blocked': []}
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(_status, urls))
    dead = [(u, c) for u, c in zip(urls, codes) if c in DEAD or c == 0 or c >= 500]
    blocked = [(u, c) for u, c in zip(urls, codes) if c in BLOCKED]
    return {'dead': dead, 'blocked': blocked}


def link_block(result: dict) -> str:
    if not result.get('dead'):
        return ''
    lines = ['', '', '[링크 점검 — 시스템이 본문 URL 을 실제로 열어 본 결과]',
             '아래 링크는 열리지 않습니다(없는 페이지·연결 실패). 해당 출처는 원문을 다시 찾아 확인하고, '
             '찾지 못하면 그 주장을 unverifiable 로 판정하세요.']
    lines += [f'- {u} ({c or "연결 실패"})' for u, c in result['dead']]
    return '\n'.join(lines) + '\n'
