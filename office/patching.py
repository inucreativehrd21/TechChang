"""패치식 수정 — 지적받은 곳만 바꾸고 나머지는 한 글자도 건드리지 않는다.

왜(2026-10-11 분석): 지적이 나오면 작가가 원고 전체를 다시 썼다. 그 과정에서 이미 검증을 통과한 문장·코드·수치가
바뀌어 새 문제가 생겼고, 재심 점수가 오르지 않고 흔들렸다(#36: 50 → 65 → 59 → 58). 전체 재작성은 고칠 범위를
작가 판단에 맡기는 셈이라, 지적 하나를 고치려다 다른 세 곳이 무너진다.

그래서 작가는 '이 문자열을 → 이렇게' 편집 목록만 낸다. 코드는 각 편집이 원고에서 정확히 한 번 나오는지 확인하고
적용한다. 일치하지 않는 편집이 절반을 넘으면(구조를 통째로 바꿔야 하는 지적 등) 호출부가 전체 재작성으로 넘어간다.
"""
from __future__ import annotations

import logging
import re

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
    '- 지적과 관계없는 곳은 고치지 마세요. 지적 하나에 편집이 여러 개여도 됩니다.\n'
    '- 근거가 없다고 지적된 문장은 확인된 근거(문서 인용·실행 결과)로 바꾸거나 지우세요. '
    '"필자의 추론", "~로 보입니다"처럼 약하게 바꾸는 편집은 거절됩니다.'
)

# 근거 없는 주장을 덮는 약화 표현 — 새로 들어오면 편집을 거절한다(unsupported)
# '필자의 판단·생각'은 권고·의견을 밝히는 정당한 표시라 넣지 않는다(2026-11-03 atomic 5차: 트레이드오프 절을 막음)
HEDGE = re.compile(r'(?:필자|글쓴이|저자)(?:의|가 보기에는?)\s*(?:추론|해석|추정|짐작)'
                   r'|(?:추론|추정|짐작)(?:입니다|됩니다|해 봅니다|할 수 있습니다)'
                   r'|것으로\s*(?:보입니다|추정됩니다|짐작됩니다)|로\s*해석됩니다')


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


def unsupported(edit: dict, pack: str) -> list[str]:
    """편집이 새로 들이는 근거 없는 수치·단정. 원래 문장(find)에 있던 것과 근거 묶음에 있는 것은 허용한다.

    왜(2026-10-31 B 파일럿): 수정이 매번 새 결함을 만들었다(v1 수정본에 새로 틀린 테스트 주장 3건, v2 패치 29건 뒤
    새 오류 1건). 외부 근거 없이 스스로 고치면 맞던 것도 틀리게 바뀐다(Huang et al., ICLR 2024). 수치는 근거 묶음,
    단정은 기계 점검이 외부 기준이다.
    """
    from . import evidence as E
    from .quality import overclaims
    find, repl = str(edit.get('find') or ''), str(edit.get('replace') or '')
    out = [f'수치 {n}' for n, _ in E.unmatched(repl, f'{pack}\n{find}')]
    old = set(overclaims(find))
    out += [f'단정 「{x[:30]}」' for x in overclaims(repl) if x not in old]
    # 근거 없는 문장을 '필자의 추론'으로 약하게 바꾸는 것은 고친 것이 아니다 — 원장 인용으로 바꾸거나 지운다
    # (2026-11-02 atomic 2차: '기록 없이 사라진다'를 추론으로 바꿔 robust=True 문서와 어긋난 채 남았다)
    # 약화는 기존 문장을 바꿀 때만 본다 — 원래 문단을 그대로 두고 뒤에 새 내용을 덧붙이는 편집은 해당 없다
    from .switches import get
    if get('hedge_reject') and not (find.strip() and find in repl):
        out += [f'추론으로 약화 「{m.group(0)}」' for m in HEDGE.finditer(repl) if m.group(0) not in find]
    return out


def patch_revise(agent: str, subject: str, content: str, issues: list, *, who: str, guide: str = '',
                 tools: tuple = (), max_tokens: int = 12000, ask_json=None, pack: str | None = None) -> tuple:
    """반환 (subject, content, ok, why). ok=False 면 원고는 그대로 — 호출부가 전체 재작성으로 넘어간다.
    ask_json: 모델 호출 함수(기본 services.ask_agent_json) — 호출부의 것을 넘기면 테스트에서 함께 대체된다.
    pack: 근거 묶음 — 주면 근거 없는 수치·단정을 새로 들이는 편집을 거절한다(원래 문장을 유지)."""
    if ask_json is None:
        from .services import ask_agent_json as ask_json
    if not issues:
        return subject, content, False, '고칠 지적 없음'
    try:
        res = ask_json(agent, PATCH_PROMPT.format(
            who=who, issues='\n'.join(f'- {i}' for i in issues), subject=subject, content=content, guide=guide),
            max_tokens=max_tokens, tools=tools)
    except Exception as exc:  # noqa: BLE001 — 패치가 안 되면 전체 재작성으로 넘어간다
        from .run_context import RunBudgetExceeded
        from .execution import LeaseLost
        from common.services.cli_errors import ProviderUnavailable
        if isinstance(exc, (RunBudgetExceeded, LeaseLost, ProviderUnavailable)):
            raise
        logger.warning('패치 수정 호출 실패: %s', exc)
        return subject, content, False, f'패치 호출 실패: {exc}'[:200]
    edits = [e for e in (res.get('edits') or []) if isinstance(e, dict)]
    blocked = []
    if pack is not None:
        screened = []
        for e in edits:
            why_not = unsupported(e, pack)
            (blocked if why_not else screened).append({**e, 'blocked': why_not} if why_not else e)
        edits = screened
        # 편집을 하나씩 적용하며 코드 정적 점검을 다시 본다 — 2026-11-01 v3 파일럿에서 패치가 tests.py 들여쓰기를
        # 깨뜨려 실행 근거가 사라졌고, 실행 결과에 기대던 주장이 근거 없음이 됐다
        from .code_check import static_issues
        base = len(static_issues(content))
        new_content, applied, failed = content, 0, []
        for e in edits:
            nxt, ok_n, _bad = apply_edits(new_content, [e])
            if not ok_n:
                failed.append(e)
            elif len(static_issues(nxt)) > base:
                blocked.append({**e, 'blocked': ['코드 블록을 깨뜨림']})
            else:
                new_content, applied = nxt, applied + 1
    else:
        new_content, applied, failed = apply_edits(content, edits)
    if not applied or len(failed) * 2 > len(edits):
        reason = f'패치 {len(edits)}건 중 {len(failed)}건이 원고와 일치하지 않음'
        if blocked:
            reason += f', 검사에 걸린 편집 {len(blocked)}건 거절({"; ".join(blocked[0]["blocked"])[:80]})'
        return subject, content, False, reason
    new_subject = str(res.get('title') or '').strip() or subject
    # 무엇이 왜 막혔는지 남긴다 — 2026-11-03 atomic 4차에서 거절 3건의 내용을 알 수 없어 규칙의 과잉 거절을 판정하지 못했다
    detail = ' / '.join(f'{"·".join(b["blocked"])[:60]} ← 「{" ".join(str(b.get("find") or "").split())[:40]}」'
                        for b in blocked)
    for b in blocked:
        logger.info('패치 편집 거절 %s: find=%r replace=%r', b['blocked'], str(b.get('find'))[:200],
                    str(b.get('replace'))[:300])
    why = (f'패치 {applied}건 적용' + (f', {len(failed)}건 불일치' if failed else '')
           + (f', 검사에 걸린 편집 {len(blocked)}건 거절: {detail}' if blocked else ''))
    return new_subject, new_content, True, why
