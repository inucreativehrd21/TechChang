"""변경분만 검증할 수 있는 보수적인 조건. 원문·코드·주장 범위 변경은 전체 확인한다."""
import difflib
import re


def scope_check(subject, content, before, previous):
    if not previous or previous.get('verdict') != 'pass' or previous.get('subject') != subject or not before:
        return None
    # 출처나 코드가 바뀌면 기존 인용이 더 이상 유효하다고 가정할 수 없다.
    for pattern in (r'https?://[^\s)]+', r'```.*?```'):
        if re.findall(pattern, before, re.S) != re.findall(pattern, content, re.S):
            return None
    old, new = before.split('\n\n'), content.split('\n\n')
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    changed = []
    for operation, _a, _b, a, b in matcher.get_opcodes():
        if operation != 'equal':
            changed.extend(new[max(0, a-1):min(len(new), b+1)])
    excerpt = '\n\n'.join(dict.fromkeys(changed))
    if not excerpt.strip() or len(excerpt) > len(content)*0.6:
        return None
    preserved = [dict(c) for c in previous.get('claims', []) if c.get('status') == 'verified'
                 and c.get('claim_id') and c.get('claim') in before and c.get('claim') in content
                 and c.get('claim') not in excerpt]
    if not preserved:
        return None
    return {'content': '[변경 구간과 인접 문단 — 이 구간의 모든 사실·인과·참조를 검증하세요]\n' + excerpt,
            'preserved': preserved,
            'metadata': {'mode': 'delta', 'preserved_claim_ids': [c['claim_id'] for c in preserved],
                         'reviewed_chars': len(excerpt), 'total_chars': len(content)}}
