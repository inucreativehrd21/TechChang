"""칼럼 '메이킹 오브' — 발행된 칼럼이 어떤 과정을 거쳐 나왔는지 공개용 타임라인으로 만든다.

공개 범위 (2026-10-09 운영자 결정):
  - 발행된 칼럼에 한해 심사 점수 추이·판정·치명 결함·평론 인용·팩트체크 결과·루브릭까지 공개한다.
    "멀티 에이전트가 서로 검증하며 원고를 끌어올린다"는 과정 자체가 이 페이지의 내용이다.
  - 운영자 지시문 원문, 보류·실패 원고, 정비·운영 기록은 계속 비공개 (publiclog 와 같은 이유).
    운영자 개입은 "검토하고 수정을 지시했다"는 사실만 남긴다.

원천은 WorkLog(한 줄 요약)와 ColumnDraft 의 최종 보고서다. 로그 문장 형식은
office_publish 의 rec() 호출들이 만든다 — 형식이 바뀌면 여기 파서도 같이 본다.
여기서 모델을 부르지 않는다(추가 비용 0).
"""
from __future__ import annotations

import re

from office.agents import AGENTS

# action → (단계 이름, 아이콘 키). 여기에 없는 action 은 보이지 않는다(허용 목록).
STAGES = {
    'meeting':    ('편집회의', 'meeting'),
    'brief':      ('기획', 'brief'),
    'blueprint':  ('설계도', 'brief'),
    'draft':      ('집필', 'draft'),
    'precheck':   ('자동 점검', 'precheck'),
    'check':      ('팩트체크', 'check'),
    'revise':     ('재집필', 'revise'),
    'critique':   ('평론', 'critique'),
    'chart':      ('도표', 'chart'),
    'qa':         ('편집 심사', 'qa'),
    'hold':       ('발행 보류', 'hold'),
    'admin_note': ('운영자 검토', 'human'),
    'headline':   ('제목 다듬기', 'qa'),
    'publish':    ('발행', 'publish'),
}

FATAL_LABELS = {
    'unverified_data': '확인되지 않은 수치',
    'duplicate': '기존 칼럼과 소재 중복',
    'too_short': '분량 미달',
    'no_evidence': '비교 가능한 근거 부족',
    'structure_broken': '필수 섹션 누락',
    'overclaim': '근거 없는 단정',
    'visual_broken': '도표가 아무것도 말해 주지 못함',
    'style_broken': '문체 이탈',
    'unreadable': '독자가 읽을 이유가 없음',
}

VERDICTS = {  # 편집 심사 판정
    'accept': ('통과', 'pass'),
    'minor': ('수정 요청', 'warn'),
    'major': ('보류', 'fail'),
}
CRITIC_VERDICTS = {
    '추천': ('추천', 'pass'), 'recommend': ('추천', 'pass'),
    '수정 후 재검토': ('수정 후 재검토', 'warn'), 'revise': ('수정 후 재검토', 'warn'),
    '반대': ('반대', 'fail'), 'reject': ('반대', 'fail'),
}
CHECK_WORDS = {'pass': '통과', 'revise': '수정 필요', 'fail': '실패', 'reject': '반려'}
CLAIM_STATUS = {
    'verified': ('확인됨', 'pass'), 'unverifiable': ('확인 불가', 'warn'),
    'wrong': ('사실과 다름', 'fail'), 'outdated': ('시점 지남', 'warn'),
}

_ID = re.compile(r'\s*\(id=\d+[^)]*\)|#\d+')
_CHARS = re.compile(r'\((\d[\d,]*)자\)')


def _agent(key: str) -> dict:
    if key == 'operator':
        return {'key': 'operator', 'name': '운영자', 'title': '사람'}
    a = AGENTS.get(key, {})
    return {'key': key, 'name': a.get('name', key), 'title': a.get('title', '')}


def _parse_qa(text: str) -> dict:
    score = None
    m = re.search(r'(\d+)\s*/\s*100', text)
    if m:
        score = int(m.group(1))
    else:
        m = re.search(r'(\d+)\s*/\s*10\b', text)  # 초기(9월) 10점 척도
        if m:
            score = int(m.group(1)) * 10
    if '→ 발행' in text:
        verdict = 'accept'
    elif '수정 요청' in text:
        verdict = 'minor'
    else:
        verdict = 'major'
    fatal = []
    m = re.search(r'치명결함 ([a-z_,]+)', text)
    if m:
        fatal = [FATAL_LABELS.get(f, f) for f in m.group(1).split(',') if f]
    note = ''
    if '→' in text:
        tail = text.split('→', 1)[1]
        note = tail.split(':', 1)[1].strip() if ':' in tail else ''
    label, tone = VERDICTS[verdict]
    return {'score': score, 'verdict': verdict, 'verdict_label': label, 'tone': tone,
            'fatal': fatal, 'note': note, 'retry': text.startswith('재심')}


def _parse_critique(text: str) -> dict:
    """'평론 {판정} · 지적 N건 — 「인용[:32]」 사유[:60]: 총평' (office_publish._critique_line).
    사유에도 ':' 가 들어갈 수 있어, 인용 뒤 60자 안에서 마지막 ': ' 를 경계로 본다."""
    retry = text.startswith('재검토 ')
    body = text[4:] if retry else text
    m = re.match(r'평론 (수정 후 재검토|\S+)(?: · 지적 (\d+)건)?', body)
    if not m:
        return {'verdict_label': '', 'tone': 'neutral', 'issues': 0, 'quote': '', 'why': '', 'reason': body,
                'retry': retry}
    label, tone = CRITIC_VERDICTS.get(m.group(1), (m.group(1), 'neutral'))
    rest = body[m.end():]
    quote = why = ''
    q = re.match(r' — 「(.*?)」 ', rest, re.S)
    if q:
        quote = q.group(1).strip()
        tail = rest[q.end():]
        cuts = [i for i in range(len(tail)) if tail.startswith(': ', i) and i <= 61]
        cut = cuts[-1] if cuts else tail.find(': ')
        why, reason = (tail[:cut], tail[cut + 2:]) if cut >= 0 else (tail, '')
    else:
        reason = rest.split(': ', 1)[1] if ': ' in rest else rest.lstrip(': ')
    return {'verdict_label': label, 'tone': tone, 'issues': int(m.group(2) or 0),
            'quote': quote, 'why': why.strip(), 'reason': reason.strip(), 'retry': retry}


def _check_summary(text: str) -> tuple[str, str]:
    """('통과'|'수정 필요'…, 문장)"""
    m = re.search(r'\b(pass|revise|fail|reject)\b', text)
    word = CHECK_WORDS.get(m.group(1), '') if m else ''
    tone = 'pass' if m and m.group(1) == 'pass' else 'warn'
    sentence = re.sub(r'\b(pass|revise|fail|reject)\b', lambda x: CHECK_WORDS[x.group(1)], text)
    return word, tone, sentence


def _event(log) -> dict | None:
    action = log.action
    if action not in STAGES:
        return None
    stage, icon = STAGES[action]
    text = _ID.sub('', (log.text or '').strip())
    clipped = len(log.text or '') >= 299  # WorkLog.text 300자 상한에서 잘린 문장
    agent = 'operator' if action == 'admin_note' else log.agent
    ev = {'action': action, 'stage': stage, 'icon': icon, 'at': log.created_at, 'agent': _agent(agent),
          'summary': '', 'detail': '', 'badge': '', 'tone': 'neutral'}

    if action == 'admin_note':
        # 지시문 원문은 비공개 — 사람이 개입했다는 사실만
        ev['summary'] = '원고를 직접 읽고 수정 방향을 지시했습니다.'
    elif action == 'brief':
        if log.agent == 'charter':
            m = re.search(r'(\d+)개', text)
            ev['summary'] = f"이 주제에 필요한 지표 {m.group(1) if m else '몇'}개를 먼저 제시했습니다."
        else:
            ev['summary'] = '집필 의뢰서를 썼습니다.'
            ev['detail'] = text.split(':', 1)[1].strip() if ':' in text else text
    elif action == 'blueprint':
        # '설계도: 주장 12개 중 10개 원문 확인' — 본문 쓰기 전에 검증관이 근거부터 확인했다는 기록
        ev['summary'] = '본문을 쓰기 전에 설계도를 내고, 검증관이 주장의 근거를 먼저 확인했습니다.'
        ev['detail'] = text.split(':', 1)[1].strip() if ':' in text else text
    elif action == 'draft':
        title = text.split(':', 1)[1] if ':' in text else ''
        title = _CHARS.sub('', title).strip()
        m = _CHARS.search(text)
        ev['summary'] = '초안을 완성했습니다' + (f' ({m.group(1)}자).' if m else '.')
        ev['detail'] = f'가제: {title}' if title else ''
        if title:
            ev['title'] = title
    elif action == 'precheck':
        ev['summary'] = text.replace('초안 ', '')
        ev['tone'] = 'pass' if '통과' in text else 'warn'
        ev['badge'] = '통과' if '통과' in text else '지적'
    elif action == 'check':
        word, tone, sentence = _check_summary(text)
        ev['summary'], ev['badge'], ev['tone'] = sentence, word, tone
    elif action == 'revise':
        # '팩트체크 4건 반영해 재작성 (3445자)' · '운영자 지시 반영해 재작성: 제목 (5218자)'
        ev['tone'] = 'fail' if '실패' in text else 'neutral'
        if '재작성' in text and '실패' not in text:
            why, _, rest = text.partition('재작성')
            why = why.strip().replace('지시 반영해', '지시를 반영해')
            if why.endswith('반영'):
                why += '해'
            m = _CHARS.search(rest)
            ev['summary'] = f'{why} 다시 썼습니다' + (f' ({m.group(1)}자).' if m else '.')
            title = _CHARS.sub('', rest.lstrip(': ')).strip()
            if title:
                ev['title'] = title
        else:
            ev['summary'] = text
    elif action == 'critique':
        cr = _parse_critique(text)
        ev['critique'] = cr
        ev['badge'], ev['tone'] = cr['verdict_label'], cr['tone']
        ev['summary'] = ('다시 읽고 ' if cr['retry'] else '') + (
            f"지적 {cr['issues']}건을 남겼습니다." if cr['issues'] else '독자 입장에서 읽고 판단했습니다.')
        ev['detail'] = cr['reason']
    elif action == 'chart':
        ev['summary'] = text.replace('자동점검 치명', '자동 점검 치명 결함')
        ev['tone'] = 'warn' if ('문제' in text or '치명' in text) else 'neutral'
    elif action == 'qa':
        qa = _parse_qa(text)
        ev['qa'] = qa
        ev['badge'] = f"{qa['score']}점 · {qa['verdict_label']}" if qa['score'] is not None else qa['verdict_label']
        ev['tone'] = qa['tone']
        ev['summary'] = ('재심' if qa['retry'] else '심사') + f" 결과 {qa['verdict_label']}."
        ev['detail'] = qa['note']
    elif action == 'hold':
        ev['summary'] = '기준에 못 미쳐 자동 발행을 멈추고 운영자 검토로 넘겼습니다.'
        ev['tone'] = 'fail'
    elif action == 'headline':
        m = re.match(r'제목 다듬기: 「(.+?)」 → 「(.+?)」', text)
        ev['summary'] = '발행 직전 제목을 다듬었습니다.'
        ev['detail'] = f'「{m.group(1)}」 → 「{m.group(2)}」' if m else ''
    elif action == 'publish':
        m = re.search(r'(\d+)점', log.text or '')
        ev['summary'] = '칼럼을 발행했습니다.'
        ev['badge'] = f'{m.group(1)}점' if m else ''
        ev['tone'] = 'pass'
    if clipped and ev['detail']:
        ev['detail'] = ev['detail'].rstrip() + '…'
    elif clipped and ev.get('critique'):
        ev['critique']['reason'] = ev['critique']['reason'].rstrip() + '…'
    return ev


def build_making(draft) -> dict | None:
    """발행된 ColumnDraft → 공개용 메이킹 데이터. 보여 줄 게 없으면 None."""
    if draft is None or draft.status != draft.STATUS_PUBLISHED or not draft.question_id:
        return None

    events = []
    dec = draft.decision
    if dec is not None and dec.kind in ('column', 'series') and dec.chosen:
        opt = dec.chosen
        proposer = next((k for k, a in AGENTS.items() if a['name'] == opt.get('proposed_by')), 'lead')
        events.append({
            'action': 'meeting', 'stage': '편집회의', 'icon': 'meeting', 'at': dec.meeting.held_at,
            'agent': _agent(proposer), 'tone': 'neutral', 'badge': '채택',
            'summary': f'{dec.meeting.week_start.month}월 {dec.meeting.week_start.day}일 주차 편집회의에서 이 주제를 제안했고, 운영자가 채택했습니다.',
            'detail': opt.get('title', ''),
        })
    last_title = ''
    for log in draft.logs.order_by('created_at', 'id'):
        ev = _event(log)
        if not ev:
            continue
        # 제목은 바뀐 순간에만 보여 준다 — 제목이 다듬어지는 과정 자체가 볼거리다
        title = ev.pop('title', '')
        if title and ev['action'] == 'revise' and last_title and title != last_title:
            ev['detail'] = f'제목을 바꿨습니다 → 「{title}」'
        last_title = title or last_title
        events.append(ev)
    if not events:
        return None

    scores = [e['qa']['score'] for e in events if e.get('qa') and e['qa']['score'] is not None]
    final = draft.qa_report or {}
    if final.get('score') is not None:
        final_score = draft.qa_score
        if not scores or scores[-1] != final_score:
            scores.append(final_score)
    else:
        final_score = scores[-1] if scores else None

    agents = []
    for e in events:
        if e['agent']['key'] not in [a['key'] for a in agents]:
            agents.append(e['agent'])

    started, finished = events[0]['at'], events[-1]['at']
    return {
        'question_id': draft.question_id,
        'subject': draft.question.subject if draft.question else draft.subject,
        'events': events,
        'rounds': _rounds(events),
        'score_trail': scores,
        'score_svg': _sparkline(scores),
        'score_chart': _sparkline(scores, w=640, h=170, pad=22),
        'final_score': final_score,
        'reviews': sum(1 for e in events if e['action'] == 'qa'),
        'rewrites': sum(1 for e in events if e['action'] == 'revise'),
        'human_steps': sum(1 for e in events if e['action'] == 'admin_note'),
        'critiques': sum(1 for e in events if e['action'] == 'critique'),
        'agents': [a for a in agents if a['key'] != 'operator'],
        'had_human': any(a['key'] == 'operator' for a in agents),
        'started': started,
        'finished': finished,
        'duration': _duration(started, finished),
        'rubric': _rubric(final),
        'strengths': final.get('strengths', ''),
        # 남은 개선 제안은 접어서 핵심 한 문장만 — 전문(최대 5개)이 페이지의 큰 비중을 차지했다
        'suggestions': [_gist(s) for s in (final.get('issues') or []) if isinstance(s, str)][:3],
        'suggestions_total': len([s for s in (final.get('issues') or []) if isinstance(s, str)]),
        'claims': _claims(draft.check_report or {}),
    }


def _rounds(events: list) -> list:
    """편집 심사 한 번 = 원고 한 회차. 심사 뒤의 '발행 보류'는 그 회차에 붙이고,
    다음 행동(운영자 검토·재집필)부터 새 회차로 연다."""
    rounds, cur = [], []
    closed = False
    published = False
    for e in events:
        # 심사 뒤의 보류·발행은 그 회차의 결말이고, 발행 뒤 손질도 마지막 회차에 남긴다
        if closed and not published and e['action'] not in ('hold', 'publish'):
            rounds.append(cur)
            cur, closed = [], False
        cur.append(e)
        if e['action'] == 'qa':
            closed = True
        elif e['action'] == 'publish':
            published = True
    if cur:
        rounds.append(cur)

    out = []
    for i, evs in enumerate(rounds, 1):
        qa = next((e['qa'] for e in reversed(evs) if e.get('qa')), None)
        published = any(e['action'] == 'publish' for e in evs)
        out.append({
            'n': i, 'events': evs, 'qa': qa, 'published': published,
            'human': any(e['action'] == 'admin_note' for e in evs),
            'title': '기획과 초고' if i == 1 else f'{i}차 원고',
            # 첫 회차와 마지막 회차만 펼쳐 둔다 — 길게 이어진 중간 공방은 접어서
            'open': i == 1 or i == len(rounds),
        })
    return out


def _gist(text: str, limit: int = 90) -> str:
    """제안 하나를 핵심 한 문장으로 — 첫 문장(마침표·대시 앞)만, 길면 자른다."""
    t = re.sub(r'^\s*[\[「][^\]」]{1,30}[\]」]\s*:?\s*', '', text.strip())   # 앞머리 [섹션명] 꼬리표
    t = re.split(r'(?<=[.다요])\s|\s—\s', t, maxsplit=1)[0].strip()
    return t if len(t) <= limit else t[:limit].rstrip() + '…'


def _rubric(qa: dict) -> list:
    from office.pipeline import RUBRIC
    if qa.get('rubric') == 'series':           # 연재 회차는 연재용 기준표로 심사했다
        from office.series_pipeline import SERIES_RUBRIC as RUBRIC
    scores = qa.get('scores') or {}
    rows = []
    for key, (weight, desc) in RUBRIC.items():
        v = scores.get(key)
        if v is None:
            continue
        rows.append({'label': desc.split(' — ')[0], 'score': v, 'pct': int(v) * 20, 'weight': int(weight * 100)})
    return rows


def _claims(check: dict) -> list:
    out = []
    for c in check.get('claims') or []:
        if not isinstance(c, dict) or not c.get('claim'):
            continue
        label, tone = CLAIM_STATUS.get(c.get('status'), (c.get('status', ''), 'neutral'))
        url = next(iter(re.findall(r'https?://[^\s)\]」>,]+', str(c.get('note') or ''))), '')
        out.append({'claim': c['claim'], 'status': label, 'tone': tone, 'url': url})
    return out[:12]


def _duration(a, b) -> str:
    secs = max(0, int((b - a).total_seconds()))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f'{days}일 {hours}시간'
    if hours:
        return f'{hours}시간 {mins}분'
    return f'{max(mins, 1)}분'


def _sparkline(scores: list, *, w: int = 240, h: int = 64, pad: int = 8) -> dict | None:
    """점수 추이 선 그래프 좌표 (viewBox 0 0 W H). 2개 미만이면 그리지 않는다."""
    if len(scores) < 2:
        return None
    # 점수가 있는 구간만 쓴다 (발행 기준 80점은 항상 보이게)
    hi = 100
    lo = max(0, (min(min(scores), 80) - 10) // 10 * 10)
    step = (w - pad * 2) / (len(scores) - 1)
    pts = []
    for i, s in enumerate(scores):
        x = pad + i * step
        y = pad + (hi - max(lo, min(hi, s))) / (hi - lo) * (h - pad * 2)
        pts.append({'x': round(x, 1), 'y': round(y, 1), 'score': s})
    pass_y = round(pad + (hi - 80) / (hi - lo) * (h - pad * 2), 1)  # 발행 기준선 80점
    return {'w': w, 'h': h, 'points': pts, 'path': ' '.join(f"{p['x']},{p['y']}" for p in pts), 'pass_y': pass_y}
