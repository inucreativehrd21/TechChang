"""연구실 위클리 — 매주 금요일, 지난 한 주(금~목)에 연구실이 낸 칼럼을 카드뉴스 + 웹 페이지로 추천한다.

리포트가 아니라 큐레이션: 표지(훅) → 회의실에서(이 주제를 왜 골랐나 — 편집회의에서 오간 말) → 추천 칼럼 카드
(왜 지금 읽을 만한지·무엇을 얻는지·누구에게 좋은지) → 다음 주 예고. 제작 과정의 수정 횟수·심사 점수는 싣지 않는다.
흐름: collect(사실 모으기) → curate(큐레이터 은혜가 문구 쓰기) → render(카드 PNG) → 저장(office.models.Newsletter)
- 사실은 DB 에서만 모은다(발행 기록·칼럼 지도 요약/키워드·본문 소제목·편집회의 회의록). 큐레이터는 문구만 쓴다.
- 문구의 숫자는 모은 사실에 있는 값만(office.evidence 수치 대조). 길이·숫자가 어긋나면 한 번 고치게 하고,
  그래도 안 되면 사실로 만든 기본 문구로 대신한다 — 모델 호출이 실패해도 위클리는 나간다.
- 카드는 templates/newsletter/cards.html(디자인 원칙 DESIGN.md 「관측 원장」)을 Playwright 로 찍는다.
  장 수는 추천 글 수에 따라 4~6장. 글자 칸이 넘치면(.fit) 큐레이터에게 줄이게 한다.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

AGENT_ORDER = ['lead', 'editor', 'hrd', 'data', 'coding', 'checker', 'critic', 'charter']
CURATOR = 'lead'
SPRITE_FRONT = 18           # 16×32 프레임 24개 중 정면을 보는 첫 프레임
CAT_LABEL = {'hrd': 'HRD', 'data': '데이터분석', 'coding': '프로그래밍'}
LIMITS = {'theme': 20, 'intro': 90, 'chat': 46, 'hook': 30, 'why_now': 70, 'point': 32, 'for_whom': 28}
WEEKDAY = '월화수목금토일'


# ───────────────────────────── 기간·그림
def window(run_date: date) -> tuple[date, date]:
    """금요일에 돌면 지난 금요일~어제(목요일) 7일."""
    end = run_date - timedelta(days=1)
    return end - timedelta(days=6), end


def week_code(d: date) -> tuple[str, str]:
    y, w, _ = d.isocalendar()
    return f'{y} W{w:02d}', f'{y}-w{w:02d}'


def sprite(key: str) -> str:
    """연구실 픽셀 인물(정면)을 data URI 로. 파일이 없으면 빈 문자열."""
    from PIL import Image
    path = os.path.join(settings.MEDIA_ROOT, 'lab', 'chars', f'{key}_idle.png')
    try:
        im = Image.open(path).crop((SPRITE_FRONT * 16, 0, SPRITE_FRONT * 16 + 16, 32))
    except (OSError, ValueError):
        return ''
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def _span(start: date, end: date):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz),
            timezone.make_aware(datetime.combine(end, time.max), tz))


# ───────────────────────────── 사실 모으기
def _author_key(q) -> str:
    if q.series_id:
        return 'coding'
    from office import digest as D
    return {'hrd': 'hrd', 'data': 'data', 'coding': 'coding'}.get(D.category_key(q), 'editor')


def _published(lo, hi) -> list[dict]:
    from community.models import Question
    from office.models import ColumnDigest, WorkLog
    from office.publiclog import is_remake, post_id
    seen, out = set(), []
    for log in WorkLog.objects.filter(action='publish', created_at__range=(lo, hi)).order_by('-created_at'):
        pid = post_id(log)
        if not pid or pid in seen:
            continue
        q = Question.objects.filter(pk=pid, is_deleted=False).select_related('category', 'series').first()
        if q is None:
            continue
        seen.add(pid)
        m = re.search(r'(\d+)점', log.text or '')
        dg = ColumnDigest.objects.filter(question=q).first()
        cat = (f'연재 · {q.episode_number}편' if q.series_id else (q.category.name if q.category else '칼럼'))
        out.append({'id': q.pk, 'title': q.subject, 'cat': ('갱신 · ' if is_remake(log) else '') + cat,
                    'remake': is_remake(log), 'score': int(m.group(1)) if m else None,
                    'author_key': _author_key(q), 'date': timezone.localtime(log.created_at).strftime('%m.%d'),
                    'summary': dg.summary if dg else q.seo_description, 'url': f'/{q.pk}/'})
    out.sort(key=lambda p: (p['remake'], p['date']))      # 새 발행이 먼저
    return out


def _next_week(run_date: date) -> list[dict]:
    """다음 한 주 일정 — 토 프로그래밍, 일 편집회의, 월 연재(격주), 화 HRD, 목 데이터."""
    from community.models import ColumnSeries
    from community.series_catalog import SERIES
    from office.models import ColumnDraft, Decision
    from office.series_pipeline import outline_of

    def chosen(topic):
        d = (Decision.objects.filter(topic=topic, consumed_at__isnull=True).exclude(chosen_key='')
             .order_by('-chosen_at').first())
        return (d.chosen or {}).get('title', '') if d else ''

    def label(d):
        return f"{d:%m.%d}({WEEKDAY[d.weekday()]})"

    days = {wd: run_date + timedelta(days=(wd - run_date.weekday()) % 7 or 7) for wd in range(7)}
    rows = []
    for wd, topic in ((5, 'coding'), (6, None), (0, 'series'), (1, 'hrd'), (3, 'data')):
        d = days[wd]
        if topic is None:
            rows.append({'date': d, 'day': WEEKDAY[wd], 'what': '편집회의', 'note': f'{label(d)} · 다음 주 주제를 정합니다',
                         'agent': 'lead'})
        elif topic == 'series':
            key = 'django' if d.isocalendar()[1] % 2 == 1 else 'agent'
            s = ColumnSeries.objects.filter(slug=SERIES[key]['slug']).first()
            no = s.next_episode_number if s else 0
            ol = outline_of(key, no) or {}
            rows.append({'date': d, 'day': WEEKDAY[wd], 'what': SERIES[key]['title'],
                         'note': f"{label(d)} · 연재 {no}편" + (f" — {ol.get('title')}" if ol.get('title') else ''),
                         'agent': 'coding'})
        else:
            ready = (ColumnDraft.objects.filter(topic=topic, series_key='', publish_at__date=d,
                                                status__in=(ColumnDraft.STATUS_READY, ColumnDraft.STATUS_PUBLISHED))
                     .exclude(subject='').order_by('-created_at').first())
            pick = ready.subject if ready else chosen(topic)      # 이미 준비된 원고면 실제 제목
            rows.append({'date': d, 'day': WEEKDAY[wd], 'what': f'{CAT_LABEL[topic]} 칼럼',
                         'note': f'{label(d)} · ' + (pick or '편집회의가 정한 주제로'), 'agent': topic})
    rows.sort(key=lambda r: r['date'])
    for r in rows:
        r['date'] = r['date'].isoformat()
    return rows


# ───────────────────────────── 추천 글과 그 주제를 고른 회의
# 위클리는 독자에게 칼럼을 추천하는 큐레이션이다. 제작 과정의 수정 횟수·심사 점수·실패담은 싣지 않는다.
# 재료: 추천 글의 요약·키워드·소제목(칼럼 지도) + 그 주제를 정한 편집회의 발언(팀장 브리핑, 제안자의 이유, 반응).
# 운영자 지시문과 운영·보안 안건은 칼럼 안건이 아니므로 애초에 닿지 않는다.
FOR_WHOM = {'HRD': 'HRD·교육 담당자', '데이터분석': '데이터로 일하는 HR 실무자', '프로그래밍': '개발이 궁금한 비전공자'}

# 공개 문구 가드레일(2026-10-16 No.2 '방문자 3301명, 검색 클릭 10회, 추천 0' 이 회의실 카드에 그대로 나갔다).
# 독자에게 사이트 운영 지표를 말하면 '아무도 안 보는 사이트'로 읽힌다 — 회의 재료에서 빼고, 문구에서도 막는다.
SITE_METRIC = re.compile(r'방문자?|클릭|노출|조회\s*수|추천(은|이|수)?\s*(전부\s*)?0|평균\s*순위|검색\s*순위|CTR|트래픽|유입|'
                         r'\d[\d,]*\s*(명|회)\s*(방문|조회)')
# '우리 사이트에 그 주제 글이 없었다'는 운영 사정이지 독자가 읽을 이유가 아니다
CATALOG_GAP = re.compile(r'(같은|겹치는|비슷한)\s*(주제|칼럼|글)[^.]{0,6}없|최근\s*[^.]{0,12}칼럼\s*(중|에)|발행\s*목록|'
                         r'우리\s*(글|칼럼|사이트)|칼럼\s*중\s*같은')
CHAT_RANGE = (3, 4)             # 회의실 카드 말풍선 — 5개면 '그래서 고른 칼럼' 상자와 부딪혔다(No.2)


def _scrub(text: str) -> str:
    """회의 발언에서 사이트 지표·카탈로그 사정이 담긴 문장을 뺀다(큐레이터에게 애초에 주지 않는다)."""
    keep = [s for s in _sentences(text) if not SITE_METRIC.search(s) and not CATALOG_GAP.search(s)]
    return ' '.join(keep)


def _clip(s: str, n: int) -> str:
    s = re.sub(r'\s+', ' ', (s or '')).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def _around(text: str, needle: str, before: int = 160, after: int = 320) -> str:
    """회의 발언에서 그 제안이 나오는 부분만."""
    text = re.sub(r'\s+', ' ', text or '').strip()
    i = text.find(needle) if needle else -1
    if i < 0:
        return _clip(text, before + after)
    lo = max(0, i - before)
    return ('…' if lo else '') + _clip(text[lo:i + after], before + after)


def _sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r'(?<=[.!?다요])\s+', re.sub(r'\s+', ' ', s or '').strip()) if x.strip()]


def _origin(draft) -> dict:
    from office.agents import AGENTS
    d = draft.decision if draft is not None else None
    if d is None or d.meeting_id is None:
        series = bool(draft and draft.series_key)
        return {'decision_id': None, 'from': '연재 기획서' if series else '편집장 의뢰',
                'proposer': 'coding' if series else 'lead', 'pitch': _clip(getattr(draft, 'brief', ''), 80),
                'why': _clip(getattr(draft, 'brief', ''), 200)}
    opt = next((o for o in (d.options or []) if o.get('key') == d.chosen_key), {}) or {}
    name = opt.get('proposed_by', '')
    key = next((k for k, a in AGENTS.items() if a['name'] == name), 'lead')
    head = (opt.get('title') or '')[:10]
    turns = [t for t in (d.meeting.transcript or []) if isinstance(t, dict) and t.get('agent') == key]
    said = next((t['text'] for t in turns if head and head in (t.get('text') or '')), turns[0]['text'] if turns else '')
    return {'decision_id': d.pk, 'from': f"{timezone.localtime(d.meeting.held_at):%m.%d} 편집회의 · {name or AGENTS[key]['name']} 제안",
            'proposer': key, 'pitch': _clip(opt.get('title'), 80),
            'why': _around(said, head) if said else _clip(opt.get('detail'), 300)}


def _headings(content: str) -> list[str]:
    hs = [h.strip(' #') for h in re.findall(r'^#{2,3}\s+(.+)$', content or '', flags=re.M)]
    return [h for h in hs if h and not re.search(r'참고|출처|맺음|References', h)][:6]


def _picks(published) -> list[dict]:
    """추천할 글 — 이번 주 새 글(최대 3). 새 글이 없으면 다시 다듬은 글 중 점수 높은 2편."""
    from community.models import Question
    from office.models import ColumnDigest, ColumnDraft
    pool = [p for p in published if not p['remake']][:3]
    if not pool:
        pool = sorted([p for p in published if p['remake']], key=lambda p: -(p['score'] or 0))[:2]
    out = []
    for p in pool:
        q = Question.objects.filter(pk=p['id']).first()
        dg = ColumnDigest.objects.filter(question_id=p['id']).first()
        if p['remake']:
            dr = (ColumnDraft.objects.filter(target_question_id=p['id'], status=ColumnDraft.STATUS_PUBLISHED)
                  .order_by('-created_at').first())
        else:
            dr = ColumnDraft.objects.filter(question_id=p['id']).first()
        out.append({'id': p['id'], 'title': p['title'], 'cat': p['cat'], 'author_key': p['author_key'], 'date': p['date'],
                    'url': p['url'], 'summary': _clip(p['summary'], 400), 'keywords': (dg.keywords if dg else [])[:6],
                    'headings': _headings(q.content if q else ''), 'origin': _origin(dr)})
    return out


def _meeting_talk(picks) -> dict:
    """추천 글들의 주제를 정한 편집회의 — 팀장의 지표 브리핑, 제안자의 이유, 다른 연구원의 반응(회의 순서대로)."""
    from collections import Counter

    from office.models import Decision
    ids = [p['origin']['decision_id'] for p in picks if p['origin'].get('decision_id')]
    if not ids:
        return {}
    meeting = Counter(d.meeting for d in Decision.objects.filter(pk__in=ids).select_related('meeting')).most_common(1)[0][0]
    turns = [t for t in (meeting.transcript or []) if isinstance(t, dict) and t.get('text') and t.get('agent')]
    heads = {(p['origin']['pitch'] or '')[:8]: p['origin']['proposer'] for p in picks if p['origin'].get('decision_id')}
    picked = []
    for t in turns:
        hit = next((h for h in heads if h and h in t['text']), None)
        if hit:     # 팀장의 지표 브리핑(방문·클릭·추천 수)은 싣지 않는다 — 독자에게 내부 운영 수치다
            picked.append({'agent': t['agent'], 'text': _around(t['text'], hit, 140, 300)})
    if len(picked) < 2:   # 제목이 그대로 안 나오면 제안자 발언으로
        props = set(heads.values())
        picked = [{'agent': t['agent'], 'text': _clip(t['text'], 380)} for t in turns if t['agent'] in props][:6]
    picked = [{**ln, 'text': _scrub(ln['text'])} for ln in picked]
    picked = [ln for ln in picked if len(ln['text']) >= 20]
    return {'date': f"{timezone.localtime(meeting.held_at):%m.%d}", 'lines': picked[:6]}


def collect(run_date: date) -> dict:
    start, end = window(run_date)
    lo, hi = _span(start, end)
    published = _published(lo, hi)
    picks = _picks(published)
    return {'start': start.isoformat(), 'end': end.isoformat(), 'published': published, 'picks': picks,
            'meeting': _meeting_talk(picks), 'next': _next_week(run_date)}


# ───────────────────────────── 문구(큐레이터)
PROMPT = (
    '연구실 위클리의 문구를 씁니다. 인스타그램 카드뉴스 같은 큐레이션으로, 이번 주 연구실이 낸 칼럼을 독자에게 추천하는 게 목적입니다.\n'
    '흐름: 표지(훅) → 회의실에서(이 주제를 왜 골랐나 — 회의에서 오간 말) → 추천 칼럼 카드(왜 지금 읽을 만한지, 무엇을 얻는지, '
    '누구에게 좋은지) → 다음 주 예고.\n'
    '톤: 요즘 카드뉴스처럼 짧고 리듬감 있게, 친근한 해요체. 광고 같은 과장·이모지는 쓰지 않습니다. '
    '제작 과정의 수정 횟수·심사 점수·실패담은 쓰지 않습니다.\n'
    '회의 대화는 [이번 주 사실]의 회의 발언(meeting.lines)을 바탕으로, 그 연구원이 한 말의 뜻을 살려 짧게 옮깁니다. '
    '하지 않은 말은 지어내지 않습니다.\n\n'
    '[이번 주 사실]\n{facts}\n\n'
    '출력 JSON: {{"theme": "표지 훅", "intro": "표지 소개", "chat": [{{"agent": "연구원 키", "line": "한 줄"}}], '
    '"picks": {{"글 id": {{"hook": "...", "why_now": "...", "points": ["...", "...", "..."], "for_whom": "..."}}}}}}\n'
    '규칙:\n'
    '- theme: {theme}자 이내. 이번 주 추천 글들을 관통하는 훅 한 구절 — 질문이나 반전으로 궁금하게. "○편 발행" 같은 보고서 제목 금지. '
    '핵심 낱말 하나를 *별표*로 감쌉니다.\n'
    '- intro: {intro}자 이내 두 문장. 이번 주에 무엇을 추천하는지.\n'
    '- chat: meeting.lines 가 있으면 3~4줄, 회의 순서대로. 각 line {chat}자 이내. 연구원이 현장·업계에서 무엇을 보고 '
    '이 주제가 독자에게 필요하다고 판단했는지가 드러나게. agent 는 그 말을 한 연구원 키({agents}). meeting 이 비어 있으면 [].\n'
    '- picks: 추천 글(picks)마다. hook {hook}자 이내 — 독자가 멈춰 읽을 질문이나 한 줄. why_now {why_now}자 이내 — 독자의 일·업계에서 '
    '지금 이 글이 필요한 이유("회의에서~"로 시작하지 않기). points 정확히 3개, 각 {point}자 이내 — 이 글에서 얻는 것(요약·소제목 근거). '
    'for_whom {for_whom}자 이내 — 이런 분께 추천.\n'
    '- 절대 쓰지 않기: 우리 사이트의 방문자·클릭·노출·조회·추천 수·검색 순위 같은 운영 지표, "우리 칼럼에 같은 주제가 없었다" 같은 '
    '운영 사정. 독자는 그걸 보고 읽을 이유를 얻지 못하고, 사이트가 초라해 보입니다.\n'
    '- 숫자는 아라비아 숫자로, [이번 주 사실]에 있는 값만. 맞춤법을 한 번 더 봅니다.{retry}'
)


def _facts_text(facts: dict) -> str:
    return json.dumps({
        '기간': f"{facts['start']} ~ {facts['end']}",
        '새로 발행한 글 수': sum(not p['remake'] for p in facts['published']),
        '다시 다듬어 갱신한 글 수': sum(p['remake'] for p in facts['published']),
        '추천 글(picks)': [{k: v for k, v in p.items() if k not in ('url', 'date')} for p in facts.get('picks') or []],
        '편집회의(meeting)': facts.get('meeting') or {},
        '다음 주': [{'요일': n['day'], '할 일': n['what'], '비고': n['note']} for n in facts['next']],
    }, ensure_ascii=False, indent=1)


def _plain_len(s: str) -> int:
    return len(re.sub(r'\*', '', s or ''))


def _too_long(s, n) -> bool:
    return not s or _plain_len(str(s)) > n


def _pick_copy(copy: dict, pid) -> dict:
    picks = copy.get('picks') or {}
    return picks.get(str(pid)) or picks.get(pid) or {}


def _problems(copy: dict, facts: dict) -> list[str]:
    from office import evidence as E
    out = []
    if _too_long(copy.get('theme'), LIMITS['theme']):
        out.append(f"theme 을 {LIMITS['theme']}자 이내로")
    if _too_long(copy.get('intro'), LIMITS['intro']):
        out.append(f"intro 를 {LIMITS['intro']}자 이내로")
    chat = copy.get('chat') or []
    usable = len((facts.get('meeting') or {}).get('lines') or [])
    if usable >= CHAT_RANGE[0]:
        if not CHAT_RANGE[0] <= len(chat) <= CHAT_RANGE[1]:
            out.append(f'chat 은 {CHAT_RANGE[0]}~{CHAT_RANGE[1]}줄로')
    elif chat:      # 쓸 만한 회의 발언이 적으면 회의실 카드를 빼는 게 낫다(말풍선 한두 개는 빈약해 보인다)
        out.append('chat 은 [] 로(쓸 만한 회의 발언이 적음)')
    if usable:
        if any(c.get('agent') not in AGENT_ORDER or _too_long(c.get('line'), LIMITS['chat']) for c in chat if isinstance(c, dict)):
            out.append(f"chat 의 agent 는 정해진 키, line 은 {LIMITS['chat']}자 이내로")
    texts = [copy.get('theme', ''), copy.get('intro', '')] + [str(c.get('line', '')) for c in chat if isinstance(c, dict)]
    for p in facts.get('picks') or []:
        c = _pick_copy(copy, p['id'])
        pts = c.get('points') or []
        bad = [k for k in ('hook', 'why_now', 'for_whom') if _too_long(c.get(k), LIMITS[k])]
        if len(pts) != 3 or any(_too_long(x, LIMITS['point']) for x in pts):
            bad.append('points(3개)')
        if bad:
            out.append(f"picks[{p['id']}] 의 {', '.join(bad)} 를 정해진 길이로")
        texts += [str(c.get(k, '')) for k in ('hook', 'why_now', 'for_whom')] + [str(x) for x in pts]
    loose = E.unmatched(' '.join(texts).replace('*', ''), _facts_text(facts))
    if loose:
        out.append(f"사실에 없는 숫자 {', '.join(sorted({n for n, _ in loose}))} 를 빼거나 사실의 값으로")
    out += public_problems(copy, facts)
    return out


def public_problems(copy: dict, facts: dict) -> list[str]:
    """독자에게 내보내면 안 되는 문구 — 사이트 운영 지표, 카탈로그 사정, '회의에서~'로 시작하는 읽을 이유."""
    out = []
    fields = [('theme', copy.get('theme', '')), ('intro', copy.get('intro', ''))]
    fields += [(f'chat[{i}]', c.get('line', '')) for i, c in enumerate(copy.get('chat') or []) if isinstance(c, dict)]
    for p in facts.get('picks') or []:
        c = _pick_copy(copy, p['id'])
        fields += [(f"picks[{p['id']}].{k}", str(c.get(k, ''))) for k in ('hook', 'why_now', 'for_whom')]
        if str(c.get('why_now', '')).lstrip().startswith('회의에서'):
            out.append(f"picks[{p['id']}].why_now 를 '회의에서~'가 아니라 독자의 일에서 지금 필요한 이유로")
    for name, text in fields:
        if SITE_METRIC.search(text or ''):
            out.append(f'{name} 에서 사이트 운영 지표(방문·클릭·노출·조회·추천 수·순위)를 빼세요')
        elif CATALOG_GAP.search(text or ''):
            out.append(f'{name} 에서 "우리 칼럼에 없던 주제" 같은 운영 사정을 빼고 독자 관점의 이유로')
    return out


def _fit(s: str, n: int) -> str:
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def default_copy(facts: dict) -> dict:
    """모델 없이 사실만으로 만드는 문구 — 호출 실패·검사 실패 때의 안전판."""
    picks = facts.get('picks') or []
    theme = '이번 주 읽을 만한 *연구실 칼럼*' if picks else '다음 주를 준비한 *연구실*'
    intro = (f'연구실이 이번 주 고른 칼럼 {len(picks)}편을 소개해요. 회의에서 왜 이 주제를 골랐는지도 함께 적었어요.'
             if picks else '이번 주에는 새 글 대신 다음 주제를 준비했어요. 다음 주 일정을 확인해 주세요.')
    lines = (facts.get('meeting') or {}).get('lines') or []
    chat = [{'agent': ln['agent'], 'line': _fit((_sentences(ln['text']) or [''])[0].lstrip('…'), LIMITS['chat'])}
            for ln in lines[:CHAT_RANGE[1]]]
    if lines and len(chat) < CHAT_RANGE[0]:
        chat = []
    out = {}
    for p in picks:
        sents = _sentences(p['summary'])
        pts = [_fit(s, LIMITS['point']) for s in sents[:3]]
        pts += [_fit(h, LIMITS['point']) for h in p['headings'] if len(pts) < 3]
        while len(pts) < 3:
            pts.append(_fit('키워드 ' + '·'.join(p['keywords'][:3] or ['칼럼']), LIMITS['point']))
        cat = p['cat'].split('·')[-1].strip()
        out[str(p['id'])] = {'hook': _fit(p['title'], LIMITS['hook']),
                             'why_now': _fit((sents[0] if sents else p['title']), LIMITS['why_now']),
                             'points': pts[:3], 'for_whom': _fit(FOR_WHOM.get(cat, '테크창 독자'), LIMITS['for_whom'])}
    return {'theme': theme, 'intro': _fit(intro, LIMITS['intro']), 'chat': chat, 'picks': out, 'source': 'default'}


def curate(facts: dict, *, ask_json=None, shorten: list | None = None) -> dict:
    if ask_json is None:
        from office.services import ask_agent_json as ask_json
    retry = ''
    if shorten:
        retry = '\n\n직전 문구가 카드 칸을 넘쳤습니다. 다음을 더 짧게: ' + ', '.join(shorten)
    probs = []
    for _ in range(2):
        try:
            copy = ask_json(CURATOR, PROMPT.format(
                facts=_facts_text(facts), agents=', '.join(AGENT_ORDER), retry=retry, **LIMITS), max_tokens=3500)
        except Exception as exc:  # noqa: BLE001
            logger.warning('위클리 큐레이션 실패: %s', exc)
            return default_copy(facts)
        copy = copy if isinstance(copy, dict) else {}
        probs = _problems(copy, facts)
        if not probs:
            copy['source'] = 'curator'
            return copy
        retry = '\n\n직전 문구의 문제: ' + '; '.join(probs) + '. 고쳐서 다시 내세요.'
    logger.warning('위클리 문구 검사 실패 — 기본 문구 사용: %s', probs)
    return default_copy(facts)


# ───────────────────────────── 카드 렌더
def context(facts: dict, copy: dict, issue_no: int, run_date: date) -> dict:
    sp = {k: sprite(k) for k in AGENT_ORDER}
    from office.agents import AGENTS
    code, _slug = week_code(run_date)
    start, end = date.fromisoformat(facts['start']), date.fromisoformat(facts['end'])
    theme = escape(copy['theme'])
    theme_html = mark_safe(re.sub(r'\*(.+?)\*', r'<em>\1</em>', str(theme)))
    chat = [{'agent': c['agent'], 'name': AGENTS[c['agent']]['name'], 'role': AGENTS[c['agent']]['title'],
             'sprite': sp.get(c['agent'], ''), 'line': c.get('line', '')}
            for c in (copy.get('chat') or []) if isinstance(c, dict) and c.get('agent') in AGENTS]
    ids = ['cover'] + (['meeting'] if chat else [])
    picks = []
    for i, p in enumerate(facts.get('picks') or [], 1):
        c = _pick_copy(copy, p['id'])
        picks.append({**p, **{k: c.get(k, '') for k in ('hook', 'why_now', 'for_whom')}, 'points': c.get('points') or [],
                      'n': i, 'sprite': sp.get(p['author_key'], ''), 'author': AGENTS.get(p['author_key'], {}).get('name', ''),
                      'link': f"techchang.com{p['url']}".rstrip('/')})
        ids.append(f'pick-{i}')
    ids.append('next')
    pages = {cid: i for i, cid in enumerate(ids, 1)}
    for p in picks:
        p['page'] = pages[f"pick-{p['n']}"]
    alts = (['표지 — 이번 주 연구실 큐레이션'] + (['회의실에서 — 이 주제를 고른 편집회의 대화'] if chat else [])
            + [f"추천 칼럼 {p['n']} — {p['title']}" for p in picks] + ['다음 관측 — 다음 주 일정'])
    return {
        'no': issue_no, 'no_pad': f'{issue_no:02d}', 'week_code': code,
        'range': f'{start:%m.%d} – {end:%m.%d}', 'theme_html': theme_html, 'theme_plain': copy['theme'].replace('*', ''),
        'intro': copy.get('intro', ''),
        'agents': [{'key': k, 'name': AGENTS[k]['name'], 'sprite': sp[k]} for k in AGENT_ORDER],
        'chat': chat, 'meeting_date': (facts.get('meeting') or {}).get('date', ''), 'picks': picks,
        'count_new': sum(not p['remake'] for p in facts['published']),
        'count_remade': sum(p['remake'] for p in facts['published']),
        'next': [{**n, 'sprite': sp.get(n['agent'], '')} for n in facts['next']],
        'card_ids': ids + ['og'], 'pages': pages, 'total': f'{len(ids):02d}', 'alts': alts,
    }


OVERFLOW_JS = """() => {
  const out = [...document.querySelectorAll('.fit')]
    .filter(e => e.scrollHeight > e.clientHeight + 4).map(e => e.dataset.fit);
  // 카드 레이아웃 — 블록끼리 겹치거나(말풍선이 아래 상자에 닿음), 꼬리말 선을 침범하면 'layout:<카드>'
  for (const card of document.querySelectorAll('section.card')) {
    const frame = card.querySelector('.frame');
    if (!frame) continue;
    const kids = [...frame.children].filter(k => k.offsetHeight > 0);
    const foot = kids.find(k => k.classList.contains('bottom'));
    const body = kids.filter(k => k !== foot);
    // 블록의 위·아래는 상자가 아니라 안쪽 내용으로 잰다 — 남는 높이를 채우는 블록(flex-grow)이나 안쪽 여백은 겹침이 아니다
    const kidsOf = el => [...el.children].filter(k => k.offsetHeight > 0);
    const end = el => kidsOf(el).length ? Math.max(...kidsOf(el).map(k => k.getBoundingClientRect().bottom))
                                        : el.getBoundingClientRect().bottom;
    const start = el => (parseFloat(getComputedStyle(el).flexGrow) > 0 && kidsOf(el).length)
                        ? Math.min(...kidsOf(el).map(k => k.getBoundingClientRect().top)) : el.getBoundingClientRect().top;
    let bad = false;
    for (let i = 1; i < body.length; i++) {
      if (start(body[i]) < end(body[i - 1]) + 12) bad = true;
    }
    if (foot && body.length && end(body[body.length - 1]) > foot.getBoundingClientRect().top - 12) bad = true;
    const fr = frame.getBoundingClientRect();
    if (frame.scrollHeight > frame.clientHeight + 2 || body.some(k => k.getBoundingClientRect().bottom > fr.bottom)) bad = true;
    if (bad) out.push('layout:' + card.id);
  }
  return out;
}"""


def render(nl: dict, out_dir: str | None) -> list[str]:
    """카드 PNG 를 찍는다. 반환: 넘친 글자 칸 키. out_dir 이 None 이면 재기만 한다."""
    from playwright.sync_api import sync_playwright
    html = render_to_string('newsletter/cards.html', {'nl': nl})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': 1400}, device_scale_factor=1)
            page.set_content(html, wait_until='load')
            page.evaluate('document.fonts.ready.then(() => true)')
            over = page.evaluate(OVERFLOW_JS)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
                for cid in nl['card_ids']:
                    page.locator(f'#{cid}').screenshot(path=os.path.join(out_dir, f'{cid}.png'))
        finally:
            browser.close()
    return over


CURATED_KEYS = re.compile(r'^(theme|og-theme|intro|chat-\d+|hook-\d+|why-\d+|pt-\d+-\d+|whom-\d+)$')


def _fix_layout(issues: list, copy: dict) -> bool:
    """코드로 고칠 수 있는 레이아웃 — 회의실 카드가 넘치면 말풍선을 하나 줄인다. 고쳤으면 True."""
    if 'layout:meeting' in issues and len(copy.get('chat') or []) > CHAT_RANGE[0]:
        copy['chat'] = copy['chat'][:-1]
        return True
    return False


def make(run_date: date | None = None, *, dry: bool = False, ask_json=None, renderer=None, use_model: bool = True,
         out=print):
    """한 호를 만든다. dry 면 저장하지 않고 카드만 media/newsletter/_dry/ 에 찍는다. 반환: Newsletter 또는 dict."""
    from office.models import Newsletter
    run_date = run_date or timezone.localdate()
    renderer = renderer or render
    code, slug = week_code(run_date)
    existing = Newsletter.objects.filter(slug=slug).first()
    issue_no = existing.issue_no if existing else (Newsletter.objects.order_by('-issue_no').values_list('issue_no', flat=True).first() or 0) + 1

    facts = collect(run_date)
    out(f'{code} · {facts["start"]}~{facts["end"]} · 발행 {len(facts["published"])}편 · 추천 {len(facts["picks"])}편'
        f' · 회의 발언 {len((facts["meeting"] or {}).get("lines") or [])}')
    copy = curate(facts, ask_json=ask_json) if use_model else default_copy(facts)
    nl = context(facts, copy, issue_no, run_date)
    over = [k for k in renderer(nl, None) if CURATED_KEYS.match(k)]
    if over and use_model:
        out(f'  글자 넘침 {over} — 큐레이터에게 줄이게 합니다')
        copy = curate(facts, ask_json=ask_json, shorten=over)
        nl = context(facts, copy, issue_no, run_date)
        over = [k for k in renderer(nl, None) if CURATED_KEYS.match(k)]
    if over:
        out(f'  여전히 넘침 {over} — 기본 문구로 대신합니다')
        copy = default_copy(facts)
        nl = context(facts, copy, issue_no, run_date)

    # 마지막 관문 — 카드 레이아웃(블록 겹침·넘침)과 공개 금지 문구. 코드로 고칠 수 있으면 고치고, 아니면 공개하지 않는다
    issues = renderer(nl, None)
    for _ in range(3):
        if not _fix_layout(issues, copy):
            break
        nl = context(facts, copy, issue_no, run_date)
        issues = renderer(nl, None)
    blockers = [k for k in issues if k.startswith('layout:') or CURATED_KEYS.match(k)] + public_problems(copy, facts)

    rel = f"newsletter/{'_dry' if dry else slug}"          # URL 에도 쓰므로 os.path.join 이 아닌 '/'
    renderer(nl, os.path.join(settings.MEDIA_ROOT, 'newsletter', '_dry' if dry else slug))
    stamp = timezone.now().strftime('%Y%m%d%H%M')
    urls = [f"{settings.MEDIA_URL}{rel}/{cid}.png?v={stamp}" for cid in nl['card_ids']]
    out(f"  문구 출처: {copy.get('source')} · 제목: {nl['theme_plain']}")
    if blockers:
        out(f'  공개 보류 — {blockers}')
    if dry:
        return {'facts': facts, 'copy': copy, 'cards': urls, 'blockers': blockers}
    data = {'facts': facts, 'copy': copy, 'alts': nl['alts'], 'blockers': blockers}
    if blockers and existing and existing.status == Newsletter.STATUS_PUBLISHED:
        _alert_blocked(run_date, code, blockers, kept=True)     # 이미 공개된 판은 그대로 둔다
        return existing
    obj, _ = Newsletter.objects.update_or_create(slug=slug, defaults={
        'issue_no': issue_no, 'week_start': date.fromisoformat(facts['start']), 'week_end': date.fromisoformat(facts['end']),
        'title': nl['theme_plain'], 'intro': nl['intro'], 'data': data, 'cards': urls[:-1], 'og_image': urls[-1],
        'status': Newsletter.STATUS_HOLD if blockers else Newsletter.STATUS_PUBLISHED,
        'published_at': None if blockers else timezone.now()})
    if blockers:
        _alert_blocked(run_date, code, blockers, kept=False)
    return obj


def _alert_blocked(run_date, code, blockers, *, kept: bool):
    """검사를 통과하지 못한 호 — 공개하지 않고 운영자에게 [다시 만들기] 버튼과 함께 알린다."""
    try:
        from office import jobmail as J
        args = ['make_newsletter', '--date', run_date.isoformat()]
        J.send(f'위클리 {code} 공개 보류 — 카드·문구 검사 실패',
               [f'{code} 위클리가 공개 전 검사를 통과하지 못해 ' + ('이전 공개판을 그대로 두었습니다.' if kept else '공개하지 않았습니다.'),
                '', '걸린 항목:'] + [f'  - {b}' for b in blockers[:12]],
               [('다시 만들기', J.link(J.make_token('rerun', args, f'위클리 {code} 다시 만들기')),
                 '같은 주의 위클리를 처음부터 다시 만들고 다시 검사합니다.')])
    except Exception:  # noqa: BLE001 — 알림 실패가 제작을 막지 않게
        logger.exception('위클리 보류 알림 실패')
