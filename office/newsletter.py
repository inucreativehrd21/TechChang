"""연구실 위클리 — 매주 금요일, 지난 한 주(금~목)의 연구실 활동과 발행을 카드뉴스 5장 + 웹 페이지로 엮는다.

성과 리포트가 아니라 뒷이야기 — 왜 그 주제였나(편집회의), 만들며 무엇이 꼬였나(심사 점수·가제·사고)를 유쾌하게.
흐름: collect(사실 모으기) → curate(큐레이터 은혜가 문구 쓰기) → render(카드 PNG) → 저장(office.models.Newsletter)
- 사실은 DB 에서만 모은다(발행 기록·칼럼 지도 요약·제작 단계 기록·방문/검색 지표). 큐레이터는 문구만 쓴다.
- 문구의 숫자는 모은 사실에 있는 값만(office.evidence 수치 대조). 길이·숫자가 어긋나면 한 번 고치게 하고,
  그래도 안 되면 사실로 만든 기본 문구로 대신한다 — 모델 호출이 실패해도 위클리는 나간다.
- 카드는 templates/newsletter/cards.html(디자인 원칙 DESIGN.md 「관측 원장」)을 Playwright 로 찍는다.
  글자 칸이 넘치면(.fit) 큐레이터에게 줄이게 한다.
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
LIMITS = {'theme': 20, 'intro': 90, 'why': 60, 'hero_head': 18, 'event': 40, 'behind': 40, 'scene': 64}
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


def _ledger(lo, hi, published) -> list[dict]:
    from office.models import Decision, StageRun
    verified = total = 0
    for r in StageRun.objects.filter(stage='blueprint', created_at__range=(lo, hi)).only('output'):
        for c in ((r.output or {}).get('verify') or {}).get('claims') or []:
            total += 1
            verified += c.get('status') == 'verified'
    dropped = sum(len((r.output or {}).get('removed') or [])
                  for r in StageRun.objects.filter(stage='lock', created_at__range=(lo, hi)).only('output'))
    scores = [p['score'] for p in published if p['score']]
    decisions = Decision.objects.filter(meeting__held_at__range=(lo, hi)).count()
    new = sum(not p['remake'] for p in published)
    remade = len(published) - new
    # 0 인 줄은 싣지 않는다 — 카드에 '0건'이 늘어서면 아무 일도 없던 주처럼 보인다
    rows = [{'label': '새로 발행한 글', 'value': f'{new}', 'unit': '편'}]
    if remade:
        rows.append({'label': '다시 다듬어 갱신한 글', 'value': f'{remade}', 'unit': '편'})
    if total:
        rows.append({'label': '설계도 단계에서 원문으로 확인한 주장', 'value': f'{verified}', 'unit': f'/ {total}건'})
    if dropped:
        rows.append({'label': '근거 없는 수치라 지운 문장', 'value': f'{dropped}', 'unit': '문장'})
    if scores:
        rows.append({'label': f'심사 점수 평균 ({len(scores)}편)', 'value': f'{sum(scores) / len(scores):.1f}', 'unit': '점'})
    if decisions:
        rows.append({'label': '편집회의에서 정한 안건', 'value': f'{decisions}', 'unit': '건'})
    return rows[:4]


def _gsc() -> dict:
    try:
        from common.management.commands.send_visitor_report import Command as VR
        end = timezone.localdate() - timedelta(days=3)
        d = VR()._collect_gsc(end - timedelta(days=27), end)
        return d if d.get('available') else {}
    except Exception as exc:  # noqa: BLE001 — 지표 하나 실패로 위클리를 멈추지 않는다
        logger.warning('위클리 GSC 수집 실패: %s', exc)
        return {}


def _numbers(start, end) -> tuple[list, list, int]:
    from community import site_stats
    from community.models import DailyVisitor, Question
    from office import digest as D
    st = site_stats.stats()
    rows = {v.date: v.visitor_count for v in DailyVisitor.objects.filter(date__range=(start, end))}
    days = [start + timedelta(days=i) for i in range(7)]
    counts = [rows.get(d, 0) for d in days]
    peak = max(counts) or 1
    visits = [{'label': d.strftime('%m.%d'), 'pct': max(round(c * 100 / peak), 4), 'peak': c == peak and c > 0, 'count': c}
              for d, c in zip(days, counts)]
    cols = D.columns()
    series_n = cols.filter(series__isnull=False).count()
    nums = [
        {'value': f"{st['launch_days']:,}", 'unit': '일', 'label': '운영', 'note': '2025.10.01 문을 연 뒤로'},
        {'value': f"{st['visitors_total']:,}", 'unit': '', 'label': '누적 방문', 'note': f'이번 주 +{sum(counts):,}'},
        {'value': f"{st['lab_columns']:,}", 'unit': '편', 'label': '연구실 칼럼·연재',
         'note': f"칼럼 {st['lab_columns'] - series_n} · 연재 {series_n}"},
    ]
    g = _gsc()
    if g.get('position'):
        nums.append({'value': f"{g['position']:.1f}", 'unit': '위', 'label': '검색 평균 순위',
                     'note': f"최근 28일 · 클릭 {g.get('clicks', 0):,}회"})
    else:
        nums.append({'value': f'{sum(counts):,}', 'unit': '명', 'label': '이번 주 방문', 'note': '하루 방문자 합계'})
    return nums, visits, max(counts)


def _next_week(run_date: date) -> list[dict]:
    """다음 한 주 일정 — 토 프로그래밍, 일 편집회의, 월 연재(격주), 화 HRD, 목 데이터."""
    from community.models import ColumnSeries
    from community.series_catalog import SERIES
    from office.models import Decision
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
            pick = chosen(topic)
            rows.append({'date': d, 'day': WEEKDAY[wd], 'what': f'{CAT_LABEL[topic]} 칼럼',
                         'note': f'{label(d)} · ' + (pick or '편집회의가 정한 주제로'), 'agent': topic})
    rows.sort(key=lambda r: r['date'])
    for r in rows:
        r['date'] = r['date'].isoformat()
    return rows


# ───────────────────────────── 제작기(이야기 재료)
# 리포트가 아니라 뒷이야기 — 왜 이 주제였나(편집회의 제안과 그 이유), 만들면서 무엇이 꼬였나(심사 점수의 오르내림,
# 가제→최종 제목, 사고). 운영자 지시문(admin_note)과 운영·보안 안건은 싣지 않는다.
_SCORE = re.compile(r'(\d+)/100')
_WORKING = re.compile(r'초안 완성: (.+?) \(\d+자\)')


def _clip(s: str, n: int) -> str:
    s = re.sub(r'\s+', ' ', (s or '')).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def _around(text: str, needle: str, before: int = 160, after: int = 300) -> str:
    """회의 발언에서 그 제안이 나오는 부분만."""
    text = re.sub(r'\s+', ' ', text or '').strip()
    i = text.find(needle) if needle else -1
    if i < 0:
        return _clip(text, before + after)
    lo = max(0, i - before)
    return ('…' if lo else '') + _clip(text[lo:i + after], before + after)


def _origin(draft) -> dict:
    from office.agents import AGENTS
    d = draft.decision
    if d is None or d.meeting_id is None:
        return {'from': '연재 기획서' if draft.series_key else '편집장 의뢰', 'proposer': 'coding' if draft.series_key else 'lead',
                'pitch': _clip(draft.brief, 80), 'why': _clip(draft.brief, 200)}
    opt = next((o for o in (d.options or []) if o.get('key') == d.chosen_key), {}) or {}
    name = opt.get('proposed_by', '')
    key = next((k for k, a in AGENTS.items() if a['name'] == name), 'lead')
    head = (opt.get('title') or '')[:10]
    turns = [t for t in (d.meeting.transcript or []) if isinstance(t, dict) and t.get('agent') == key]
    said = next((t['text'] for t in turns if head and head in (t.get('text') or '')), turns[0]['text'] if turns else '')
    return {'from': f"{timezone.localtime(d.meeting.held_at):%m.%d} 편집회의 · {name or AGENTS[key]['name']} 제안",
            'proposer': key, 'pitch': _clip(opt.get('title'), 80),
            'why': _around(said, head) if said else _clip(opt.get('detail'), 300)}


def _journey(draft) -> dict:
    scores, notes, working, fact_issues = [], [], '', 0
    for w in draft.logs.exclude(action='admin_note').order_by('created_at'):
        t = w.text or ''
        if w.action == 'draft' and not working:
            m = _WORKING.search(t)
            working = m.group(1) if m else ''
        elif w.action == 'qa':
            m = _SCORE.search(t)
            if m:
                scores.append(int(m.group(1)))
                body = t.split('→', 1)[1] if '→' in t else t
                notes.append(f"편집장 {m.group(1)}점: " + _clip(body.split(':', 1)[-1], 120))
        elif w.action == 'critique' and len([n for n in notes if n.startswith('평론가')]) < 2:
            notes.append('평론가: ' + _clip(t.split(':', 1)[-1], 110))
        elif w.action == 'revise' and '실패' in t:
            notes.append('사고: ' + _clip(t, 110))
        elif w.action == 'chart' and '문제' in t:
            notes.append('도표: ' + _clip(t, 90))
        elif w.action == 'check':
            m = re.search(r'확인 필요 (\d+)건', t)
            fact_issues += int(m.group(1)) if m else 0
    if len(notes) > 9:   # 사고는 다 남기고, 심사평은 처음·최저·마지막 위주로
        keep = [n for n in notes if not n.startswith('편집장')]
        qa = [n for n in notes if n.startswith('편집장')]
        low = min(qa, key=lambda n: int(re.search(r'(\d+)점', n).group(1))) if qa else None
        picked = [qa[0], low, qa[-1]] if qa else []
        notes = [n for n in notes if n in keep[:6] or n in picked]
    return {'working_title': working, 'scores': scores, 'revisions': draft.revisions, 'fact_issues': fact_issues,
            'notes': notes}


def _making(lo, hi, published) -> tuple[list, int | None, dict]:
    """발행 글마다 제작기. 반환: (제작기 목록, 가장 고생한 글 id, 이번 주 반려·보류 수)."""
    from office.models import ColumnDraft, WorkLog
    stories = []
    for p in published:
        if p['remake']:
            dr = (ColumnDraft.objects.filter(target_question_id=p['id'], status=ColumnDraft.STATUS_PUBLISHED)
                  .order_by('-created_at').first())
        else:
            dr = ColumnDraft.objects.filter(question_id=p['id']).first()
        if dr is None:
            continue
        tries = ColumnDraft.objects.filter(target_question_id=p['id'], created_at__range=(lo, hi)).count() if p['remake'] else 1
        stories.append({'id': p['id'], 'title': p['title'], 'remake': p['remake'], 'author_key': p['author_key'],
                        'tries': tries, 'origin': _origin(dr), **_journey(dr)})
    pool = [s for s in stories if not s['remake']] or stories
    hero = max(pool, key=lambda s: (len(s['scores']) + s['tries'], s['revisions']), default=None)
    hero_id = hero['id'] if hero and (len(hero['scores']) >= 2 or hero['tries'] >= 2) else None
    week = {'rejected': ColumnDraft.objects.filter(created_at__range=(lo, hi), status=ColumnDraft.STATUS_REJECTED).count(),
            'holds': WorkLog.objects.filter(created_at__range=(lo, hi), action='hold').count()}
    # 새 글 제작기를 앞에, 갱신은 고생한 글만 남긴다
    keep = [s for s in stories if not s['remake']][:3]
    if hero_id and hero_id not in [s['id'] for s in keep]:
        keep.append(hero)
    return keep, hero_id, week


def _meeting_week(lo, hi) -> list[dict]:
    """이번 주 편집회의 — 무엇이 핫했고 무엇이 반응이 없었나(팀장 첫 브리핑)와 공개 요약."""
    from office.models import Meeting
    out = []
    for m in Meeting.objects.filter(held_at__range=(lo, hi)).order_by('held_at'):
        first = next((t['text'] for t in (m.transcript or []) if isinstance(t, dict) and t.get('agent') == 'lead'), '')
        out.append({'date': f"{timezone.localtime(m.held_at):%m.%d}", 'signals': _clip(first, 420),
                    'summary': _clip(m.public_summary, 260)})
    return out


def collect(run_date: date) -> dict:
    start, end = window(run_date)
    lo, hi = _span(start, end)
    published = _published(lo, hi)
    numbers, visits, peak = _numbers(start, end)
    making, hero_id, week = _making(lo, hi, published)
    return {'start': start.isoformat(), 'end': end.isoformat(), 'published': published,
            'ledger': _ledger(lo, hi, published), 'numbers': numbers, 'visits': visits, 'visits_peak': peak,
            'next': _next_week(run_date), 'making': making, 'hero_id': hero_id, 'week': week,
            'meetings': _meeting_week(lo, hi)}


# ───────────────────────────── 문구(큐레이터)
PROMPT = (
    '연구실 위클리(카드뉴스 5장)의 문구를 씁니다. 이건 성과 리포트가 아니라 연구실 뒷이야기입니다.\n'
    '왜 그 주제를 골랐는지(무엇이 검색되고 무엇이 반응이 좋았고 무엇이 비어 있었는지), 만들면서 무엇이 꼬였고 어떻게 풀었는지를 '
    '가감 없이, 유쾌하게 씁니다. 퇴짜·삽질·사고를 숨기지 말고 자조적인 농담으로 살립니다. 읽는 사람이 피식 웃고 다음 장을 넘기게.\n'
    '단, [이번 주 사실]에 없는 사건·대사·감정·숫자는 지어내지 않습니다. 특정 연구원을 깎아내리지 않습니다. 이모지 금지, 해요체.\n\n'
    '[이번 주 사실]\n{facts}\n\n'
    '출력 JSON: {{"theme": "표지 제목", "intro": "표지 소개", "whys": {{"글 id": "왜 이 주제였나"}}, '
    '"hero": {{"id": 글 id, "headline": "제작 일지 제목", "events": ["사건1", "사건2", "사건3"], "line": "쓴 연구원의 한마디"}}, '
    '"behind": {{"agent": "연구원 키", "line": "한마디"}}, "scene": "회의실 한 장면"}}\n'
    '규칙:\n'
    '- theme: {theme}자 이내. "○편 발행", "평균 ○점" 같은 보고서 제목 금지. 이번 주 가장 웃기거나 극적인 장면을 한 구절로, '
    '궁금해서 넘겨 보게. 핵심 낱말 하나를 *별표*로 감쌉니다.\n'
    '- intro: {intro}자 이내 두 문장. 무슨 일이 있었는지 맛보기. 새 글과 갱신(다시 다듬은 글)은 구분합니다.\n'
    '- whys: 제작기(making)의 글마다 {why}자 이내. 왜 이 주제였나 — 회의에서 나온 구체적 이유(검색어, 반응 좋던 형식, 비어 있던 자리)를.\n'
    '- hero: hero_id 가 있으면 그 글의 제작 일지. headline {hero_head}자 이내. events 2~3개, 각 {event}자 이내, 일어난 순서대로 '
    '사건 하나씩(가제, 점수가 떨어진 순간, 사고, 통과의 결정적 수정). line 은 그 글을 쓴 연구원의 1인칭 한마디 {behind}자 이내, 웃프게.\n'
    '- hero_id 가 null 이면 hero 는 null 로 두고 behind 를 씁니다: agent 는 {agents} 중 하나, line {behind}자 이내.\n'
    '- scene: 이번 주 편집회의(meetings)에서 가장 재밌는 장면 하나, {scene}자 이내 — 무엇이 핫했고 무엇이 반응이 없었는지, '
    '누가 무슨 근거로 무엇을 밀었는지. meetings 가 비어 있으면 빈 문자열.\n'
    '- 맞춤법을 한 번 더 봅니다.\n'
    '- 횟수·점수는 아라비아 숫자로, [이번 주 사실]에 있는 값만 씁니다.{retry}'
)


def _facts_text(facts: dict) -> str:
    new = sum(not p['remake'] for p in facts['published'])
    return json.dumps({
        '기간': f"{facts['start']} ~ {facts['end']}",
        '새로 발행한 글 수': new, '다시 다듬어 갱신한 글 수': len(facts['published']) - new,
        '이번 주 반려된 원고 수': (facts.get('week') or {}).get('rejected', 0),
        '이번 주 심사 미달 보류 수': (facts.get('week') or {}).get('holds', 0),
        '제작기(making)': facts.get('making') or [], 'hero_id': facts.get('hero_id'),
        '이번 주 편집회의': facts.get('meetings') or [],
        '연구실 기록': facts['ledger'], '지표': facts['numbers'],
        '다음 주': [{'요일': n['day'], '할 일': n['what'], '비고': n['note']} for n in facts['next']],
    }, ensure_ascii=False, indent=1)


def _plain_len(s: str) -> int:
    return len(re.sub(r'\*', '', s or ''))


def _too_long(s, n) -> bool:
    return not s or _plain_len(s) > n


def _problems(copy: dict, facts: dict) -> list[str]:
    from office import evidence as E
    pack = _facts_text(facts)
    out = []
    if _too_long(copy.get('theme'), LIMITS['theme']):
        out.append(f"theme 을 {LIMITS['theme']}자 이내로")
    if _too_long(copy.get('intro'), LIMITS['intro']):
        out.append(f"intro 를 {LIMITS['intro']}자 이내로")
    whys = copy.get('whys') or {}
    for s in (facts.get('making') or [])[:3]:
        if _too_long(whys.get(str(s['id'])) or whys.get(s['id']), LIMITS['why']):
            out.append(f"whys[{s['id']}] 를 {LIMITS['why']}자 이내로")
    if facts.get('meetings') and _too_long(copy.get('scene'), LIMITS['scene']):
        out.append(f"scene 을 {LIMITS['scene']}자 이내로")
    texts = [copy.get('theme', ''), copy.get('intro', ''), copy.get('scene') or ''] + [str(v) for v in whys.values()]
    if facts.get('hero_id'):
        h = copy.get('hero') or {}
        ev = h.get('events') or []
        if str(h.get('id')) != str(facts['hero_id']):
            out.append(f"hero.id 는 {facts['hero_id']}")
        if _too_long(h.get('headline'), LIMITS['hero_head']):
            out.append(f"hero.headline 을 {LIMITS['hero_head']}자 이내로")
        if not 2 <= len(ev) <= 3 or any(_too_long(e, LIMITS['event']) for e in ev):
            out.append(f"hero.events 는 2~3개, 각 {LIMITS['event']}자 이내로")
        if _too_long(h.get('line'), LIMITS['behind']):
            out.append(f"hero.line 을 {LIMITS['behind']}자 이내로")
        texts += [h.get('headline', ''), h.get('line', '')] + [str(e) for e in ev]
    else:
        b = copy.get('behind') or {}
        if b.get('agent') not in AGENT_ORDER or _too_long(b.get('line'), LIMITS['behind']):
            out.append(f"behind 의 agent 는 정해진 키, line 은 {LIMITS['behind']}자 이내로")
        texts.append(b.get('line', ''))
    loose = E.unmatched(' '.join(texts).replace('*', ''), pack)
    if loose:
        out.append(f"사실에 없는 숫자 {', '.join(sorted({n for n, _ in loose}))} 를 빼거나 사실의 값으로")
    return out


def _fit(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + '…'


def default_copy(facts: dict) -> dict:
    """모델 없이 사실만으로 만드는 문구 — 호출 실패·검사 실패 때의 안전판."""
    n = sum(not p['remake'] for p in facts['published'])
    m = len(facts['published']) - n
    making = facts.get('making') or []
    hero = next((s for s in making if s['id'] == facts.get('hero_id')), None)
    if hero and hero['scores']:
        k = len(hero['scores'])
        theme = f'심사 {k}번 만에 *통과*' if k > 1 else f'{hero["tries"]}번째 원고로 *통과*'
    elif n or m:
        theme = '이번 주 연구실 *뒷이야기*'
    else:
        theme = '원고를 붙잡은 *한 주*'
    intro = (f'새 글 {n}편' + (f'과 다시 다듬은 글 {m}편' if m else '') + '을 내놓기까지의 뒷이야기예요. 왜 그 주제였고 어디서 꼬였는지 적었어요.'
             if n or m else '이번 주에는 새 글 없이 원고를 다듬었어요. 무엇을 붙잡고 있었는지 적었어요.')
    whys = {str(s['id']): _fit(s['origin']['from'] + ' — ' + s['origin']['pitch'], LIMITS['why']) for s in making[:3]}
    mt = (facts.get('meetings') or [{}])[0]
    scene = _fit(mt.get('summary') or mt.get('signals') or '', LIMITS['scene']) if facts.get('meetings') else ''
    copy = {'theme': theme, 'intro': _fit(intro, LIMITS['intro']), 'whys': whys, 'scene': scene, 'source': 'default'}
    if hero:
        sc = hero['scores']
        ev = []
        if hero['working_title'] and hero['working_title'] != hero['title']:
            ev.append(_fit(f'가제는 「{hero["working_title"]}」', LIMITS['event']))
        if len(sc) > 1:
            ev.append(_fit(f'심사 점수 최저 {min(sc)}점까지 내려갔어요', LIMITS['event']))
            ev.append(_fit(f'{len(sc)}번째 심사에서 {sc[-1]}점으로 통과', LIMITS['event']))
        else:
            ev.append(_fit(f'원고 {hero["tries"]}개 중 하나가 살아남았어요', LIMITS['event']))
        copy['hero'] = {'id': hero['id'], 'headline': _fit(f'{hero["title"]}', LIMITS['hero_head']),
                        'events': ev[:3] if len(ev) >= 2 else ev + ['끝까지 고쳐서 내보냈어요'], 'line': '끝까지 고쳐서 내보냈어요.'}
    else:
        copy['behind'] = {'agent': 'checker', 'line': '원문으로 확인한 숫자만 본문에 남겼어요.'}
    return copy


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
                facts=_facts_text(facts), agents=', '.join(AGENT_ORDER), retry=retry, **LIMITS), max_tokens=3000)
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
PASS = 80


def context(facts: dict, copy: dict, issue_no: int, run_date: date) -> dict:
    sp = {k: sprite(k) for k in AGENT_ORDER}
    from office.agents import AGENTS
    code, _slug = week_code(run_date)
    start, end = date.fromisoformat(facts['start']), date.fromisoformat(facts['end'])
    theme = escape(copy['theme'])
    theme_html = mark_safe(re.sub(r'\*(.+?)\*', r'<em>\1</em>', str(theme)))
    whys = copy.get('whys') or {}
    making = {s['id']: s for s in facts.get('making') or []}
    pub = []
    for p in facts['published']:
        s = making.get(p['id'])
        pub.append({**p, 'why': whys.get(str(p['id'])) or whys.get(p['id']) or '', 'origin': (s or {}).get('origin', {}).get('from', ''),
                    'sprite': sp.get(p['author_key'], ''), 'author': AGENTS.get(p['author_key'], {}).get('name', '')})
    stories = [p for p in pub if p['id'] in making][:3]
    hero = None
    h = copy.get('hero') or {}
    hs = making.get(facts.get('hero_id'))
    if hs and h:
        lo_ = 40
        bars = [{'v': v, 'pct': max(4, round((v - lo_) * 100 / (100 - lo_))), 'pass': v >= PASS} for v in hs['scores'][-10:]]
        hk = hs['author_key'] if hs['author_key'] in AGENTS else 'editor'
        hero = {'title': hs['title'], 'working': hs['working_title'] if hs['working_title'] != hs['title'] else '',
                'headline': h.get('headline', ''), 'events': h.get('events') or [], 'line': h.get('line', ''),
                'bars': bars, 'pass_pct': round((PASS - lo_) * 100 / (100 - lo_)), 'rounds': len(hs['scores']),
                'tries': hs['tries'], 'name': AGENTS[hk]['name'], 'role': AGENTS[hk]['title'], 'sprite': sp.get(hk, '')}
    b = copy.get('behind') or {}
    bk = b.get('agent') if b.get('agent') in AGENT_ORDER else 'checker'
    return {
        'no': issue_no, 'no_pad': f'{issue_no:02d}', 'week_code': code,
        'range': f'{start:%m.%d} – {end:%m.%d}', 'theme_html': theme_html, 'theme_plain': copy['theme'].replace('*', ''),
        'intro': copy.get('intro', ''),
        'agents': [{'key': k, 'name': AGENTS[k]['name'], 'sprite': sp[k]} for k in AGENT_ORDER],
        'published': pub, 'stories': stories, 'hero': hero,
        'scene': copy.get('scene') or '', 'scene_date': ((facts.get('meetings') or [{}])[0]).get('date', ''),
        'week': facts.get('week') or {},
        'count_new': sum(not p['remake'] for p in pub), 'count_remade': sum(p['remake'] for p in pub),
        'behind': {'name': AGENTS[bk]['name'], 'role': AGENTS[bk]['title'], 'sprite': sp[bk], 'line': b.get('line', '')},
        'ledger': facts['ledger'], 'numbers': facts['numbers'], 'visits': facts['visits'], 'visits_peak': facts['visits_peak'],
        'next': [{**n, 'sprite': sp.get(n['agent'], '')} for n in facts['next']],
    }


OVERFLOW_JS = """() => [...document.querySelectorAll('.fit')]
  .filter(e => e.scrollHeight > e.clientHeight + 4).map(e => e.dataset.fit)"""
CARD_IDS = ['card-1', 'card-2', 'card-3', 'card-4', 'card-5', 'og']


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
                for cid in CARD_IDS:
                    page.locator(f'#{cid}').screenshot(path=os.path.join(out_dir, f'{cid}.png'))
        finally:
            browser.close()
    return over


CURATED_KEYS = re.compile(r'^(theme|og-theme|intro|behind|scene|why-\d+|hero-head|hero-ev-\d+|hero-line)$')


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
    out(f'{code} · {facts["start"]}~{facts["end"]} · 발행 {len(facts["published"])}편')
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

    rel = f"newsletter/{'_dry' if dry else slug}"          # URL 에도 쓰므로 os.path.join 이 아닌 '/'
    renderer(nl, os.path.join(settings.MEDIA_ROOT, 'newsletter', '_dry' if dry else slug))
    stamp = timezone.now().strftime('%Y%m%d%H%M')
    urls = [f"{settings.MEDIA_URL}{rel}/{cid}.png?v={stamp}" for cid in CARD_IDS]
    out(f"  문구 출처: {copy.get('source')} · 제목: {nl['theme_plain']}")
    if dry:
        return {'facts': facts, 'copy': copy, 'cards': urls}
    data = {'facts': facts, 'copy': copy}
    obj, _ = Newsletter.objects.update_or_create(slug=slug, defaults={
        'issue_no': issue_no, 'week_start': date.fromisoformat(facts['start']), 'week_end': date.fromisoformat(facts['end']),
        'title': nl['theme_plain'], 'intro': nl['intro'], 'data': data, 'cards': urls[:5], 'og_image': urls[5],
        'status': Newsletter.STATUS_PUBLISHED, 'published_at': timezone.now()})
    return obj
