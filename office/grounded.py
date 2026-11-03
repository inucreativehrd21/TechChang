"""원장 대조 사실 관문 — 웹을 다시 열지 않고, 수집 때 저장한 원문 발췌로 원고의 주장을 판정한다.

왜(2026-10-31 B 파일럿): 완성 원고 검증은 매번 웹을 다시 열어 Codex 입력 22만·11만 토큰을 썼고, 변경분 검증은
직전 판정이 pass 일 때만 작동해 실제로는 늘 전체 재탐색이었다. 근거 문서에 대한 사실 대조는 웹 탐색이 아니라
'문장 ↔ 발췌' 대조다(MiniCheck, EMNLP 2024). 웹은 원장에 근거가 없는 주장에만, 상한을 두고 쓴다(SAFE).

안전장치는 모델과 무관하게 코드가 건다.
- 모델이 낸 인용(quote)은 원장 발췌 안에 실제로 있어야 한다. 없으면 근거 없음으로 내린다.
- 원장 항목의 URL·위치·대상·기간을 코드가 붙인다(모델이 지어낼 자리가 없다). 이후 계약 검사(validate_check)는 같다.
- 코드 실행 결과는 URL 대신 실행 기록으로 근거가 된다(office.code_check).
"""
from __future__ import annotations

import json
import re

# 원장에 없는 주장 중 웹으로 확인할 최대 개수. 기본 0 — 2026-11-01 v3 파일럿에서 6개 웹 확인이 643k 토큰(원장 대조의
# 30배)을 썼다. 원장 밖 주장은 확인 불가로 두고 '근거 범위로 좁히거나 삭제'하는 수정 대상으로 돌린다(근거 먼저 원칙).
GROUNDED_WEB_MAX = None       # 테스트가 숫자로 바꿔 끼운다. 평소에는 스위치(office.switches 'grounded_web_max')


def web_max() -> int:
    if GROUNDED_WEB_MAX is not None:
        return GROUNDED_WEB_MAX
    from .switches import get
    return int(get('grounded_web_max'))
OUT_OF_LEDGER = '원장 밖 주장 — 근거 원장의 범위로 좁히거나 문장을 지우세요.'
EXCERPT_CHARS = 800

PROMPT = (
    '사실 관문입니다. **웹을 열지 마세요.** 아래 [근거 원장]의 발췌만으로 원고의 사실 주장을 판정합니다.\n'
    '사실 주장: 수치·API·코드 동작·인용·사례·비교·인과·일반화. 절차 안내·권고·필자의 의견 문장은 세지 않습니다.\n'
    '**확인할 가치가 있는 주장만 최대 25개** 고르세요. 같은 사실을 여러 문장이 되풀이하면 하나로 묶고, '
    '판단 기준·비교표·실행 예제·자주 하는 실수의 핵심 주장을 먼저 고릅니다.\n'
    '- verified: 발췌가 주장의 대상·범위·조건을 그대로 지지. evidence 에 원장 번호, quote 에 발췌 속 문장을 **그대로** 옮깁니다.\n'
    '  quote 는 원장 발췌의 원문(영어면 영어) 한두 문장입니다. **원고 문장이나 요약을 quote 에 쓰지 마세요** — '
    '시스템이 발췌와 글자 단위로 대조해, 발췌에 없으면 근거 없음으로 처리합니다.\n'
    '- wrong: 발췌가 주장과 다름. evidence·quote 와 함께 value 에 발췌가 말하는 정확한 표현.\n'
    '- needs_source: 원장에 이 주장을 판단할 발췌가 없음. 추측으로 verified·wrong 을 정하지 마세요.\n'
    '발췌가 주장보다 좁은 범위만 말하면(예: 특정 예제·조건) verified 가 아니라 wrong 이고, value 에 좁힌 표현을 씁니다.\n\n'
    '[이미 발행한 칼럼 제목]\n{titles}\n\n[원고]\nTITLE: {subject}\n{content}\n\n[근거 원장]\n{ledger}\n\n'
    '출력 JSON: {{"claims": [{{"claim": "원고 문장을 한 줄로", "status": "verified|wrong|needs_source", '
    '"evidence": "E3", "quote": "발췌 속 문장 그대로", "value": "", "note": "판단 근거 한 줄"}}], '
    '"duplicate": false, "similar_titles": [], "notes": "고칠 것 3~6줄"}}'
)


def enabled() -> bool:
    from .switches import get
    return bool(get('grounded_check'))


def entries(*sources, code_facts: str = '', documents: list | None = None) -> list[dict]:
    """원장 항목 — 확인된(또는 원문 값으로 바로잡은) 주장만, URL·인용이 있는 것만. 같은 주장은 한 번.
    documents: 코드가 받은 근거 문서 문단(office.sources.entries) — 문단 전체가 발췌다."""
    out, seen = [], set()
    for rows in sources:
        for r in rows or []:
            if not isinstance(r, dict) or r.get('status') not in ('verified', 'wrong', 'outdated'):
                continue
            quote, url = str(r.get('quote') or '').strip(), str(r.get('url') or '').strip()
            if not quote or not url.startswith('http'):
                continue
            fact = (r.get('value') if r.get('status') != 'verified' else None) or r.get('value') or r.get('claim')
            key = (str(fact).strip(), url)
            if key in seen:
                continue
            seen.add(key)
            out.append({'fact': str(fact).strip(), 'quote': quote, 'url': url,
                        'context': str(r.get('context') or '')[:EXCERPT_CHARS],
                        'source_locator': r.get('source_locator') or '', 'population': r.get('population') or '',
                        'period': r.get('period') or '', 'source_date': r.get('source_date') or ''})
    for line in (code_facts or '').splitlines():
        from .code_check import ITEM
        if line.startswith(ITEM) and ': 통과' in line:
            out.append({'fact': line[len(ITEM):].strip(), 'quote': line[len(ITEM):].strip(), 'url': '',
                        'kind': 'execution', 'context': '', 'source_locator': '본문 코드 실행(임시 앱·메모리 DB)',
                        'population': '본문 예제 코드', 'period': '이번 실행'})
    out += list(documents or [])
    for i, e in enumerate(out, 1):
        e['id'] = f'E{i}'
    return out


def ledger_text(items: list[dict]) -> str:
    lines = []
    for e in items:
        src = '본문 코드 실행 결과' if e.get('kind') == 'execution' else e['url']
        if e.get('kind') == 'document':          # 문서 문단은 통째로 — 이 문단이 대조 재료다
            lines.append(f"{e['id']}. [문서] {e['fact']} · {e['source_locator']}\n    {e['quote']}\n    출처: {src}")
            continue
        lines.append(f"{e['id']}. {e['fact']}\n    원문: \"{e['quote'][:300]}\"" +
                     (f"\n    앞뒤 문단: {e['context']}" if e.get('context') else '') +
                     f"\n    출처: {src} · 위치 {e['source_locator'] or 'unknown'} · 대상 {e['population'] or 'unknown'}"
                     f" · 기간 {e['period'] or 'unknown'}")
    return '\n'.join(lines) or '(원장 비어 있음)'


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip().strip('"“”\'').strip()


def _letters(text: str) -> str:
    """구두점·따옴표·공백·대소문자 차이를 지운 글자열 — 인용 대조용."""
    return re.sub(r'[^0-9a-z가-힣]', '', str(text or '').lower())


MIN_QUOTE = 15   # 인용 조각의 최소 글자 수(구두점 제외) — 짧은 낱말 하나로 근거를 꾸미지 못하게


def quoted_in(quote: str, excerpt: str) -> bool:
    """인용이 발췌 안에 있는가. 생략 부호(… / ...)로 나눈 조각은 각각 발췌에 있어야 한다.
    2026-11-01 재생: 모델이 문서와 일치한다고 판정한 5건이 생략 부호·구두점 차이로 내려갔다."""
    # 2026-11-01 재생 2회차: 실제 문서 문장 4건이 서로 떨어진 두 문장을 생략 표시 없이 이어 붙여 내려갔다 — 문장 단위로 나눈다
    pieces = [_letters(p) for p in re.split(r'…|\.\.\.|\[\.\.\.\]|\n+|(?<=[.!?])\s+', quote or '')]
    pieces = [p for p in pieces if p]
    target = _letters(excerpt)
    return (bool(pieces) and sum(map(len, pieces)) >= MIN_QUOTE and all(len(p) >= 4 for p in pieces)
            and all(p in target for p in pieces))


def attach(claim: dict, items: dict) -> dict:
    """모델 판정에 원장 항목을 붙인다. 인용이 그 발췌 안에 없으면 근거 없음(needs_source)으로 내린다.
    가리킨 항목이 아니라 다른 항목에 인용이 있으면 그 항목으로 고쳐 붙인다(번호만 잘못 적은 경우)."""
    c = dict(claim)
    status = c.get('status')
    if status not in ('verified', 'wrong'):
        c['status'] = 'needs_source'
        return c
    quote = _norm(c.get('quote'))
    e = items.get(str(c.get('evidence') or '').strip())
    def text(x):
        return x['quote'] + ' ' + x.get('context', '')
    if not (e and quoted_in(quote, text(e))):
        e = next((x for x in items.values() if quoted_in(quote, text(x))), None)
    if not e and quoted_in(quote, ' '.join(text(x) for x in items.values())):
        # 문장마다 다른 항목에 있다 — 가장 긴 문장이 든 항목을 근거 위치로 삼는다
        longest = max((p for p in re.split(r'…|\.\.\.|\n+|(?<=[.!?])\s+', quote) if p.strip()), key=len)
        e = next((x for x in items.values() if _letters(longest) in _letters(text(x))), None)
    if not e:
        c['status'] = 'needs_source'
        c['note'] = f"[시스템] 원장 발췌에서 인용을 찾지 못해 근거 없음으로 내림 — {c.get('note', '')}"
        return c
    c.update({'quote': quote, 'url': e['url'], 'source_locator': e['source_locator'],
              'population': e['population'], 'period': e['period'], 'source_date': e.get('source_date') or 'unknown',
              'entailment': 'supported' if status == 'verified' else 'contradicted', 'grounded': e['id']})
    if e.get('kind') == 'execution':
        c['evidence_kind'] = 'execution'
    return c


def check(subject: str, content: str, items: list[dict], *, ask_json, titles: str = '', extra: str = '',
          web_tools: tuple = ()) -> dict:
    """원장 대조 → 원장에 없는 주장만 웹 확인(상한). 반환은 step_check 와 같은 모양(검증 전 claims)."""
    from . import evidence as E
    res = ask_json('checker', PROMPT.format(titles=titles or '(없음)', subject=subject, content=content,
                                            ledger=ledger_text(items)) + extra, max_tokens=6000)
    res = res if isinstance(res, dict) else {}
    by_id = {e['id']: e for e in items}
    claims = [attach(c, by_id) for c in res.get('claims') or [] if isinstance(c, dict) and c.get('claim')]
    missing = [c for c in claims if c['status'] == 'needs_source']
    web = []
    if missing and web_tools and web_max():
        web = E.gather([{'claim': c['claim']} for c in missing[:web_max()]], ask_json=ask_json, tools=web_tools)
    by_claim = {str(w.get('claim', '')).strip(): w for w in web}
    out = []
    for c in claims:
        if c['status'] != 'needs_source':
            out.append(c)
        elif c['claim'].strip() in by_claim:
            out.append({**by_claim[c['claim'].strip()], 'claim': c['claim']})
        else:
            # 원장 밖 주장은 고치기 쉬운 결함이다(좁히거나 지우면 된다) — 조기 보류의 '틀림' 수에 넣지 않는다
            out.append({**c, 'status': 'unverifiable', 'out_of_ledger': True,
                        'note': f"{OUT_OF_LEDGER} {c.get('note', '')}".strip()})
    return {'claims': out, 'duplicate': bool(res.get('duplicate')), 'similar_titles': res.get('similar_titles') or [],
            'notes': str(res.get('notes') or ''),
            'grounded': {'ledger': len(items), 'claims': len(claims), 'web_checked': len(web),
                         'needs_source': len(missing)}}


CLAIMS_PROMPT = (
    '집필 전 근거 확인입니다. **웹을 열지 마세요.** 아래 [근거 원장]의 발췌만으로 각 주장을 판정합니다.\n'
    '- verified: 발췌가 주장의 대상·범위·조건을 그대로 지지. evidence 에 원장 번호, quote 에 발췌 원문(영어면 영어) '
    '한두 문장을 그대로. 주장 문장을 quote 에 쓰지 마세요 — 시스템이 발췌와 글자 단위로 대조합니다.\n'
    '- wrong: 발췌가 다르게 말함. value 에 발췌가 말하는 정확한 표현(필요하면 범위를 좁힌 표현).\n'
    '- needs_source: 원장에 판단할 발췌가 없음. 추측하지 마세요.\n\n'
    '[주장]\n{claims}\n\n[근거 원장]\n{ledger}\n\n'
    '출력 JSON: {{"claims": [{{"n": 1, "status": "verified|wrong|needs_source", "evidence": "E3", '
    '"quote": "발췌 원문 그대로", "value": "", "note": "판단 근거 한 줄"}}]}}'
)


def verify_claims(claims: list[dict], items: list[dict], *, ask_json) -> list[dict]:
    """설계도의 주장을 원장(코드가 받은 문서 문단)과 대조한다 — 웹 없이 한 번. 반환은 주장 순서대로,
    계약 검사 전 행(status verified|wrong|unverifiable). 원장 밖 주장은 out_of_ledger 로 표시한다.
    2026-11-01 v3 파일럿: 모델의 웹 수집 4묶음이 506k 토큰을 썼다."""
    text = '\n'.join(f"{i}. {c['claim']}" for i, c in enumerate(claims, 1))
    res = ask_json('checker', CLAIMS_PROMPT.format(claims=text, ledger=ledger_text(items)), max_tokens=5000)
    got = {}
    for r in (res.get('claims') if isinstance(res, dict) else None) or []:
        try:
            got[int(r.get('n'))] = r
        except (TypeError, ValueError):
            continue
    by_id = {e['id']: e for e in items}
    out = []
    for i, c in enumerate(claims, 1):
        row = attach({**(got.get(i) or {'status': 'needs_source'}), 'claim': c['claim']}, by_id)
        if row['status'] == 'needs_source':
            row = {**row, 'status': 'unverifiable', 'out_of_ledger': True,
                   'note': f"{OUT_OF_LEDGER} {row.get('note', '')}".strip()}
        out.append(row)
    return out


def payload_size(subject: str, content: str, items: list[dict]) -> int:
    """프롬프트 글자 수 — 비용 비교용."""
    return len(PROMPT) + len(subject) + len(content) + len(ledger_text(items))


def dumps(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)
