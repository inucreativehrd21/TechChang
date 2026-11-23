"""원고 판별 지적 장부 — 초안부터 재작성까지 지적·해결·강점을 판을 넘어 이어 가요. (2026-11-23)

왜 필요한가:
- 재작성 단계는 직전 판의 심사만 봤어요(office_publish 의 prev_qa, RevisionRequests 의 before=현재 판).
  초안에서 잘 쓴 대목이 두 번째 재작성에서 사라지거나, 해결된 지적이 다른 말로 다시 요청돼 제자리걸음을 했어요.
- 관리 화면 체크 목록은 판마다 E1·S1 번호를 새로 매기고 모두 체크된 채 열렸어요. 이미 해결한 지적도 다시 보냈어요.

장부가 하는 일:
- 판(round)마다 심사·팩트체크 지적을 같은 항목끼리 이어 붙여요(필수 수정은 issue_id, 나머지는 문장 유사도).
- 다시 지적되지 않은 항목은 근거가 있을 때만 '해결'로 잠가요. 근거는 관리자 수정 검증의 인용, 편집장의
  해결 판정, 팩트체크 통과, 문제 주장 삭제예요. 근거 없이 사라진 지적은 '다시 지적되지 않음'으로만 둬요.
- 해결 근거 문장이 다음 판에서 사라지면 '회귀'로 되돌려요. 지켜야 할 강점(평론가·편집장이 인용한 대목)도
  판마다 남았는지 확인해요.

장부는 ColumnDraft 저장 신호로 갱신해요(제작·자동 재작성·관리자 재작성·연재 공통). 승인 지문(audit.snapshot)에는
들어가지 않으므로 장부 갱신이 승인을 무효화하지 않아요.
"""
from __future__ import annotations

import difflib
import json
import re
from copy import deepcopy

from .recorder import digest

LEDGER_VERSION = 1
MAX_ITEMS = 80
MAX_KEEPS = 12
SIMILAR = 0.62
# 판 비교에서 빼는 심사 필드 — 운영자 결정·수정 검증 보고·제목 점검은 원고 판이 바뀐 것이 아니에요.
_VOLATILE_QA = ('admin_revision', 'human_approval', 'title_review')
_PREFIX = re.compile(r'^\s*\((?:제안|재심 신규[^)]*)\)\s*')

STATE_LABEL = {'new': '새 지적', 'repeat': '다시 남음', 'regressed': '회귀', 'locked': '해결됨'}
EVIDENCE_LABEL = {'quote': '본문 인용 확인', 'review': '편집장 해결 판정', 'verified': '팩트체크 통과',
                  'removed': '문제 주장 삭제'}


# ───────────────────────────── 비교 도구
def norm(text) -> str:
    return re.sub(r'\s+', ' ', _PREFIX.sub('', str(text or ''))).strip()


def similar(a, b) -> bool:
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 12 and (a in b or b in a)):
        return True
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= SIMILAR


def quote_in(quote, haystack, threshold: float = 0.82) -> bool:
    """인용이 본문에 거의 그대로 있나 — 관리자 수정 검증과 같은 판정(조사·공백 차이 허용)."""
    from .revision_requests import RevisionRequests
    return RevisionRequests._quote_found(str(quote or ''), str(haystack or ''), threshold)


def fingerprint(subject, content, qa, check) -> str:
    qa = {k: v for k, v in (qa or {}).items() if k not in _VOLATILE_QA}
    check = {k: v for k, v in (check or {}).items() if k != 'first'}
    return digest(json.dumps({'s': subject or '', 'c': content or '', 'q': qa, 'k': check},
                             ensure_ascii=False, sort_keys=True, default=str))


def reviewed(qa) -> bool:
    return isinstance(qa, dict) and isinstance(qa.get('score'), (int, float))


def empty() -> dict:
    return {'version': LEDGER_VERSION, 'fp': '', 'rounds': [], 'items': [], 'keeps': [], 'current': [],
            'seen_revisions': []}


def round_label(n: int) -> str:
    return '초안' if n == 0 else f'재작성 {n}'


# ───────────────────────────── 판 넘기기
def _new_item(row: dict, r: int, n: int) -> dict:
    return {'key': f'L{n}', 'kind': row['kind'], 'text': row['text'], 'issue_id': row.get('issue_id', ''),
            'claim': row.get('claim', ''), 'first_round': r, 'last_round': r, 'raised': 1, 'status': 'open',
            'resolved_round': None, 'regressed_round': None, 'evidence': '', 'evidence_kind': '', 'reason': ''}


def _group(kind: str) -> str:
    # 편집장의 필수 수정과 제안은 재심에서 서로 오르내려요(demote_stale) — 같은 무리에서 이어 붙여요.
    return 'fact' if kind == 'fact' else 'editor'


def _match(items: list, row: dict, used: set):
    if row.get('issue_id'):
        for item in items:
            if id(item) not in used and item.get('issue_id') == row['issue_id']:
                return item
    best, best_ratio = None, 0.0
    for item in items:
        if id(item) in used or _group(item['kind']) != _group(row['kind']):
            continue
        texts = [item['text']] + ([item['claim']] if item.get('claim') and row.get('claim') else [])
        probe = [row['text']] + ([row['claim']] if row.get('claim') else [])
        if any(similar(a, b) for a in texts for b in probe):
            ratio = difflib.SequenceMatcher(None, norm(item['text']), norm(row['text']), autojunk=False).ratio()
            if best is None or ratio > best_ratio:
                best, best_ratio = item, ratio
    return best


def _admin_evidence(qa: dict, data: dict) -> list[tuple[str, str]]:
    """채택된 관리자 수정 — 요구가 '반영 확인'된 지적 문장과 그 인용."""
    report = qa.get('admin_revision') if isinstance(qa.get('admin_revision'), dict) else {}
    if report.get('status') != 'adopted' or str(report.get('run_id', '')) in data.get('seen_revisions', []):
        return []
    picked = {r.get('id'): r.get('text', '') for r in report.get('selected_feedback') or [] if isinstance(r, dict)}
    out = []
    for item in report.get('items') or []:
        if not isinstance(item, dict) or item.get('met') is not True:
            continue
        for ref in item.get('reference_ids') or []:
            if picked.get(ref):
                out.append((picked[ref], str(item.get('evidence') or '')))
    return out


def _evidence(item: dict, *, qa: dict, check: dict, text: str, admin: list, order: list):
    """다시 지적되지 않은 항목을 '해결'로 볼 근거 → (근거 문장, 종류) 또는 None."""
    for feedback, quote in admin:
        if similar(feedback, item['text']):
            return (quote, 'quote') if quote and quote_in(quote, text) else (quote, 'review')
    resolutions = qa.get('resolutions') if isinstance(qa.get('resolutions'), dict) else {}
    result = resolutions.get(item.get('issue_id') or '')
    if isinstance(result, dict) and result.get('resolved') is True:
        quote = str(result.get('evidence') or '').strip()
        return (quote, 'quote') if quote and quote_in(quote, text) else (quote, 'review')
    flags = qa.get('resolved') if isinstance(qa.get('resolved'), list) else []
    if item['key'] in order and order.index(item['key']) < len(flags) and flags[order.index(item['key'])] is True:
        return '', 'review'
    if item['kind'] == 'fact' and item.get('claim'):
        for c in check.get('claims') or []:
            if isinstance(c, dict) and c.get('status') == 'verified' and similar(c.get('claim', ''), item['claim']):
                return str(c.get('claim', ''))[:300], 'verified'
        # 검증관은 주장을 요약해 적어요 — 본문과 거의 겹치지 않을 때만 '삭제'로 봐요(되살아남 판정은 0.9로 엄격하게)
        if not quote_in(item['claim'], text, 0.6):
            return '해당 주장을 본문에서 뺐어요.', 'removed'
    return None


def _still_solved(item: dict, text: str) -> bool:
    """해결 근거가 이번 판에도 살아 있나. 인용 근거만 기계로 확인할 수 있어요."""
    if item['evidence_kind'] == 'quote':
        return quote_in(item['evidence'], text)
    if item['evidence_kind'] == 'removed':
        return not quote_in(item['claim'], text, 0.9)
    return True


def advance(data: dict | None, *, subject: str, content: str, qa: dict, check: dict, at: str = '') -> dict:
    """새로 심사받은 판을 장부에 더해요. 같은 판(지문 동일)이면 그대로 돌려줘요."""
    from .revision_requests import base_rows
    data = deepcopy(data) if data else empty()
    for key, value in empty().items():
        data.setdefault(key, deepcopy(value))
    qa, check = qa or {}, check or {}
    fp = fingerprint(subject, content, qa, check)
    if data.get('fp') == fp:
        return data
    r = len(data['rounds'])
    text = (subject or '') + '\n' + (content or '')
    items = data['items']
    rows = base_rows(qa, check)
    admin = _admin_evidence(qa, data)
    order = list(data.get('prev_must_fix') or [])
    used, current = set(), []
    for row in rows:
        item = _match(items, row, used)
        if item is None:
            item = _new_item(row, r, len(items) + 1)
            items.append(item)
            state = 'new'
        else:
            item.update(text=row['text'], kind=row['kind'], last_round=r, raised=item.get('raised', 0) + 1)
            if row.get('issue_id'):
                item['issue_id'] = row['issue_id']
            if item['status'] == 'resolved' and _still_solved(item, text):
                state = 'locked'                     # 근거가 살아 있는데 다시 지적됨 — 잠근 채 '다시 열기'로만
                item['reraised_round'] = r
            elif item['status'] == 'resolved':
                item.update(status='regressed', regressed_round=r, reason='해결했던 지적이 다시 나왔고 해결 근거도 사라졌어요.')
                state = 'regressed'
            elif item['status'] == 'regressed':
                state = 'regressed'
            else:
                item['status'] = 'open'
                state = 'repeat'
        used.add(id(item))
        current.append({'id': row['id'], 'key': item['key'], 'state': state})
    for item in items:
        if id(item) in used:
            continue
        if item['status'] in ('open', 'regressed'):
            found = _evidence(item, qa=qa, check=check, text=text, admin=admin, order=order)
            if found:
                item.update(status='resolved', resolved_round=r, evidence=found[0][:400], evidence_kind=found[1], reason='')
            elif item['status'] == 'open':
                item.update(status='cleared', resolved_round=r, evidence='', evidence_kind='')
        elif item['status'] == 'resolved' and not _still_solved(item, text):
            item.update(status='regressed', regressed_round=r, reason='해결 근거 문장이 이번 판에서 사라졌어요.')
    data['items'] = items[-MAX_ITEMS:]
    data['current'] = current
    data['prev_must_fix'] = [c['key'] for c, row in zip(current, rows) if row['kind'] == 'must_fix']
    _advance_keeps(data, qa, text, r)
    report = qa.get('admin_revision') if isinstance(qa.get('admin_revision'), dict) else {}
    if report.get('status') == 'adopted' and report.get('run_id'):
        data['seen_revisions'] = (data['seen_revisions'] + [str(report['run_id'])])[-20:]
    data['rounds'].append({'round': r, 'label': round_label(r), 'score': qa.get('score'),
                           'verdict': qa.get('verdict', ''), 'subject': (subject or '')[:200],
                           'content_hash': digest(content or ''), 'chars': len(content or ''), 'at': at,
                           'open': sum(i['status'] in ('open', 'regressed') for i in data['items'])})
    data['fp'] = fp
    return data


def _advance_keeps(data: dict, qa: dict, text: str, r: int) -> None:
    keeps = data['keeps']
    for keep in keeps:
        if quote_in(keep['quote'], text):
            if keep['status'] == 'lost':
                keep.update(status='kept', restored_round=r)
        elif keep['status'] == 'kept':
            keep.update(status='lost', lost_round=r)
    for passage in qa.get('keep_passages') or []:
        if not isinstance(passage, dict):
            continue
        quote = str(passage.get('quote') or '').strip()
        if len(quote) < 8 or not quote_in(quote, text) or any(similar(quote, k['quote']) for k in keeps):
            continue
        keeps.append({'key': f'K{len(keeps) + 1}', 'quote': quote[:240], 'why': str(passage.get('why') or '')[:240],
                      'source': str(passage.get('source') or '')[:20], 'first_round': r, 'status': 'kept',
                      'lost_round': None})
    # 먼저 꼽힌(초안에 가까운) 강점을 우선 남겨요 — 그게 재작성에서 사라지기 쉬운 대목이에요.
    data['keeps'] = keeps[:MAX_KEEPS]


# ───────────────────────────── 저장·조회
def ledger_for(draft) -> dict:
    if draft is None or not getattr(draft, 'pk', None):
        return {}
    from .models import RevisionLedger
    row = RevisionLedger.objects.filter(draft_id=draft.pk).values_list('data', flat=True).first()
    return row or {}


def observe(draft) -> dict | None:
    """원고 저장 직후 호출돼요. 새로 심사받은 판이면 장부를 한 판 넘겨요."""
    if draft is None or not draft.pk or not reviewed(draft.qa_report):
        return None
    from django.db import transaction
    from django.utils import timezone
    from .models import RevisionLedger
    with transaction.atomic():
        row, _ = RevisionLedger.objects.select_for_update().get_or_create(draft_id=draft.pk)
        before = row.data or {}
        data = advance(before, subject=draft.subject, content=draft.content, qa=draft.qa_report,
                       check=draft.check_report, at=timezone.localtime().strftime('%m-%d %H:%M'))
        if data != before:
            row.data = data
            row.save(update_fields=['data', 'updated_at'])
    return data


def is_current(ledger: dict, draft) -> bool:
    return bool(ledger) and ledger.get('fp') == fingerprint(draft.subject, draft.content, draft.qa_report,
                                                             draft.check_report)


# ───────────────────────────── 화면·재작성에 넘길 형태
def annotate(rows: list[dict], ledger: dict, *, current: bool) -> list[dict]:
    """관리 화면 체크 목록 — 지적마다 상태·기본 선택·잠금을 붙이고, 장부에만 있는 회귀·사라진 강점을 더해요.

    기본 선택: 필수 수정·팩트체크·회귀·사라진 강점. 제안은 기본으로 고르지 않아요(고칠 범위가 넓어지면 회귀가 늘어요).
    잠금: 근거가 확인된 '해결' 항목이 다시 지적되면 고를 수 없고, 운영자가 '다시 열기'를 눌러야 보낼 수 있어요."""
    states = {c['id']: c for c in (ledger.get('current') or [])} if current else {}
    items = {i['key']: i for i in ledger.get('items') or []}
    out = []
    for row in rows:
        mark = states.get(row['id'], {})
        item = items.get(mark.get('key'), {})
        state = mark.get('state', '')
        out.append({**row, 'state': state, 'state_label': STATE_LABEL.get(state, ''),
                    'ledger_key': mark.get('key', ''), 'since': item.get('first_round'),
                    'rounds_open': (item.get('last_round', 0) - item.get('first_round', 0) + 1) if item else 0,
                    'locked': state == 'locked',
                    'resolved_note': _resolved_note(item) if state == 'locked' else '',
                    'default': state != 'locked' and (row['kind'] in ('must_fix', 'fact') or state == 'regressed')})
    if not current:
        return out
    raised = {m.get('key') for m in states.values()}
    n = 0
    for item in ledger.get('items') or []:
        if item['status'] == 'regressed' and item['key'] not in raised:
            n += 1
            out.append({'id': f'G{n}', 'kind': 'regressed', 'label': '회귀', 'ledger_key': item['key'],
                        'text': f"{item['text']} — {item.get('reason') or '해결했던 지적이 되돌아갔어요.'}",
                        'state': 'regressed', 'state_label': STATE_LABEL['regressed'], 'locked': False,
                        'since': item.get('first_round'), 'rounds_open': 0, 'resolved_note': '', 'default': True})
    n = 0
    for keep in ledger.get('keeps') or []:
        if keep['status'] == 'lost':
            n += 1
            out.append({'id': f'K{n}', 'kind': 'keep', 'label': '사라진 강점', 'ledger_key': keep['key'],
                        'text': f"{round_label(keep['first_round'])}의 강점 「{keep['quote']}」"
                                + (f" ({keep['why']})" if keep.get('why') else '')
                                + ' — 되살리거나 같은 역할을 하는 문장을 둬요.',
                        'state': 'regressed', 'state_label': '사라짐', 'locked': False,
                        'since': keep['first_round'], 'rounds_open': 0, 'resolved_note': '', 'default': True})
    return out


def _resolved_note(item: dict) -> str:
    if not item:
        return ''
    label = EVIDENCE_LABEL.get(item.get('evidence_kind', ''), '해결')
    where = round_label(item['resolved_round']) if item.get('resolved_round') is not None else ''
    quote = f" 「{item['evidence'][:80]}」" if item.get('evidence') and item.get('evidence_kind') != 'removed' else ''
    return f'{where}에서 해결 · {label}{quote}'.strip()


def resolved_items(ledger: dict) -> list[dict]:
    rows = []
    for item in ledger.get('items') or []:
        if item['status'] in ('resolved', 'cleared'):
            rows.append({**item, 'round_label': round_label(item['resolved_round'] or 0),
                         'evidence_label': EVIDENCE_LABEL.get(item.get('evidence_kind', ''), '다시 지적되지 않음')})
    return rows


def guidance(ledger: dict, content: str = '') -> dict:
    """재작성 지시에 붙일 압축된 상태 — 원고 판 전체 대신 '지킬 것'만 넘겨요(맥락 끌림·토큰 절감)."""
    if not ledger:
        return {}
    preserve = [{'quote': k['quote'], 'why': k.get('why', ''), 'since': round_label(k['first_round'])}
                for k in ledger.get('keeps') or [] if k['status'] == 'kept' and (not content or quote_in(k['quote'], content))]
    solved = [{'feedback': i['text'][:240], 'evidence': i.get('evidence', '')[:200],
               'solved_in': round_label(i['resolved_round'] or 0)}
              for i in ledger.get('items') or [] if i['status'] == 'resolved'][-12:]
    out = {}
    if preserve:
        out['preserve_passages'] = preserve
    if solved:
        out['already_resolved'] = solved
    return out


def guidance_text(ledger: dict, content: str = '') -> str:
    g = guidance(ledger, content)
    lines = []
    if g.get('preserve_passages'):
        lines.append('[지켜야 할 강점 — 지적과 관계없으면 이 문장들을 그대로 두세요]')
        lines += [f"- 「{p['quote']}」 {p['why']}".rstrip() for p in g['preserve_passages']]
    if g.get('already_resolved'):
        lines.append('[이미 해결한 지적 — 되돌리지 마세요]')
        lines += [f"- {s['feedback']}" + (f" (근거: 「{s['evidence'][:80]}」)" if s['evidence'] else '')
                  for s in g['already_resolved']]
    return ('\n\n' + '\n'.join(lines)) if lines else ''


def lost_passages(ledger: dict, before: str, after: str, edits_find: list[str] = ()) -> list[str]:
    """재작성 후보에서 요청과 무관하게 사라진 강점·해결 근거 — 편집 대상(find)과 겹친 문장은 의도된 변경으로 봐요."""
    def touched(quote):
        return any(quote_in(quote, find, 0.6) or (len(find) >= 8 and quote_in(find, quote, 0.82))
                   for find in edits_find if find)
    lost = []
    for keep in ledger.get('keeps') or []:
        q = keep['quote']
        if keep['status'] == 'kept' and quote_in(q, before) and not quote_in(q, after) and not touched(q):
            lost.append(f'강점 「{q[:80]}」')
    for item in ledger.get('items') or []:
        q = item.get('evidence', '')
        if (item['status'] == 'resolved' and item.get('evidence_kind') == 'quote' and quote_in(q, before)
                and not quote_in(q, after) and not touched(q)):
            lost.append(f'해결 근거 「{q[:80]}」')
    return lost
