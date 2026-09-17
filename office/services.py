"""
연구실 공용 서비스: 에이전트 호출, 사이트 지표 수집, JSON 파싱, 차트 렌더링, 회의 결정 조회.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from common.services.claude import ask
from .agents import AGENTS, MODEL
from .models import ColumnDraft, Decision, Meeting, WorkLog

BOT_USERNAME = 'techchang연구팀'


# ───────────────────────────── 에이전트 호출
def ask_agent(key: str, prompt: str, *, max_tokens: int = 2000) -> str:
    return ask(prompt, system=AGENTS[key]['system'], model=MODEL, max_tokens=max_tokens).strip()


def ask_agent_json(key: str, prompt: str, *, max_tokens: int = 2000) -> dict:
    """JSON 만 답하도록 요청하고 파싱. 코드펜스·앞뒤 잡음은 걷어낸다."""
    suffix = '\n\n반드시 유효한 JSON 객체 하나만 출력하세요. 설명·코드펜스 금지.'
    raw = ask_agent(key, prompt + suffix, max_tokens=max_tokens)
    try:
        return parse_json(raw)
    except json.JSONDecodeError:
        # 적응형 thinking 이 출력 예산을 잠식해 비거나 잘린 경우 → 예산 3배로 1회 재시도
        raw = ask_agent(key, prompt + suffix, max_tokens=max_tokens * 3)
        return parse_json(raw)


def parse_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def log(agent: str, action: str, text: str, *, draft=None, meeting=None) -> WorkLog:
    return WorkLog.objects.create(agent=agent, action=action, text=text[:300], draft=draft, meeting=meeting)


# ───────────────────────────── 사이트 지표 수집
def collect_site_snapshot(days: int = 28) -> dict:
    """회의·QA 프롬프트에 넣을 사실 묶음. 외부 API(GSC) 는 실패해도 나머지는 살린다."""
    from community.models import ColumnSeries, DailyVisitor, Question
    from common.models import LogFinding

    today = timezone.localdate()
    since = today - timedelta(days=days)
    prev_since = since - timedelta(days=days)

    def visitors(a, b):
        return DailyVisitor.objects.filter(date__gte=a, date__lt=b).aggregate(s=Sum('visitor_count'))['s'] or 0

    bot_cols = (Question.objects.filter(is_deleted=False, author__username=BOT_USERNAME)
                .select_related('category').order_by('-create_date'))
    recent_cols = [
        {'id': q.id, 'subject': q.subject, 'category': q.category.name if q.category else '',
         'date': q.create_date.date().isoformat(), 'views': q.view_count,
         'votes': q.voter.count(), 'answers': q.answer_set.filter(is_deleted=False).count()}
        for q in bot_cols[:24]
    ]
    all_titles = list(bot_cols.values_list('subject', flat=True)[:200])

    top_viewed = [
        {'subject': q.subject, 'views': q.view_count, 'category': q.category.name if q.category else ''}
        for q in Question.objects.filter(is_deleted=False, create_date__date__gte=since)
        .select_related('category').order_by('-view_count')[:8]
    ]

    series = [
        {'title': s.title, 'slug': s.slug, 'planned': s.total_episodes,
         'published': Question.objects.filter(series=s, is_deleted=False).count(), 'active': s.is_active}
        for s in ColumnSeries.objects.all()[:5]
    ]

    findings = list(LogFinding.objects.filter(status=LogFinding.STATUS_PENDING)
                    .values_list('title', flat=True)[:8])

    last_meeting = Meeting.objects.order_by('-held_at').first()
    last_decisions = []
    if last_meeting:
        for d in last_meeting.decisions.all():
            last_decisions.append({
                'kind': d.kind, 'topic': d.topic, 'question': d.question,
                'chosen': (d.chosen or {}).get('title', '') if d.chosen_key else '(관리자 미선택)',
            })

    held = ColumnDraft.objects.filter(status=ColumnDraft.STATUS_HOLD).count()

    snap = {
        'today': today.isoformat(),
        'visitors': {'recent': visitors(since, today + timedelta(days=1)),
                     'previous': visitors(prev_since, since), 'days': days},
        'recent_columns': recent_cols,
        'all_column_titles': all_titles,
        'top_viewed': top_viewed,
        'series': series,
        'pending_findings': findings,
        'held_drafts': held,
        'last_meeting': last_decisions,
        'gsc': _collect_gsc(since, today),
    }
    return snap


def _collect_gsc(start: date, end: date) -> dict:
    """send_visitor_report 의 수집기를 재사용 (설정 없으면 {'available': False})."""
    try:
        from common.management.commands.send_visitor_report import Command as VR
        data = VR()._collect_gsc(start, end)
        if not data.get('available'):
            return {'available': False}
        # 프롬프트에 넣을 만큼만
        return {
            'available': True,
            'clicks': data.get('clicks'), 'impressions': data.get('impressions'),
            'ctr': data.get('ctr'), 'position': data.get('position'),
            'top_queries': (data.get('top_queries') or [])[:10],
        }
    except Exception as ex:  # noqa: BLE001 — 지표 수집 실패는 회의를 막지 않는다
        return {'available': False, 'error': str(ex)[:120]}


def snapshot_as_text(snap: dict) -> str:
    """에이전트에게 주는 브리핑 원문."""
    v = snap['visitors']
    lines = [f"기준일 {snap['today']} (최근 {v['days']}일)",
             f"방문자: 최근 {v['recent']}명 / 직전 기간 {v['previous']}명"]
    g = snap.get('gsc') or {}
    if g.get('available'):
        lines.append(f"검색(GSC): 클릭 {g.get('clicks')} · 노출 {g.get('impressions')} · CTR {g.get('ctr')} · 평균순위 {g.get('position')}")
        if g.get('top_queries'):
            qs = ', '.join(f"{q.get('k')}({q.get('clicks', 0)})" for q in g['top_queries'][:8] if isinstance(q, dict))
            lines.append(f"상위 검색어: {qs}")
    lines.append('최근 발행 칼럼(제목 | 분야 | 날짜 | 조회 | 추천):')
    for c in snap['recent_columns'][:16]:
        lines.append(f"  - {c['subject']} | {c['category']} | {c['date']} | {c['views']} | {c['votes']}")
    if snap['top_viewed']:
        lines.append('기간 내 조회 상위 글:')
        for t in snap['top_viewed']:
            lines.append(f"  - {t['subject']} ({t['category']}, {t['views']}회)")
    for s in snap['series']:
        lines.append(f"시리즈 '{s['title']}': {s['published']}/{s['planned']}회 발행, {'진행 중' if s['active'] else '중단'}")
    if snap['pending_findings']:
        lines.append('로그 분석 미결 지적사항: ' + '; '.join(snap['pending_findings']))
    if snap['held_drafts']:
        lines.append(f"검수 대기(보류) 칼럼: {snap['held_drafts']}편")
    if snap['last_meeting']:
        lines.append('지난 회의 결정:')
        for d in snap['last_meeting']:
            lines.append(f"  - [{d['kind']}{'/' + d['topic'] if d['topic'] else ''}] {d['question']} → {d['chosen']}")
    return '\n'.join(lines)


# ───────────────────────────── 회의 결정 → 칼럼 브리프
def take_column_brief(topic: str) -> Decision | None:
    """해당 분야의 가장 최근 '선택됐고 아직 쓰지 않은' 칼럼 안건. 없으면 None."""
    return (Decision.objects.filter(kind=Decision.KIND_COLUMN, topic=topic, consumed_at__isnull=True)
            .exclude(chosen_key='').select_related('meeting').order_by('-meeting__held_at').first())


def week_monday(d: date | None = None) -> date:
    d = d or timezone.localdate()
    return d - timedelta(days=d.weekday())


# ───────────────────────────── 차트
def render_chart(spec: dict, filename_stem: str) -> str | None:
    """
    charter 에이전트의 spec 으로 PNG 를 만들어 media/columns/ 에 저장하고 media 상대경로를 돌려준다.
    spec: {type: bar|line|hbar, title, labels[], series:[{name, values[]}], unit, source}
    matplotlib 미설치·데이터 불량이면 None.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return None

    labels = [str(x) for x in spec.get('labels') or []]
    series = [s for s in (spec.get('series') or []) if isinstance(s, dict) and s.get('values')]
    if not labels or not series:
        return None
    for s in series:
        try:
            s['values'] = [float(v) for v in s['values']][:len(labels)]
        except (TypeError, ValueError):
            return None
        if len(s['values']) != len(labels):
            return None

    # 한글 폰트: 레포 동봉 Noto Sans KR (TTF)
    font_path = Path(settings.BASE_DIR) / 'static' / 'fonts' / 'NotoSansKR-VariableFont_wght.ttf'
    family = 'sans-serif'
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        family = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams['font.family'] = family
    plt.rcParams['axes.unicode_minus'] = False

    palette = ['#4f46e5', '#2aa876', '#f0a33a', '#d9534f', '#3aa7c9']
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    kind = spec.get('type', 'bar')
    n = len(series)
    if kind == 'line':
        for i, s in enumerate(series):
            ax.plot(labels, s['values'], marker='o', linewidth=2, color=palette[i % 5], label=s.get('name', ''))
    elif kind == 'hbar':
        import numpy as np
        y = np.arange(len(labels))
        h = 0.8 / n
        for i, s in enumerate(series):
            ax.barh(y + i * h - 0.4 + h / 2, s['values'], height=h, color=palette[i % 5], label=s.get('name', ''))
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
    else:
        import numpy as np
        x = np.arange(len(labels))
        w = 0.8 / n
        for i, s in enumerate(series):
            bars = ax.bar(x + i * w - 0.4 + w / 2, s['values'], width=w, color=palette[i % 5], label=s.get('name', ''))
            ax.bar_label(bars, fmt='%g', fontsize=8, padding=2)
        ax.set_xticks(x, labels)
    ax.set_title(spec.get('title', ''), fontsize=12, fontweight='bold', loc='left', pad=12)
    if spec.get('unit'):
        ax.set_ylabel(spec['unit'] if kind != 'hbar' else '')
        if kind == 'hbar':
            ax.set_xlabel(spec['unit'])
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y' if kind != 'hbar' else 'x', alpha=.25)
    if n > 1 or series[0].get('name'):
        ax.legend(frameon=False, fontsize=9)
    if spec.get('source'):
        fig.text(0.01, 0.01, f"출처: {spec['source']}", fontsize=8, color='#666')
    fig.tight_layout()

    out_dir = Path(settings.MEDIA_ROOT) / 'columns'
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = f'columns/{filename_stem}.png'
    fig.savefig(out_dir / f'{filename_stem}.png')
    plt.close(fig)
    return rel


def chart_markdown(rel_path: str, spec: dict) -> str:
    """이미지 + 표 마크다운. 표는 첫 시리즈 기준(다중이면 열 추가)."""
    url = f"{settings.MEDIA_URL.rstrip('/')}/{rel_path}"
    labels = spec.get('labels') or []
    series = spec.get('series') or []
    head = '| 항목 | ' + ' | '.join(s.get('name') or '값' for s in series) + ' |'
    sep = '|' + '---|' * (len(series) + 1)
    rows = []
    for i, lab in enumerate(labels):
        vals = []
        for s in series:
            v = s['values'][i]
            vals.append(f'{v:g}' if isinstance(v, (int, float)) else str(v))
        rows.append(f'| {lab} | ' + ' | '.join(vals) + ' |')
    unit = f" (단위: {spec['unit']})" if spec.get('unit') else ''
    parts = [f"![{spec.get('title', '차트')}]({url})", '', f"**{spec.get('title', '')}**{unit}", '', head, sep, *rows]
    if spec.get('source'):
        parts += ['', f"*출처: {spec['source']}*"]
    return '\n'.join(parts)
