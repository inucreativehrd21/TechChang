"""편집 심사의 지적 규약 — '필수 수정'과 '제안'을 나누고, 재심은 직전 필수 수정의 해결 여부부터 본다.

왜 필요한가(2026-10-11 분석): 최근 원고 22편 중 첫 심사 통과는 2편, 심사를 8~9번 받은 원고도 있었다.
원고 #36 은 재심마다 편집장이 새 지적을 꺼냈다(표 1 → Gradle 사례 → 대응표 축소 …). 작가가 지난 지적을
다 고치면 새 지적이 나오고, 그걸 고치느라 통째로 다시 쓰다 다른 곳이 무너졌다(50 → 65 → 59 → 58).
그래서 지적을 두 층으로 나눈다.

- must_fix: 고치지 않으면 발행할 수 없는 것만, 최대 5개, 위치·고칠 방법·완료 기준을 함께. 재작성은 이것만 처리한다.
- suggestions: 더 좋아질 제안. 발행을 막지 않고, 재작성 지시로 넘기지 않는다.
- 재심: 직전 must_fix 를 하나씩 해결/미해결로 판정한다. 새 must_fix 는 이번 판에서 새로 생긴 문제나
  치명 결함일 때만 — 직전에 문제 삼지 않았던 곳을 새로 문제 삼는 것은 suggestions 로만.
"""
from __future__ import annotations

MAX_MUST_FIX = 5

RULE = (
    '\n\n[지적 쓰는 법 — 반드시 지키세요]\n'
    '- "must_fix": 고치지 않으면 발행할 수 없는 것만, 최대 5개. 각 항목은 '
    '{"where": "섹션 이름이나 문장 일부", "problem": "무엇이 문제인지", "fix": "어떻게 고치는지", '
    '"done_when": "해결됐다고 볼 기준"} 형태로 씁니다. 치명 결함(fatal)이 있으면 그 원인은 반드시 여기에 들어갑니다.\n'
    '- "suggestions": 발행을 막지 않는 개선 제안(문장 한 줄씩). 분량을 줄이라는 제안은 하지 마세요.\n'
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
