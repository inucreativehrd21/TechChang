"""공개 연구실(/lab/)에 내보낼 활동 로그를 다듬는다.

WorkLog.text 는 운영자가 관리 화면에서 읽는 **날것**이다. 점수·자수·작업 카드 번호는 물론,
운영자가 직접 입력한 수정 지시문 원문까지 그대로 들어 있다. 그걸 공개 페이지에 그대로
흘리면 세 가지가 한꺼번에 샌다.

  - 보안: 정비 백로그·이슈 번호·서버 보안 점검 과제("5xx·의심 IP 차단" 등)
  - 사생활: 운영자가 팀에 남긴 지시문 원문
  - 인상: 반려 사유·치명 결함 같은 내부 채점표

그래서 **허용 목록** 방식으로 간다. 공개는 '칼럼이 만들어지는 과정'만 보여 주고,
문장도 일정한 존댓말로 다시 쓴다. 새 action 이 생기면 기본은 비공개다 — 빠뜨려서
새는 것보다 빠뜨려서 안 보이는 편이 낫다.
"""
from __future__ import annotations

import re

# 공개하지 않는 action — 정비반·운영 지시·내부 실패 기록
PRIVATE_ACTIONS = {
    'admin_note',   # 운영자가 입력한 수정 지시 원문
    'reject', 'fail',
    'crew', 'triage', 'scan', 'patch', 'verify', 'pr', 'issue',
}

# 공개하는 action → (표시 라벨, 문장 틀). {title} 이 있으면 칼럼 제목을 넣는다.
PUBLIC_ACTIONS = {
    'meeting':  ('편집회의', '편집회의에서 의견을 냈습니다.'),
    'decision': ('안건 확정', '이번 편집 방향을 정했습니다{title}.'),
    'brief':    ('기획', '집필 의뢰서를 정리했습니다.'),
    'draft':    ('집필', '초안을 완성했습니다{title}.'),
    'check':    ('검증', '수치와 출처를 확인했습니다.'),
    'critique': ('평론', '독자 입장에서 읽어 보고 의견을 냈습니다{title}.'),
    'chart':    ('도표', '도표를 만들었습니다{title}.'),
    'qa':       ('편집 심사', '편집 심사를 마쳤습니다.'),
    'revise':   ('재집필', '지적사항을 반영해 다시 썼습니다{title}.'),
    'hold':     ('보완', '기준에 못 미쳐 보완 중입니다{title}.'),
    'publish':  ('발행', '칼럼을 발행했습니다{title}.'),
}

# 심사 결과는 결론만 — 점수와 반려 사유는 내부 정보다
QA_VERDICT = (
    ('보류', '편집 심사 결과 보완이 필요하다고 판단했습니다.'),
    ('수정 요청', '편집 심사에서 수정할 곳을 짚었습니다.'),
    ('발행', '편집 심사를 통과시켰습니다.'),
)

_PAREN_NUM = re.compile(r'\s*\([^)]*\d[^)]*\)')      # (3451자), (bar, 항목 3개), (major, 70점)
_TRAILING_ID = re.compile(r'#\d+')


def _title_of(log) -> str:
    """로그에 딸린 칼럼 제목. 없으면 빈 문자열."""
    draft = getattr(log, 'draft', None)
    if draft is not None and getattr(draft, 'subject', ''):
        return draft.subject
    # 'xxx: 제목 (1234자)' 형태에서 제목만 떼어 낸다
    text = _PAREN_NUM.sub('', log.text or '')
    if ':' in text:
        tail = text.split(':', 1)[1].strip()
        # '관리자 결정: 이번 주 HRD 칼럼 주제 → 제목' 처럼 화살표 뒤가 실제 제목이다
        if '→' in tail:
            tail = tail.split('→')[-1]
        tail = tail.split(' — ')[0].split(' · ')[0].strip()
        if 2 < len(tail) <= 80 and not _TRAILING_ID.search(tail):
            return tail
    return ''


def public_line(log) -> str:
    """공개용 한 문장. 내보내면 안 되는 로그는 None."""
    if log.action in PRIVATE_ACTIONS or log.action not in PUBLIC_ACTIONS:
        return None

    if log.action == 'qa':
        for needle, sentence in QA_VERDICT:
            if needle in (log.text or ''):
                return sentence
        return PUBLIC_ACTIONS['qa'][1]

    # 운영 안건(개발·보안)은 공개 대상이 아니다 — 칼럼·시리즈 결정만 내보낸다
    if log.action == 'decision' and not re.search(r'칼럼|시리즈|주제', log.text or ''):
        return None

    title = _title_of(log)
    label = f' — {title}' if title else ''
    return PUBLIC_ACTIONS[log.action][1].format(title=label)


def public_label(action: str) -> str:
    return PUBLIC_ACTIONS.get(action, ('활동', ''))[0]


def public_logs(qs, limit: int = 20) -> list:
    """(로그, 라벨, 문장) 목록. 비공개 항목은 빠지고, 같은 문장은 한 번만 남는다.

    문장은 미리 다듬어 둔 public_text 를 쓰고, 아직 없으면 틀 문장으로 대신한다.
    **여기서 API 를 부르지 않는다** — 연구실 페이지가 주기적으로 폴링하므로 조회할 때마다
    모델을 부르면 비용이 걷잡을 수 없다. 다듬기는 polish_logs 가 따로 한다.

    한 편을 여러 번 고쳐 쓰면 같은 문장이 연달아 쌓인다. 내부 기록으로는 의미가 있지만
    공개 피드에서는 읽는 맛만 떨어지므로 가장 최근 것 하나만 남긴다(최신순 전제).
    """
    out, seen = [], set()
    for log in qs:
        fallback = public_line(log)
        if not fallback:
            continue
        line = (log.public_text or '').strip() or fallback
        key = line
        if key in seen:
            continue
        seen.add(key)
        out.append((log, public_label(log.action), line))
        if len(out) >= limit:
            break
    return out


# ───────────────────────────── 말투 다듬기 (API 사용)
POLISH_PROMPT = (
    '연구팀의 공개 활동 피드에 올릴 문장을 다듬는 일입니다.\n'
    '아래는 각 연구원이 한 일을 기계가 정리한 딱딱한 문장입니다. 이것을 그 연구원이 '
    '편집회의 자리에서 동료에게 말하듯 자연스럽게 한 문장으로 바꿔 주세요.\n\n'
    '지켜야 할 것:\n'
    '- 한국어 존댓말. 한 문장, 45자 이내. 담백하게 — 감탄사·이모지·과장 금지\n'
    '- 사실을 바꾸지 마세요. **주어진 문장에 없는 내용을 지어내면 안 됩니다**\n'
    '- 칼럼 제목이 들어 있으면 그대로 두되, 길면 자연스럽게 줄여도 됩니다\n'
    '- 점수·글자 수·내부 절차 이름은 넣지 마세요\n'
    '- 같은 역할의 문장이 여러 개면 말투가 단조롭지 않게 조금씩 달리 씁니다\n\n'
    '[다듬을 문장]\n{items}\n\n'
    '출력 JSON: {{"lines": {{"<번호>": "다듬은 문장", ...}}}} — 번호는 그대로 돌려주세요.'
)


MEETING_PROMPT = (
    '연구팀 공개 페이지에 올릴 편집회의 안내문을 씁니다. 독자는 이 사이트의 방문자입니다.\n'
    '아래는 내부용 회의 결론과, 이번에 쓰기로 정한 칼럼 주제들입니다.\n\n'
    '[내부 회의 결론]\n{summary}\n\n[정해진 주제]\n{topics}\n\n'
    '지켜야 할 것:\n'
    '- **운영 지표(방문자 수·CTR·검색 순위)와 사이트 개선 과제는 쓰지 마세요.** 독자의 관심사가 아닙니다\n'
    '- 반려·보류된 안건, 그 사유, 내부 역할 이름(검증관·팀장 등)도 넣지 않습니다\n'
    '- 요약은 "이번 주에 어떤 이야기를 준비하고 있는지" 2~3문장. 한국어 존댓말, 담백하게\n'
    '- 주제별 소개는 **한 문장**으로, 그 글이 무엇을 다루는지만. 제목을 되풀이하지 마세요\n'
    '- **주제가 {count}개 주어졌습니다. notes 에 {count}개를 빠짐없이 넣으세요** — '
    '번호를 하나라도 빠뜨리면 그 글은 소개 없이 제목만 나갑니다\n'
    '- 사실을 지어내지 마세요. 주어진 내용 안에서만 씁니다\n\n'
    '출력 JSON: {{"summary": "2~3문장", "notes": {{"<주제 번호>": "한 문장 소개", ...}}}}'
)


def polish_meeting(meeting) -> dict:
    """회의 요약·주제 소개를 독자용으로 다듬는다. 반환 {'summary': str, 'notes': {decision_id: str}}.

    주 1회 회의 때 한 번만 부른다(호출 1회). 공개 페이지는 저장된 결과만 읽는다.
    모델에는 칼럼·시리즈 주제만 넘긴다 — 운영·보안 안건은 애초에 입력에 넣지 않는다.
    """
    from .models import Decision
    from .services import ask_agent_json

    topics = [d for d in meeting.decisions.all()
              if d.kind in (Decision.KIND_COLUMN, Decision.KIND_SERIES) and d.chosen_key]
    if not topics:
        return {'summary': '', 'notes': {}, 'expected': 0}

    lines = []
    for d in topics:
        c = d.chosen or {}
        lines.append(f"{d.id}. [{d.get_kind_display()}] {c.get('title', '')} — {c.get('detail', '')}")
    res = ask_agent_json('lead', MEETING_PROMPT.format(
        summary=meeting.summary or '(없음)', topics='\n'.join(lines), count=len(topics)),
        max_tokens=1500)

    notes = {}
    raw = res.get('notes') if isinstance(res.get('notes'), dict) else {}
    valid = {str(d.id) for d in topics}
    for key, value in raw.items():
        key = str(key).strip().rstrip('.')
        if key in valid and isinstance(value, str) and value.strip():
            notes[int(key)] = ' '.join(value.split())[:300]
    return {'summary': ' '.join(str(res.get('summary', '')).split())[:900],
            'notes': notes, 'expected': len(topics)}


def polish(rows: list) -> dict:
    """[(id, 연구원 이름, 역할, 기계 문장)] → {id: 다듬은 문장}.

    모델에는 **이미 걸러진 문장만** 넘긴다. 원문(WorkLog.text)을 주면 운영자 지시문이
    다시 새어 나올 수 있다 — 입력에 없으면 출력에도 없다는 것이 이 설계의 핵심이다.
    """
    if not rows:
        return {}
    from .services import ask_agent_json

    items = '\n'.join(f'{i}. [{name}·{title}] {line}' for i, name, title, line in rows)
    res = ask_agent_json('lead', POLISH_PROMPT.format(items=items), max_tokens=2000)
    lines = res.get('lines') if isinstance(res.get('lines'), dict) else {}

    out = {}
    by_id = {str(i): line for i, _n, _t, line in rows}
    for key, value in lines.items():
        key = str(key).strip().rstrip('.')
        if key not in by_id or not isinstance(value, str):
            continue
        value = ' '.join(value.split())[:280]
        if value:
            out[int(key)] = value
    return out
