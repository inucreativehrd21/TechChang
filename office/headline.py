"""제목 점검 — 심사와 별도로 제목을 점검표로 평가하고, 결이 다른 후보를 운영자에게 보여 줘요. (2026-11-23)

왜: 최근 제목이 "검색어, 설명" 공식으로 굳었어요(예: 「ADsP 점수와 합격 기준, 총점만 보면 놓치는 과락」).
원고 제목은 편집회의 선택지 제목에서 출발하는데, 선택지는 검색 수요 순으로 만들고 고르기 때문이에요. 제목 다듬기
지시문도 검색할 말을 앞세웠고, B 프로필은 제목 단계를 건너뛰었어요. 예전 칼럼(「일터의 스승은 동료다: 피어러닝의 귀환」)은
짧은 이미지와 핵심 개념을 한 호흡에 담았지만 "~의 시대", "~이 온다" 같은 상투구도 반복됐어요.

설계:
- 100점 심사표에는 넣지 않아요. 통과 기준(80·65)을 흔들지 않고, 점수 하나로는 '결'을 판정하기 어려워요.
- 점검표(예/아니요 질문)로 평가해요 — 직접 점수보다 사람 판단과 더 잘 맞는다는 연구(TICK, arXiv 2410.03608).
- 후보는 검색형·은유형·질문형으로 나눠 만들고, 제목은 자동으로 바꾸지 않아요. 운영자가 원고 카드에서 고르면
  재작성 요청(제목 요구)으로 들어가 사실 검증·심사를 다시 받아요(제목도 승인 지문에 묶여 있어요).
- 검색어는 첫 문단·소제목이 받아요(search_target_rule). 제목에 억지로 앞세우지 않아요.
"""
from __future__ import annotations

import hashlib
import json

STYLES = {'search': '검색형', 'image': '은유형', 'question': '질문형'}
# 운영자가 '자연스럽고 예쁘다'고 꼽은 예전 테크창 칼럼 제목의 결(2026-06~07 발행분 중심). 그대로 베끼지 않고 결만 참고해요.
EXEMPLARS = (
    '일터의 스승은 동료다: 피어러닝의 귀환',
    '심리적 안전감, 팀 학습의 숨겨진 엔진',
    '직원 경험(EX)이 곧 학습이다: HRD의 새 축',
    '직원 이탈을 예측하는 AI, 얼마나 믿을 수 있나',
    '숫자 뒤에 숨은 맥락, 인과추론이 온다',
    '교육을 안 받았다면 어땠을까, 반사실로 읽는 교육 효과 분석',
)
CHECKS = (
    ('answer', '본문이 실제로 답하는 질문이나 주장을 담았다'),
    ('natural', '소리 내 읽으면 자연스러운 한국어다(명사 나열·번역투·보고서 말투가 아니다)'),
    ('hook', '읽고 싶어지는 궁금증이나 이미지가 있다'),
    ('fresh', '"키워드, 설명" 쉼표 공식이나 최근 제목의 틀을 반복하지 않는다'),
    ('honest', '과장·단정·낚시가 없고 본문이 제목의 약속을 지킨다'),
)
CHECK_LABEL = dict(CHECKS)
MISS_LABEL = {'answer': '본문의 답이 드러나지 않음', 'natural': '말투가 딱딱함', 'hook': '끌림이 약함',
              'fresh': '최근 제목과 같은 틀', 'honest': '과장·약속 불일치', 'length': '길이(12~40자) 벗어남',
              'assert': '단정 표현', 'duplicate': '이미 쓴 제목과 같음'}

LAB_PROMPT = (
    '칼럼 제목 후보를 만듭니다. 편집장으로서 아래 칼럼에 어울리는 제목을 결이 다른 세 갈래로 두 개씩, 모두 6개 내세요.\n'
    '- search(검색형): 독자가 찾는 말을 담되 자연스러운 문장으로. 검색어를 맨 앞에 두고 쉼표로 설명을 붙이는 공식은 피해요.\n'
    '- image(은유형): 핵심을 짧은 이미지·대비로. 예전 테크창 제목의 결을 참고하되 베끼지 않아요.\n'
    '- question(질문형): 본문이 실제로 답하는 질문을 독자의 말로.\n\n'
    '[현재 제목] {subject}\n[독자가 검색할 만한 말 — 넣을 수 있으면 자연스럽게만] {keywords}\n'
    '[예전 테크창 제목의 결 — 참고용]\n{exemplars}\n[최근 제목 — 같은 틀을 반복하지 마세요]\n{recent}\n\n'
    '[본문 앞부분]\n{head}\n\n'
    '규칙: 12~40자. 과장·단정(반드시·유일한·결정적·정답) 금지. "~의 시대", "~이 온다", "종말" 같은 상투구 금지. '
    '본문에 없는 약속을 하지 않아요.\n'
    '출력 JSON: {{"candidates": [{{"title": "제목", "style": "search|image|question"}}]}}'
)

JUDGE_PROMPT = (
    '칼럼 제목 점검입니다. 아래 본문을 읽고, 각 제목이 점검 질문을 충족하는지 예(true)/아니요(false)로만 답하세요. '
    '제목끼리 순위를 매기지 말고 각 제목을 따로 판단하세요.\n\n'
    '[점검 질문]\n{checks}\n\n[최근 제목]\n{recent}\n\n[본문 앞부분]\n{head}\n\n[제목 목록]\n{titles}\n\n'
    '출력 JSON: {{"results": [{{"n": 1, {fields}}}]}} — 목록의 모든 번호를 빠짐없이.'
)


def code_misses(title: str, recent=()) -> list[str]:
    from .quality import _ASSERT
    misses = []
    if not 12 <= len(title) <= 40:
        misses.append('length')
    if _ASSERT.search(title):
        misses.append('assert')
    if title.strip() in {t.strip() for t in recent}:
        misses.append('duplicate')
    return misses


def _shuffled(titles: list[str], seed: str) -> list[str]:
    """목록 순서 편향을 줄이려 본문마다 다른(재현 가능한) 순서로 보여 줘요."""
    return sorted(titles, key=lambda t: hashlib.sha256((seed + t).encode()).hexdigest())


def review(subject: str, content: str, *, keywords=(), recent=(), ask_json=None) -> dict:
    """제목 점검 결과 — {'subject', 'current': {...}, 'candidates': [상위 3개], 'checks': [...]}.

    호출 2회(후보 만들기·점검). 실패하면 빈 dict — 제목 점검 때문에 제작을 막지 않아요."""
    from common.services.claude import call_tags
    from .pipeline import strip_visual_block
    if ask_json is None:
        from .services import ask_agent_json as ask_json
    recent = [t for t in recent if t and t != subject][:20]
    head = strip_visual_block(content)[:1800]
    with call_tags(stage='title_lab'):
        raw = ask_json('editor', LAB_PROMPT.format(
            subject=subject, keywords=', '.join(k for k in keywords if k) or '(없음)',
            exemplars='\n'.join(f'- {t}' for t in EXEMPLARS), recent='\n'.join(f'- {t}' for t in recent) or '(없음)',
            head=head), max_tokens=1500)
    pool, seen = [], {subject.strip()}
    for c in (raw or {}).get('candidates') or [] if isinstance(raw, dict) else []:
        if not isinstance(c, dict):
            continue
        title = str(c.get('title') or '').strip().strip('"「」')
        style = c.get('style') if c.get('style') in STYLES else 'search'
        if title and title not in seen:
            seen.add(title)
            pool.append({'title': title[:80], 'style': style})
    if not pool:
        return {}
    titles = _shuffled([subject] + [p['title'] for p in pool], content[:200])
    fields = ', '.join(f'"{k}": true' for k, _ in CHECKS)
    with call_tags(stage='title_lab'):
        judged = ask_json('editor', JUDGE_PROMPT.format(
            checks='\n'.join(f'- {k}: {label}' for k, label in CHECKS), recent='\n'.join(f'- {t}' for t in recent) or '(없음)',
            head=head, titles='\n'.join(f'{i}. {t}' for i, t in enumerate(titles, 1)), fields=fields), max_tokens=2000)
    by_n = {}
    for row in (judged or {}).get('results') or [] if isinstance(judged, dict) else []:
        if isinstance(row, dict) and isinstance(row.get('n'), int):
            by_n[row['n']] = row

    def grade(title):
        row = by_n.get(titles.index(title) + 1, {})
        misses = [k for k, _ in CHECKS if row.get(k) is not True] + code_misses(title, recent)
        total = len(CHECKS)
        passed = sum(row.get(k) is True for k, _ in CHECKS)
        return {'passed': passed, 'total': total, 'misses': [MISS_LABEL[m] for m in misses],
                'code_ok': not code_misses(title, recent), 'judged': bool(row)}

    current = grade(subject)
    current['ok'] = current['judged'] and current['code_ok'] and current['passed'] >= len(CHECKS) - 1
    graded = []
    for p in pool:
        g = grade(p['title'])
        if g['code_ok'] and g['judged']:
            graded.append({**p, **g, 'style_label': STYLES[p['style']]})
    # 점검 통과 수 → 결이 겹치지 않게 갈래마다 먼저 하나씩
    graded.sort(key=lambda c: -c['passed'])
    picked, styles = [], set()
    for c in graded:
        if c['style'] not in styles:
            picked.append(c)
            styles.add(c['style'])
    picked += [c for c in graded if c not in picked]
    return {'version': 1, 'subject': subject, 'current': current, 'candidates': picked[:3],
            'checks': [label for _, label in CHECKS]}


def enabled() -> bool:
    from . import switches as SW
    return bool(SW.get('title_lab'))


def attach(qa: dict, subject: str, content: str, *, keywords=(), recent=(), context=None, record=None) -> None:
    """심사 결과에 제목 점검을 붙여요. 꺼져 있거나 예산이 모자라거나 실패하면 붙이지 않아요."""
    if not enabled():
        return
    if context and not context.can_start_revision(calls=2, seconds=120):
        if record:
            record('title_lab', 'editor', {'reason': '예산 부족으로 제목 점검을 건너뛰었어요.'}, status='skipped')
        return
    try:
        result = review(subject, content, keywords=keywords, recent=recent)
    except Exception as exc:  # noqa: BLE001
        from common.services.cli_errors import ProviderUnavailable
        from .run_context import RunBudgetExceeded
        if isinstance(exc, (ProviderUnavailable, RunBudgetExceeded)):
            raise
        if record:
            record('title_lab', 'editor', {'reason': str(exc)[:300]}, status='failed')
        return
    if result:
        qa['title_review'] = result
        if record:
            record('title_lab', 'editor', json.loads(json.dumps(result, ensure_ascii=False)))
