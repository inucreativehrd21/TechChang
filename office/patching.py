"""패치식 수정 — 지적받은 곳만 바꾸고 나머지는 한 글자도 건드리지 않는다.

왜(2026-10-11 분석): 지적이 나오면 작가가 원고 전체를 다시 썼다. 그 과정에서 이미 검증을 통과한 문장·코드·수치가
바뀌어 새 문제가 생겼고, 재심 점수가 오르지 않고 흔들렸다(#36: 50 → 65 → 59 → 58). 전체 재작성은 고칠 범위를
작가 판단에 맡기는 셈이라, 지적 하나를 고치려다 다른 세 곳이 무너진다.

그래서 작가는 '이 문자열을 → 이렇게' 편집 목록만 낸다. 코드는 각 편집이 원고에서 정확히 한 번 나오는지 확인하고
적용한다. 일치하지 않는 편집이 절반을 넘으면(구조를 통째로 바꿔야 하는 지적 등) 호출부가 전체 재작성으로 넘어간다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PATCH_PROMPT = (
    '{who} 아래 필수 수정 사항이 나왔습니다. **원고 전체를 다시 쓰지 말고, 고칠 곳만 바꾸는 편집 목록**을 내세요. '
    '잘 된 부분을 건드리면 재심에서 새 문제가 생깁니다.\n\n[필수 수정]\n{issues}\n\n'
    '[원고]\nTITLE: {subject}\n---\n{content}\n\n{guide}\n'
    '출력 JSON: {{"edits": [{{"find": "원고에 있는 그대로의 연속된 문자열 — 원고 안에서 딱 한 번 나오는 문장·문단·코드 줄", '
    '"replace": "바꿀 내용(지우려면 빈 문자열)"}}], "title": "제목을 바꿀 때만 새 제목, 아니면 빈 문자열"}}\n'
    '규칙:\n'
    '- find 는 원고에서 한 글자도 바꾸지 말고 그대로 복사하세요(공백·기호 포함). 너무 짧으면 여러 곳과 일치하니 '
    '문장 단위 이상으로 잡으세요.\n'
    '- 새 문단·표를 넣으려면 그 바로 앞 문단을 find 로 잡고, replace 에 그 문단 + 새 내용을 쓰세요.\n'
    '- 지적과 관계없는 곳은 고치지 마세요. 지적 하나에 편집이 여러 개여도 됩니다.'
)


def apply_edits(content: str, edits: list) -> tuple[str, int, list]:
    """편집 목록 적용. 반환 (새 본문, 적용 수, 실패한 편집[]). find 가 정확히 한 번 나와야 적용한다."""
    applied, failed = 0, []
    for e in edits or []:
        if not isinstance(e, dict):
            continue
        find, repl = str(e.get('find') or ''), str(e.get('replace') if e.get('replace') is not None else '')
        if len(find.strip()) < 4 or content.count(find) != 1:
            failed.append(e)
            continue
        content = content.replace(find, repl, 1)
        applied += 1
    return content, applied, failed


def patch_revise(agent: str, subject: str, content: str, issues: list, *, who: str, guide: str = '',
                 tools: tuple = (), max_tokens: int = 12000, ask_json=None) -> tuple:
    """반환 (subject, content, ok, why). ok=False 면 원고는 그대로 — 호출부가 전체 재작성으로 넘어간다.
    ask_json: 모델 호출 함수(기본 services.ask_agent_json) — 호출부의 것을 넘기면 테스트에서 함께 대체된다."""
    if ask_json is None:
        from .services import ask_agent_json as ask_json
    if not issues:
        return subject, content, False, '고칠 지적 없음'
    try:
        res = ask_json(agent, PATCH_PROMPT.format(
            who=who, issues='\n'.join(f'- {i}' for i in issues), subject=subject, content=content, guide=guide),
            max_tokens=max_tokens, tools=tools)
    except Exception as exc:  # noqa: BLE001 — 패치가 안 되면 전체 재작성으로 넘어간다
        logger.warning('패치 수정 호출 실패: %s', exc)
        return subject, content, False, f'패치 호출 실패: {exc}'[:200]
    edits = [e for e in (res.get('edits') or []) if isinstance(e, dict)]
    new_content, applied, failed = apply_edits(content, edits)
    if not applied or len(failed) * 2 > len(edits):
        return subject, content, False, f'패치 {len(edits)}건 중 {len(failed)}건이 원고와 일치하지 않음'
    new_subject = str(res.get('title') or '').strip() or subject
    why = f'패치 {applied}건 적용' + (f', {len(failed)}건 불일치' if failed else '')
    return new_subject, new_content, True, why
