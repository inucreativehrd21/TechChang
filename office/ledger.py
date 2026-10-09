"""검증 원장 — 검증관이 원문을 대조한 사실을 쌓고, 다음 팩트체크에 다시 보여 준다(office.models.VerifiedFact).

- record(): 팩트체크 결과에서 근거 URL 이 붙은 판정(verified·wrong·outdated)만 저장한다.
  URL 없는 판정은 '확인했다'는 증거가 없으므로 원장에 넣지 않는다.
- ledger_block(): 원고에 나온 수치와 같은 수치를 담은 원장 항목을 찾아 검증관 프롬프트에 붙인다.
  같은 값이면 원장의 URL 로 빠르게 재확인하고, 값이 다르면 원문을 다시 확인하게 한다.
기록 실패가 팩트체크를 멈추게 하면 안 된다 — 모든 DB 접근은 예외를 삼킨다.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_URL = re.compile(r'https?://[^\s)\]」>,]+')
_NUM = re.compile(r'\d[\d,]*(?:\.\d+)?\s*(?:%p|%|명|건|배|억|만|점|달러|원|곳|개국)')
_METHOD = re.compile(r'확인 방법\s*\(?([123])\)?|운영자 원문 확인')
KEEP = ('verified', 'wrong', 'outdated')


def _key(claim: str) -> str:
    return re.sub(r'\s+', '', claim)[:200]


def _method(note: str) -> str:
    m = _METHOD.search(note or '')
    if not m:
        return ''
    if m.group(0).startswith('운영자'):
        return '운영자'
    return {'1': '원문', '2': '보도 2곳+', '3': '학술 초록'}[m.group(1)]


def record(check: dict) -> int:
    """팩트체크 결과의 근거 있는 판정을 원장에 쌓는다. 반환: 저장·갱신한 건수."""
    from office.models import VerifiedFact

    saved = 0
    for c in (check or {}).get('claims') or []:
        if not isinstance(c, dict) or c.get('status') not in KEEP:
            continue
        claim, note = str(c.get('claim', '')).strip(), str(c.get('note', '')).strip()
        urls = list(dict.fromkeys(_URL.findall(note)))[:5]
        if not claim or not urls:
            continue
        try:
            fact = VerifiedFact.objects.filter(claim_key=_key(claim)).first()
            if fact:
                fact.status, fact.note, fact.urls = c['status'], note[:2000], urls
                fact.method = _method(note) or fact.method
                fact.times_seen += 1
                fact.save()
            else:
                VerifiedFact.objects.create(claim=claim[:500], claim_key=_key(claim), status=c['status'],
                                            note=note[:2000], urls=urls, method=_method(note))
            saved += 1
        except Exception:  # noqa: BLE001
            logger.exception('검증 원장 기록 실패')
    return saved


def related(content: str, limit: int = 8) -> list:
    """원고에 나온 수치를 담은 원장 항목."""
    from office.models import VerifiedFact

    nums = {re.sub(r'[\s,]', '', n) for n in _NUM.findall(content or '')}
    if not nums:
        return []
    out = []
    try:
        for fact in VerifiedFact.objects.all()[:500]:
            claim_nums = {re.sub(r'[\s,]', '', n) for n in _NUM.findall(fact.claim)}
            if claim_nums & nums:
                out.append(fact)
                if len(out) >= limit:
                    break
    except Exception:  # noqa: BLE001
        logger.exception('검증 원장 조회 실패')
    return out


def ledger_block(content: str) -> str:
    facts = related(content)
    if not facts:
        return ''
    ko = {'verified': '확인됨', 'wrong': '원문과 다름', 'outdated': '시점 지남'}
    lines = ['', '', '[검증 원장 — 이전 팩트체크에서 원문을 대조한 기록입니다]',
             '본문 수치가 아래와 같으면 기록된 URL 로 재확인하고, 값·연도·출처가 다르면 원문을 다시 확인하세요. '
             '"원문과 다름"으로 기록된 값이 또 나오면 그대로 지적하세요.']
    for f in facts:
        lines.append(f"- [{ko.get(f.status, f.status)}·{f.method or '방법 미상'}] {f.claim[:160]} — {f.urls[0]}")
    return '\n'.join(lines) + '\n'
