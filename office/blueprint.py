"""집필 설계도와 사전 검증 — 본문을 쓰기 전에 '무엇을, 어떤 근거로' 쓸지 정하고 검증관이 먼저 확인한다.

왜(2026-10-11 분석): 최근 원고 22편 중 첫 심사 통과는 2편(9%), 첫 심사 평균 65.5점. 첫 심사의 치명 결함은
코드 오류(7)·과장(4)·근거 없는 수치(4)가 1~3위였다. 모두 '본문을 다 쓴 뒤에야 사실을 확인'하는 순서에서 나온다.
틀린 수치·없는 API가 본문 곳곳에 박힌 채 심사에 가고, 거기서부터 재작성 → 재검증 → 재심이 반복됐다.

그래서 순서를 바꾼다.
  1) 작가가 설계도를 낸다 — 독자 질문과 한 문장 답, 절 구성, 쓸 주장마다 근거, 핵심 표·그림, 도입부 약속과 회수 위치
  2) 검증관이 설계도의 주장을 본문 쓰기 전에 웹으로 확인한다 — 틀리거나 확인 안 되는 주장은 여기서 빠진다
  3) 작가는 '확인된 설계도'만 보고 본문을 쓴다
설계도 단계의 호출 2번이, 본문 이후의 재작성·재검증·재심 사이클(한 바퀴에 호출 4~6번)을 줄이는 것이 목표다.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

BLUEPRINT_PROMPT = (
    '본문을 쓰기 전에 설계도를 먼저 냅니다. 이 설계도는 검증관이 먼저 확인하고, 확인된 것만으로 본문을 쓰게 됩니다.\n\n'
    '{context}\n\n'
    '출력 JSON:\n'
    '{{"reader_question": "독자가 이 글에서 답을 얻고 싶은 질문 한 문장",\n'
    ' "thesis": "그 질문에 대한 이 글의 답 한 문장(과장 없이, 근거가 받쳐 주는 만큼만)",\n'
    ' "sections": [{{"heading": "절 제목", "point": "이 절에서 말할 것 한 줄"}}],\n'
    ' "claims": [{{"claim": "본문에 쓸 사실·수치·코드 동작·인용 하나", "source": "근거 URL 또는 공식 문서·보고서명", '
    '"kind": "stat|doc|code|case"}}],\n'
    ' "key_table": {{"title": "핵심 표 제목", "columns": ["열1", "열2"], "basis": "어떤 근거로 채우는지"}} 또는 null,\n'
    ' "visual": "그림이 보여 줄 비교 한 줄 — 글의 답(thesis)을 받쳐 주는 것. 없으면 빈 문자열",\n'
    ' "promises": ["도입부에서 던질 질문·약속 → 답하는 절 제목"]}}\n'
    '규칙:\n'
    '- claims 에는 본문에서 사실로 말할 것을 빠짐없이 넣으세요(6~14개). 근거를 모르는 것은 넣지 말고, 본문에도 쓰지 않습니다.\n'
    '- 필자가 정한 기준·묶음·점수는 kind 를 "doc" 이 아니라 claim 에 "필자 기준"이라고 적으세요. 공식 분류처럼 쓰지 않습니다.\n'
    '- 코드·명령은 실제로 존재하는 현재 버전의 것만. 확신이 없으면 웹 검색으로 공식 문서를 확인하세요.'
)

def make_blueprint(agent: str, context: str, *, ask_json, tools: tuple = ()) -> dict:
    """작가의 설계도. 실패하면 {} — 호출부는 설계도 없이 예전처럼 집필한다."""
    try:
        bp = ask_json(agent, BLUEPRINT_PROMPT.format(context=context), max_tokens=6000, tools=tools)
    except Exception as exc:  # noqa: BLE001 — 설계도는 품질 장치일 뿐, 실패해도 집필은 진행
        logger.warning('설계도 작성 실패: %s', exc)
        return {}
    return bp if isinstance(bp, dict) and bp.get('thesis') else {}


def verify_blueprint(bp: dict, *, ask_json, tools: tuple = (), extra: str = '') -> dict:
    """검증관의 사전 검증. 실패하면 {}.

    주장을 한 호출에 몰아 주면 앞의 몇 개만 열고 나머지를 '확인 불가'로 남겼다(#89·#100). 그래서 주장을
    몇 개씩 나눠 동시에 확인하고(office.evidence.gather), 원문 문장에 값이 없으면 verified 를 내린다.
    답(thesis)의 범위 판정은 확인 결과를 보고 따로 한 번 한다.
    """
    from . import evidence as E
    if not bp:
        return {}
    claims = [c for c in (bp.get('claims') or []) if isinstance(c, dict) and str(c.get('claim', '')).strip()]
    try:
        results = E.gather(claims, ask_json=ask_json, tools=tools, extra=extra)
    except Exception as exc:  # noqa: BLE001
        logger.warning('사전 검증 실패: %s', exc)
        return {}
    ver = {'claims': results, 'pack': E.pack_text(results)}
    ver.update({k: v for k, v in E.assess_thesis(bp, results, ask_json=ask_json).items()
                if k in ('thesis_ok', 'thesis_note', 'missing')})
    return ver


def summary(bp: dict, ver: dict) -> str:
    """작업 기록용 한 줄 — '설계도: 주장 N개 중 M개 확인'."""
    claims = ver.get('claims') or []
    ok = sum(1 for c in claims if isinstance(c, dict) and c.get('status') == 'verified')
    return (f"설계도: 주장 {len(bp.get('claims') or [])}개 중 {ok}개 원문 확인"
            + ('' if ver.get('thesis_ok', True) else ' · 답 범위 좁힘'))


def block(bp: dict, ver: dict) -> str:
    """집필 프롬프트에 붙이는 '확인된 설계도' — 확인된 주장만 쓰게 하고, 빠진 주장은 쓰지 말라고 못 박는다."""
    if not bp:
        return ''
    by_claim = {str(c.get('claim', '')).strip(): c for c in (ver.get('claims') or []) if isinstance(c, dict)}
    usable, dropped = [], []
    for c in bp.get('claims') or []:
        if not isinstance(c, dict):
            continue
        text = str(c.get('claim', '')).strip()
        v = by_claim.get(text, {})
        status = v.get('status', 'unverified' if ver else 'verified')
        if status == 'verified':
            fact = v.get('value') or text
            usable.append(f"- {fact} (원문: \"{str(v.get('quote', ''))[:160]}\" {v.get('url') or c.get('source', '')})")
        elif status in ('wrong', 'outdated') and v.get('value'):
            usable.append(f"- {v['value']} (검증관이 원문으로 바로잡은 값 — 원래 주장 '{text[:40]}'은 쓰지 마세요; "
                          f"원문: \"{str(v.get('quote', ''))[:160]}\" {v.get('url', '')})")
        else:
            dropped.append(f'- {text}')
    thesis = bp.get('thesis', '')
    if ver and not ver.get('thesis_ok', True) and ver.get('thesis_note'):
        thesis = f"{thesis} → 검증관 조정: {ver['thesis_note']}"
    lines = ['\n[확인된 설계도 — 본문은 이 설계도대로 쓰세요]',
             f"- 독자 질문: {bp.get('reader_question', '')}", f'- 이 글의 답: {thesis}']
    if bp.get('sections'):
        lines.append('- 절 구성: ' + ' / '.join(f"{s.get('heading', '')}({s.get('point', '')})"
                                              for s in bp['sections'] if isinstance(s, dict)))
    if usable:
        lines += ['- 사실로 써도 되는 주장(원문 확인됨) — **본문의 수치는 이 목록에 있는 값만 씁니다**. '
                  '여기 없는 숫자는 자동 점검에서 걸리고, 그래도 남으면 그 문장이 지워집니다:'] + [f'  {u}' for u in usable]
    if dropped:
        lines += ['- **쓰면 안 되는 주장**(확인되지 않음 — 본문에서 사실로 말하지 마세요):'] + [f'  {d}' for d in dropped]
    kt = bp.get('key_table')
    if isinstance(kt, dict) and kt.get('title'):
        lines.append(f"- 핵심 표: \"### 표 1. {kt['title']}\" 제목으로 실제로 싣기 — 열: {', '.join(kt.get('columns') or [])}")
    if bp.get('visual'):
        lines.append(f"- 그림이 보여 줄 것: {bp['visual']}")
    if bp.get('promises'):
        lines.append('- 도입부 약속과 회수 위치(본문에서 반드시 답할 것): ' + ' / '.join(map(str, bp['promises'])))
    if ver.get('missing'):
        lines.append('- 검증관이 짚은 빠진 근거(찾을 수 있으면 보강, 못 찾으면 그 주장을 하지 마세요): '
                     + ' / '.join(map(str, ver['missing'])))
    return '\n'.join(lines) + '\n'
