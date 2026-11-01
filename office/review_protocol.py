"""편집 심사의 지적 규약 — '필수 수정'과 '제안'을 나누고, 재심은 직전 필수 수정의 해결 여부부터 본다.

왜 필요한가(2026-10-11 분석): 최근 원고 22편 중 첫 심사 통과는 2편, 심사를 8~9번 받은 원고도 있었다.
원고 #36 은 재심마다 편집장이 새 지적을 꺼냈다(표 1 → Gradle 사례 → 대응표 축소 …). 작가가 지난 지적을
다 고치면 새 지적이 나오고, 그걸 고치느라 통째로 다시 쓰다 다른 곳이 무너졌다(50 → 65 → 59 → 58).
그래서 지적을 두 층으로 나눈다.

- must_fix: 고치지 않으면 발행할 수 없는 것만, 최대 5개, 위치·고칠 방법·완료 기준을 함께. 재작성은 이것만 처리한다.
- suggestions: 더 좋아질 제안. 발행을 막지 않고, 재작성 지시로 넘기지 않는다.
- 재심: 직전 must_fix 를 하나씩 해결/미해결로 판정한다. 새 must_fix 는 이번 판에서 새로 생긴 문제나
  치명 결함일 때만 — 직전에 문제 삼지 않았던 곳을 새로 문제 삼는 것은 suggestions 로만.

2026-10-10 보강(레거시 #89·#100): 프롬프트로만 "새 지적 금지"를 걸었더니 재심마다 필수 수정이 5 → 5 → 4건으로
대부분 새로 나왔다. 그리고 수정 지시가 기억으로 새 수치를 들여왔다("10,035건으로 바꾸라" → 다음 재심에서 확인 불가).
- 첫 심사에서 발행을 막는 문제를 한 번에 다 내도록 상한을 8로 올린다.
- demote_stale(): 재심에서 새로 나온 필수 수정이 직전 판과 똑같은 문장을 가리키면(바뀌지 않은 곳) 제안으로 내린다.
- flag_numbers(): 수정 지시에 근거 묶음에 없는 수치가 있으면 '쓰지 말고 지우라'는 경고를 붙인다.
"""
from __future__ import annotations

import difflib
import re
import hashlib

MAX_MUST_FIX = 8

RULE = (
    '\n\n[지적 쓰는 법 — 반드시 지키세요]\n'
    '- "must_fix": 고치지 않으면 발행할 수 없는 것만, 최대 8개. **발행을 막는 문제는 이번 심사에서 한 번에 모두** '
    '적으세요 — 재심에서는 바뀌지 않은 문장을 새로 문제 삼을 수 없습니다. 각 항목은 '
    '{"where": "섹션 이름이나 문장 일부", "problem": "무엇이 문제인지", "fix": "어떻게 고치는지", '
    '"done_when": "해결됐다고 볼 기준"} 형태로 씁니다. 치명 결함(fatal)이 있으면 그 원인은 반드시 여기에 들어갑니다.\n'
    '- "suggestions": 발행을 막지 않는 개선 제안(문장 한 줄씩). 분량을 줄이라는 제안은 하지 마세요.\n'
    '- 고칠 방법(fix)에 **새 수치를 제시하지 마세요.** 확인되지 않은 수치는 "그 문장을 지우라"고 지시합니다. '
    '바꿀 값을 알려 주려면 [운영자 확인 사항]에 있는 값만 쓰세요 — 기억으로 준 값은 다음 심사에서 다시 '
    '확인 불가가 됩니다.\n'
    '- 출력 JSON 에 "must_fix" 와 "suggestions" 를 추가하세요. "issues" 에는 must_fix 를 먼저, 제안을 뒤에 적습니다.\n'
)


def previous_block(previous: dict | None) -> str:
    """재심 때 붙이는 블록 — 직전 필수 수정의 해결 여부부터 판정하게 한다."""
    if previous:
        attach_issue_ids(previous)
    items = must_fix_items(previous)
    if not items:
        return ''
    lines = '\n'.join(f'{i}. {m["issue_id"]} [{m.get("where", "")}] {m.get("problem", "")} → 완료 기준: {m.get("done_when", "") or m.get("fix", "")}'
                      for i, m in enumerate(items, 1))
    return (
        '\n\n[직전 심사의 필수 수정 사항 — 이번 심사는 이것부터 판정합니다]\n' + lines + '\n'
        '- 출력 JSON 에 "resolved": [true/false, ...] 를 위 순서대로 넣으세요. '
        '또한 "resolutions": {"issue_ID": {"resolved": true/false, "evidence": "해결됐거나 남아 있는 근거 문장"}}로 '
        '모든 직전 issue_id를 빠짐없이 판정하세요. 미해결 항목은 같은 issue_id를 must_fix에 유지하세요.\n'
        '- 해결된 항목은 다시 지적하지 마세요. 해결되지 않은 항목만 must_fix 에 다시 넣습니다.\n'
        '- 새 must_fix 는 이번 판에서 새로 생긴 문제(직전 판에 없던 문장·코드·수치)나 치명 결함일 때만 추가합니다. '
        '직전 심사에서 문제 삼지 않았던 부분을 새로 문제 삼고 싶다면 suggestions 로만 적으세요 — '
        '매번 새 필수 지적이 나오면 원고가 수렴하지 않습니다.\n'
    )


def must_fix_items(qa: dict | None) -> list[dict]:
    items = []
    for m in (qa or {}).get('must_fix') or []:
        if isinstance(m, dict) and (m.get('problem') or m.get('fix')):
            items.append(m)
        elif isinstance(m, str) and m.strip():
            items.append({'where': '', 'problem': m.strip(), 'fix': '', 'done_when': ''})
    for item in (qa or {}).get('open_issues', {}).values():
        if isinstance(item, dict) and item.get('issue_id') not in {m.get('issue_id') for m in items}:
            items.append(item)
    return items


def accept_after_revision(qa: dict) -> bool:
    """마지막 자동 재심의 '수정 요청'(minor)을 통과로 볼 수 있나 — 남은 것이 제안뿐일 때만.

    학술지의 minor revision 수리처럼 다루되, 필수 수정(must_fix)이 하나라도 남았으면 운영자 검수로 넘긴다.
    2026-10-13 #115 가 필수 수정 4건(서두 조건 개수 불일치·비교 주장 수위·자기 선언·현황 절 연결)을 남긴 채
    70점으로 발행돼서 막았다."""
    return (qa.get('verdict') == 'minor' and not qa.get('fatal') and not must_fix_items(qa)
            and not unresolved(qa))


def unresolved(qa: dict) -> int:
    """재심에서 '해결 안 됨'으로 판정된 직전 필수 수정 수. 2026-10-15 #116: 편집장이 6건 중 2건 미해결이라고 적었는데
    그 2건이 다른 문구로 다시 지적되며 '바뀌지 않은 곳의 새 지적'으로 제안에 내려가, 필수 수정 0건으로 67점 발행됐다."""
    return max(sum(1 for r in (qa.get('resolved') or []) if r is False),
               len(qa.get('unresolved_issue_ids') or []))


def attach_issue_ids(qa: dict) -> dict:
    """위치·문제의 고정 식별자를 부여한다. 표시 문자열과 분리해 다음 판에서도 사용한다."""
    qa['must_fix'] = must_fix_items(qa)
    for item in qa['must_fix']:
        if not item.get('issue_id'):
            text = '\n'.join(str(item.get(k, '')).strip() for k in ('where', 'problem'))
            item['issue_id'] = 'issue_' + hashlib.sha256(text.encode()).hexdigest()[:16]
    return qa


def blocked(qa: dict) -> bool:
    return bool(qa.get('fatal') or must_fix_items(qa) or unresolved(qa))


def publishable(qa: dict) -> bool:
    return qa.get('verdict') == 'accept' and not blocked(qa)


def finalize(qa: dict, previous: dict | None = None) -> dict:
    """모든 진입 경로에서 점수가 필수 결함을 무효화하지 못하게 한다."""
    attach_issue_ids(qa)
    from .model_router import profile
    if profile() == 'b':
        qa['review_contract_version'] = 2
    if previous and profile() == 'b':
        attach_issue_ids(previous)
        resolutions = qa.get('resolutions')
        resolutions = resolutions if isinstance(resolutions, dict) else {}
        current = {m['issue_id'] for m in qa.get('must_fix') or []}
        unresolved_ids = []
        open_issues = {}
        for item in must_fix_items(previous):
            iid = item['issue_id']
            result = resolutions.get(iid)
            # truthy 문자열/누락/판정 근거 없음은 해결로 보지 않는다.
            solved = (isinstance(result, dict) and result.get('resolved') is True
                      and bool(str(result.get('evidence') or '').strip()) and iid not in current)
            if not solved:
                unresolved_ids.append(iid)
                open_issues[iid] = item
        qa['unresolved_issue_ids'] = unresolved_ids
        qa['open_issues'] = open_issues
    if blocked(qa) and qa.get('verdict') == 'accept':
        qa['verdict'] = 'major' if qa.get('fatal') else 'minor'
    if qa.get('fatal'):
        qa['verdict'] = 'major'
    if (profile() == 'b' and qa.get('verdict') == 'minor' and not blocked(qa)
            and isinstance(qa.get('score'), (int, float)) and qa['score'] >= 65):
        qa['verdict'] = 'accept'
        qa['accepted_by_contract'] = True
    qa['issues'] = [as_line(m) for m in must_fix_items(qa)] + [f'(제안) {s}' for s in qa.get('suggestions', [])]
    return qa


def require_check(qa: dict, check: dict, content: str, subject: str = '') -> None:
    """B의 독립 검증 차단은 편집장 점수로 무효화할 수 없다."""
    from .model_router import profile
    if profile() != 'b':
        return
    from .pipeline import verification_hash
    stale = (check.get('verification_hash') != verification_hash(content)
             or check.get('subject') != subject)
    if stale or check.get('verdict') != 'pass':
        qa.setdefault('fatal', []).append('verification_stale' if stale else 'unverified_data')
        qa.setdefault('must_fix', []).append({
            'where': '독립 검증', 'problem': '현재 원고 버전의 독립 검증이 완료되지 않았어요.',
            'fix': '해당 버전의 주장·출처를 다시 검증해요.', 'done_when': '현재 content_hash로 pass 판정'})
    else:
        from .recorder import digest
        qa['verified_content_hash'] = verification_hash(content)
        qa['reviewed_full_hash'] = digest(content)
        qa['verified_subject'] = subject


def as_line(m: dict) -> str:
    where = f"[{m['where']}] " if m.get('where') else ''
    fix = f" → {m['fix']}" if m.get('fix') else ''
    done = f" (완료 기준: {m['done_when']})" if m.get('done_when') else ''
    return f"{where}{m.get('problem', '')}{fix}{done}".strip()


def normalize(qa: dict) -> dict:
    """must_fix·suggestions 를 정리하고, issues(관리 화면·메이킹 오브가 읽는 목록)를 그 순서로 맞춘다.
    모델이 새 필드를 안 주면 기존 issues 를 must_fix 로 본다 — 예전 동작과 같다."""
    items = must_fix_items(qa)
    sugg = [str(s).strip() for s in (qa.get('suggestions') or []) if str(s).strip()]
    if items or sugg:
        qa['must_fix'] = items
        qa['suggestions'] = sugg
        qa['issues'] = [as_line(m) for m in items] + [f'(제안) {s}' for s in sugg]
    else:
        qa['must_fix'] = [{'where': '', 'problem': str(i), 'fix': '', 'done_when': ''}
                          for i in (qa.get('issues') or []) if str(i).strip()]
        qa['suggestions'] = []
        qa['issues'] = [as_line(m) for m in qa['must_fix']]
    return attach_issue_ids(qa)


def revision_notes(qa: dict | None) -> list[str]:
    """재작성 지시로 넘길 것 — 필수 수정만. 제안은 넘기지 않는다(고칠 범위를 좁혀 다른 곳이 무너지지 않게)."""
    items = must_fix_items(qa)
    if items:
        return [as_line(m) for m in items]
    return [str(i) for i in ((qa or {}).get('issues') or []) if not str(i).startswith('(제안)')]


# 지적의 '어디'에서 원고 문장을 인용한 부분 — 「…」 '…' "…" ‘…’ “…”
_QUOTED = re.compile(r"[「'\"‘“]([^」'\"’”]{8,}?)[」'\"’”]")


def _snippets(where: str) -> list[str]:
    return [m.group(1).rstrip('…. ').strip() for m in _QUOTED.finditer(where or '')]


def _seen_before(item: dict, previous: list[dict]) -> bool:
    text = f"{item.get('where', '')} {item.get('problem', '')}"
    return any(difflib.SequenceMatcher(None, text, f"{p.get('where', '')} {p.get('problem', '')}").ratio() >= 0.5
               for p in previous)


def demote_stale(qa: dict, previous: dict | None, prev_content: str, content: str) -> list[str]:
    """재심의 새 필수 수정 중 '바뀌지 않은 문장'을 가리키는 것을 제안으로 내린다. 반환: 내린 항목 줄.

    치명 결함이 있으면 손대지 않는다 — 치명 결함의 원인은 필수 수정으로 남아야 한다.
    직전 필수 수정과 비슷한 항목(미해결 재지적)도 그대로 둔다.
    """
    if not previous or not prev_content or (qa.get('fatal') or []):
        return []
    if unresolved(qa):        # 직전 필수 수정이 남아 있으면, 다른 문구로 다시 지적된 그 항목일 수 있다 — 내리지 않는다
        return []
    before = must_fix_items(previous)
    from .model_router import profile
    keep, demoted = [], []
    for m in qa.get('must_fix') or []:
        snips = [sn for sn in _snippets(str(m.get('where', ''))) if len(sn) >= 8]
        stale = (bool(snips) and all(sn in prev_content and sn in content for sn in snips)
                 and not _seen_before(m, before))
        if profile() == 'b' and m.get('kind') != 'preference':
            stale = False  # 뒤늦게 발견한 사실·논리 결함은 기존 문장이어도 차단한다.
        (demoted if stale else keep).append(m)
    if demoted:
        qa['must_fix'] = keep
        qa['suggestions'] = list(qa.get('suggestions') or []) + [f'(재심 신규 — 바뀌지 않은 곳) {as_line(m)}'
                                                                  for m in demoted]
        qa['issues'] = [as_line(m) for m in keep] + [f'(제안) {x}' for x in qa['suggestions']]
    return [as_line(m) for m in demoted]


def flag_numbers(qa: dict, pack: str) -> int:
    """수정 지시(fix)에 근거 묶음에 없는 수치가 있으면 경고를 붙인다. 반환: 경고 붙인 항목 수."""
    from . import evidence as E
    have = E.keys_in(pack)
    if not have:
        return 0
    flagged = 0
    for m in qa.get('must_fix') or []:
        bad = [n for n in E.significant(str(m.get('fix', ''))) if E.key(n) not in have]
        if bad:
            m['fix'] = (f"{m.get('fix', '')} [시스템: {', '.join(bad)}은(는) 원문 확인된 근거에 없습니다 — 이 값을 "
                        '쓰지 말고 해당 문장을 지우거나 근거의 값만 쓰세요]')
            flagged += 1
    if flagged:
        qa['issues'] = [as_line(m) for m in qa['must_fix']] + [f'(제안) {x}' for x in (qa.get('suggestions') or [])]
    return flagged
