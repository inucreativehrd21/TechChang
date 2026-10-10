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
    items = must_fix_items(previous)
    if not items:
        return ''
    lines = '\n'.join(f'{i}. [{m.get("where", "")}] {m.get("problem", "")} → 완료 기준: {m.get("done_when", "") or m.get("fix", "")}'
                      for i, m in enumerate(items, 1))
    return (
        '\n\n[직전 심사의 필수 수정 사항 — 이번 심사는 이것부터 판정합니다]\n' + lines + '\n'
        '- 출력 JSON 에 "resolved": [true/false, ...] 를 위 순서대로 넣으세요.\n'
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
    return items[:MAX_MUST_FIX]


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
                          for i in (qa.get('issues') or []) if str(i).strip()][:MAX_MUST_FIX]
        qa['suggestions'] = []
    return qa


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
    before = must_fix_items(previous)
    keep, demoted = [], []
    for m in qa.get('must_fix') or []:
        snips = [sn for sn in _snippets(str(m.get('where', ''))) if len(sn) >= 8]
        stale = (bool(snips) and all(sn in prev_content and sn in content for sn in snips)
                 and not _seen_before(m, before))
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
