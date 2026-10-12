"""연구실 위클리 — 매주 금요일, 지난 한 주(금~목)의 연구실 활동과 발행을 카드뉴스 5장 + 웹 페이지로 엮는다.

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
LIMITS = {'theme': 18, 'intro': 80, 'takeaway': 56, 'behind': 38}
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
    reviews = StageRun.objects.filter(stage='review', created_at__range=(lo, hi)).count()
    scores = [p['score'] for p in published if p['score']]
    decisions = Decision.objects.filter(meeting__held_at__range=(lo, hi)).count()
    rows = [
        {'label': '설계도 단계에서 원문으로 확인한 주장', 'value': f'{verified}', 'unit': f'/ {total}건' if total else '건'},
        {'label': '근거 없는 수치라 지운 문장', 'value': f'{dropped}', 'unit': '문장'},
        {'label': '편집 심사를 거친 횟수', 'value': f'{reviews}', 'unit': '회'},
    ]
    if scores:
        rows.append({'label': '발행 글 편집 심사 평균', 'value': f'{sum(scores) / len(scores):.1f}', 'unit': '점'})
    else:
        rows.append({'label': '편집회의에서 정한 안건', 'value': f'{decisions}', 'unit': '건'})
    return rows


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


def collect(run_date: date) -> dict:
    start, end = window(run_date)
    lo, hi = _span(start, end)
    published = _published(lo, hi)
    numbers, visits, peak = _numbers(start, end)
    return {'start': start.isoformat(), 'end': end.isoformat(), 'published': published,
            'ledger': _ledger(lo, hi, published), 'numbers': numbers, 'visits': visits, 'visits_peak': peak,
            'next': _next_week(run_date)}


# ───────────────────────────── 문구(큐레이터)
PROMPT = (
    '연구실 위클리(카드뉴스 5장)의 문구를 씁니다. 아래 [이번 주 사실]만 근거로, 담백하게 씁니다. 과장·감탄사·이모지는 쓰지 않습니다.\n\n'
    '[이번 주 사실]\n{facts}\n\n'
    '출력 JSON: {{"theme": "표지 제목", "intro": "표지 소개", "takeaways": {{"글 id": "한 줄 요약"}}, '
    '"behind": {{"agent": "연구원 키", "line": "그 연구원의 한마디"}}}}\n'
    '규칙:\n'
    '- theme: {theme}자 이내. 이번 주 연구실에서 가장 의미 있었던 일을 한 구절로. 가장 중요한 낱말 하나를 *별표*로 감쌉니다.\n'
    '- intro: {intro}자 이내, 존댓말 두 문장. 이번 주에 무엇을 했고 무엇이 나왔는지.\n'
    '- takeaways: 발행된 글마다 {takeaway}자 이내. 독자가 가져갈 한 가지. 요약을 그대로 옮기지 말고 핵심만.\n'
    '- behind: agent 는 {agents} 중 이번 주 일과 가장 관련 있는 연구원. line 은 {behind}자 이내, 그 연구원이 이번 주 '
    '한 일을 1인칭 존댓말로 담백하게.\n'
    '- 숫자는 [이번 주 사실]에 있는 값만 씁니다. 없는 숫자는 쓰지 않습니다.{retry}'
)


def _facts_text(facts: dict) -> str:
    pub = [{'id': p['id'], 'title': p['title'], 'cat': p['cat'], 'score': p['score'], 'summary': p['summary']}
           for p in facts['published']]
    return json.dumps({'기간': f"{facts['start']} ~ {facts['end']}", '발행': pub, '연구실 기록': facts['ledger'],
                       '지표': facts['numbers'], '다음 주': [{'요일': n['day'], '할 일': n['what'], '비고': n['note']}
                                                       for n in facts['next']]},
                      ensure_ascii=False, indent=1)


def _plain_len(s: str) -> int:
    return len(re.sub(r'\*', '', s or ''))


def _problems(copy: dict, facts: dict) -> list[str]:
    from office import evidence as E
    pack = _facts_text(facts)
    out = []
    if not copy.get('theme') or _plain_len(copy['theme']) > LIMITS['theme']:
        out.append(f"theme 을 {LIMITS['theme']}자 이내로")
    if not copy.get('intro') or _plain_len(copy['intro']) > LIMITS['intro']:
        out.append(f"intro 를 {LIMITS['intro']}자 이내로")
    takes = copy.get('takeaways') or {}
    for p in facts['published'][:3]:
        t = takes.get(str(p['id'])) or takes.get(p['id'])
        if not t or _plain_len(t) > LIMITS['takeaway']:
            out.append(f"takeaways[{p['id']}] 를 {LIMITS['takeaway']}자 이내로")
    b = copy.get('behind') or {}
    if b.get('agent') not in AGENT_ORDER or not b.get('line') or _plain_len(b['line']) > LIMITS['behind']:
        out.append(f"behind 의 agent 는 정해진 키, line 은 {LIMITS['behind']}자 이내로")
    text = ' '.join([copy.get('theme', ''), copy.get('intro', ''), b.get('line', '')] + [str(v) for v in takes.values()])
    loose = E.unmatched(text.replace('*', ''), pack)
    if loose:
        out.append(f"사실에 없는 숫자 {', '.join(sorted({n for n, _ in loose}))} 를 빼거나 사실의 값으로")
    return out


def default_copy(facts: dict) -> dict:
    """모델 없이 사실만으로 만드는 문구 — 호출 실패·검사 실패 때의 안전판."""
    n = len([p for p in facts['published'] if not p['remake']])
    m = len(facts['published'])
    theme = f'이번 주 *{m}편*을 내놓았습니다' if m else '이번 주 연구실 *관측 기록*'
    intro = (f'연구실이 이번 주 {m}편을 심사에 통과시켰습니다. 발행 글과 제작 과정의 기록을 정리했습니다.' if m
             else '이번 주에는 새 글 대신 원고를 다듬었습니다. 연구실이 무엇을 했는지 기록으로 남깁니다.')
    if n != m and m:
        intro = f'연구실이 이번 주 새 글 {n}편과 다시 다듬은 글 {m - n}편을 냈습니다. 발행 글과 제작 기록을 정리했습니다.'
    takes = {}
    for p in facts['published'][:3]:
        first = re.split(r'(?<=[.!?다])\s', (p['summary'] or '').strip())[0]
        takes[str(p['id'])] = first if len(first) <= LIMITS['takeaway'] else first[:LIMITS['takeaway'] - 1] + '…'
    return {'theme': theme, 'intro': intro, 'takeaways': takes,
            'behind': {'agent': 'checker', 'line': '원문으로 확인한 숫자만 본문에 남겼습니다.'}, 'source': 'default'}


def curate(facts: dict, *, ask_json=None, shorten: list | None = None) -> dict:
    if ask_json is None:
        from office.services import ask_agent_json as ask_json
    retry = ''
    if shorten:
        retry = '\n\n직전 문구가 카드 칸을 넘쳤습니다. 다음을 더 짧게: ' + ', '.join(shorten)
    for _ in range(2):
        try:
            copy = ask_json(CURATOR, PROMPT.format(
                facts=_facts_text(facts), agents=', '.join(AGENT_ORDER), retry=retry, **LIMITS), max_tokens=2500)
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
    takes = copy.get('takeaways') or {}
    pub = []
    for p in facts['published']:
        pub.append({**p, 'takeaway': takes.get(str(p['id'])) or takes.get(p['id']) or '', 'sprite': sp.get(p['author_key'], ''),
                    'author': AGENTS.get(p['author_key'], {}).get('name', '')})
    b = copy.get('behind') or {}
    bk = b.get('agent') if b.get('agent') in AGENT_ORDER else 'checker'
    return {
        'no': issue_no, 'no_pad': f'{issue_no:02d}', 'week_code': code,
        'range': f'{start:%m.%d} – {end:%m.%d}', 'theme_html': theme_html, 'theme_plain': copy['theme'].replace('*', ''),
        'intro': copy.get('intro', ''),
        'agents': [{'key': k, 'name': AGENTS[k]['name'], 'sprite': sp[k]} for k in AGENT_ORDER],
        'published': pub,
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


CURATED_KEYS = re.compile(r'^(theme|og-theme|intro|behind|pub-take-\d+)$')


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
