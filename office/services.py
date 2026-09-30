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
    """에이전트 1회 호출. 적응형 thinking 이 출력 예산을 다 써서 본문이 비면 예산 2배로 1회 재시도한다."""
    out = ask(prompt, system=AGENTS[key]['system'], model=MODEL, max_tokens=max_tokens).strip()
    if not out:
        out = ask(prompt, system=AGENTS[key]['system'], model=MODEL, max_tokens=max_tokens * 2).strip()
    return out


def ask_agent_json(key: str, prompt: str, *, max_tokens: int = 2000) -> dict:
    """JSON 만 답하도록 요청하고 파싱. 코드펜스·앞뒤 잡음은 걷어낸다."""
    suffix = '\n\n반드시 유효한 JSON 객체 하나만 출력하세요. 설명·코드펜스 금지.'
    raw = ask_agent(key, prompt + suffix, max_tokens=max_tokens)
    try:
        return parse_json(raw)
    except json.JSONDecodeError:
        # 적응형 thinking 이 출력 예산을 잠식해 비거나 잘린 경우 → 예산 3배로 1회 재시도
        raw = ask_agent(key, prompt + suffix, max_tokens=min(max_tokens * 3, 24000))
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
# 사이트 액센트(premium.css #4f46e5)를 기준으로 한 차분한 팔레트. 계열이 늘어도
# 채도를 낮춰 서로 싸우지 않게 하고, 눈금·격자는 거의 보이지 않을 만큼 옅게 쓴다.
PALETTE = ['#4f46e5', '#0f9d8f', '#e0923a', '#c2476b', '#5b7cba']
INK = '#1f2937'
INK_SOFT = '#6b7280'
GRID = '#e5e7eb'


def _chart_font(font_manager) -> str:
    """차트용 한글 폰트 이름. 사이트 본문과 같은 Pretendard 를 쓰고, 없으면 Noto Sans KR.

    matplotlib 은 woff2 를 못 읽으므로 static/fonts 의 TTF 를 쓴다
    (PretendardVariable.woff2 에서 400·700 인스턴스를 떠 둔 파일).
    """
    fonts = Path(settings.BASE_DIR) / 'static' / 'fonts'
    found = None
    for name in ('Pretendard-Regular.ttf', 'Pretendard-Bold.ttf', 'NotoSansKR-VariableFont_wght.ttf'):
        path = fonts / name
        if not path.exists():
            continue
        font_manager.fontManager.addfont(str(path))
        if found is None:
            found = font_manager.FontProperties(fname=str(path)).get_name()
    return found or 'sans-serif'


def effective_chart_type(requested: str, labels: list) -> str:
    """실제로 그릴 차트 종류. 세로 막대가 읽히지 않을 상황이면 가로 막대로 돌린다.

    한글 항목명은 대개 길어서 세로 막대의 x축에 나란히 두면 서로 겹친다(실제로 7개
    항목이 통째로 겹친 차트가 칼럼에 실렸다). 줄바꿈으로 감당이 안 되는 길이면
    가로 막대가 낫다 — 항목명을 줄바꿈 없이 그대로 읽을 수 있다.
    """
    if requested != 'bar':
        return requested
    longest = max((len(str(x)) for x in labels), default=0)
    if longest > 10 or (longest > 6 and len(labels) > 4):
        return 'hbar'
    return 'bar'


def audit_chart(spec: dict, content: str, chart_rel: str, caption: str = "") -> tuple:
    """차트가 쓸모 있는지 코드로 점검한다. 반환 (치명 문제[], 경고[], 검수용 설명).

    모델에게 "차트가 있다"고만 알려 주면 그림이 읽히는지·무엇을 말하는지 판단할 수 없어,
    라벨이 통째로 겹친 차트가 87점으로 통과한 적이 있다. 기계로 확인할 수 있는 것은
    여기서 확인하고, 그 결과를 검수 프롬프트에 그대로 넘긴다.

    레이아웃(겹침·잘림)은 심사가 아니라 render_chart 가 보장한다 — 항목명이 길면 가로
    막대로 돌리고 그림 크기를 늘린다. 그래서 여기서는 **내용**을 본다.
    """
    errors, warns = [], []
    labels = [str(x) for x in spec.get('labels') or []]
    series = spec.get('series') or []
    values = [v for s in series for v in (s.get('values') or [])]

    if not chart_rel:
        warns.append('차트 이미지가 없어 표만 실렸습니다')

    if len(labels) < 3:
        errors.append(f'비교 항목이 {len(labels)}개뿐 — 차트로 보여 줄 만한 비교가 아닙니다')
    elif len(labels) > 12:
        warns.append(f'항목이 {len(labels)}개로 많아 한눈에 읽기 어렵습니다 (8개 이하 권장)')

    if len(set(labels)) != len(labels):
        errors.append('항목명이 중복됩니다 — 무엇을 비교하는지 알 수 없습니다')

    if values:
        if len(set(values)) == 1:
            errors.append(f'모든 값이 {values[0]:g}으로 같습니다 — 차트가 아무것도 보여 주지 않습니다')
        nonzero = [abs(v) for v in values if v]
        if nonzero and max(nonzero) / min(nonzero) > 200:
            warns.append(f'값의 차이가 너무 큽니다({min(nonzero):g}~{max(nonzero):g}) — '
                         '작은 막대가 보이지 않으니 나누거나 로그 축을 고려하세요')

    # 본문에 없는 수치가 차트에 있으면 출처 불명 데이터다
    missing = [f'{v:g}' for v in values if f'{v:g}' not in content]
    if missing:
        errors.append(f'차트 수치 {", ".join(missing[:5])}이(가) 본문에 없습니다 — 근거 없는 값입니다')

    if not spec.get('unit'):
        warns.append('단위가 비어 있습니다')
    if not spec.get('source'):
        warns.append('출처가 비어 있습니다')
    if not (spec.get('title') or '').strip():
        warns.append('차트 제목이 비어 있습니다')
    if not (caption or '').strip():
        errors.append('캡션이 없습니다 — 도판은 무엇을 읽어야 하는지 한 문장으로 알려 줘야 합니다')
    elif len((caption or '').strip()) < 15:
        warns.append('캡션이 너무 짧아 그림을 설명하지 못합니다')

    kind = effective_chart_type(spec.get('type', 'bar'), labels)
    pairs = ', '.join(f'{lab}={v:g}' for lab, v in zip(labels, series[0].get('values', []))) if series else ''
    lines = [
        f"차트: {spec.get('title', '(제목 없음)')} · {kind} · 항목 {len(labels)}개 · "
        f"계열 {len(series)}개 · 단위 {spec.get('unit') or '없음'}",
        f"값: {pairs[:400]}",
        f"출처: {spec.get('source') or '없음'}",
    ]
    if errors:
        lines.append('자동 점검 — 치명: ' + ' / '.join(errors))
    if warns:
        lines.append('자동 점검 — 경고: ' + ' / '.join(warns))
    if not errors and not warns:
        lines.append('자동 점검: 이상 없음')
    return errors, warns, '\n'.join(lines)


def audit_style(content: str) -> tuple:
    """본문 문체가 하우스 스타일(존댓말)로 통일됐는지 검사. 반환 (평서체 문장[], 통계).

    프롬프트에 '존댓말로 일관'이라 적어 두어도 작성자가 통째로 평서체(~다)로 쓰는 일이
    실제로 있었다(2026-09-29 칼럼 전체가 평서체). 글은 멀쩡해 보이니 심사에서도 놓친다.
    문장 끝만 보면 기계로 판별할 수 있으므로 여기서 확인한다.

    인용문(>)·각주·참고 자료·표는 원문을 그대로 옮기는 자리라 검사 대상이 아니다.
    """
    import re

    skip_section = False
    sentences = []
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith('## '):
            skip_section = line.startswith('## 참고 자료')
            continue
        if skip_section or not line:
            continue
        if line.startswith(('>', '|', '[^', '---', '![', '*출처', '*단위')):
            continue
        if line.startswith('**그림 ') or line.startswith('**표 '):
            continue
        line = re.sub(r'^\s*[-*+]\s+', '', line)           # 목록 기호
        line = re.sub(r'\*\*[^*]+\*\*:', '', line)          # **핵심어**: 뒤 설명만 본다
        line = re.sub(r'\[\^\d+\]', '', line)               # 각주 표식
        for sent in re.split(r'(?<=[.!?])\s+', line):
            sent = sent.strip().rstrip('*_')
            if len(sent) > 6:
                sentences.append(sent)

    polite = plain = 0
    offenders = []
    for sent in sentences:
        tail = sent.rstrip('.!?"\'」』)')
        if tail.endswith(('니다', '세요', '해요', '지요', '까요', '나요', '군요', '데요', '시오')):
            polite += 1
        elif tail.endswith('다') or tail.endswith(('함', '임', '음')):
            plain += 1
            if len(offenders) < 8:
                offenders.append(sent[:70])

    total = polite + plain
    stats = {'polite': polite, 'plain': plain, 'total': total,
             'plain_ratio': round(plain / total, 3) if total else 0.0}
    return offenders, stats


def _wrap_label(text: str, width: int) -> str:
    """긴 축 라벨을 두 줄까지 접는다. 한글은 공백이 드물어 글자 수로 끊는다."""
    text = str(text)
    if len(text) <= width:
        return text
    cut = text.rfind(' ', 0, width + 1)
    head, tail = (text[:cut], text[cut + 1:]) if cut > width // 2 else (text[:width], text[width:])
    return f'{head}\n{tail if len(tail) <= width else tail[:width - 1] + "…"}'


def render_chart(spec: dict, filename_stem: str) -> tuple:
    """
    charter 에이전트의 spec 으로 PNG 를 만들어 media/columns/ 에 저장한다.
    spec: {type: bar|line|hbar, title, labels[], series:[{name, values[]}], unit, source}
    반환: (media 상대경로, '') 성공 / (None, 실패 사유) — 사유는 관리 화면·로그에 그대로 노출한다.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return None, 'matplotlib 미설치 (pip install -r requirements-prod.txt)'

    labels = [str(x) for x in spec.get('labels') or []]
    series = [s for s in (spec.get('series') or []) if isinstance(s, dict) and s.get('values')]
    if not labels or not series:
        return None, 'spec 에 labels 또는 series 가 없음'
    for s in series:
        try:
            s['values'] = [float(v) for v in s['values']][:len(labels)]
        except (TypeError, ValueError):
            return None, f"계열 '{s.get('name', '')}' 값에 숫자가 아닌 항목이 있음"
        if len(s['values']) != len(labels):
            return None, f"계열 '{s.get('name', '')}' 값 개수({len(s['values'])})가 labels({len(labels)})와 다름"

    plt.rcParams['font.family'] = _chart_font(font_manager)
    plt.rcParams['axes.unicode_minus'] = False

    n = len(series)
    kind = effective_chart_type(spec.get('type', 'bar'), labels)

    unit = (spec.get('unit') or '').strip()
    # 계열이 하나면 막대를 두껍게 — 얇은 막대에 여백만 넓으면 휑해 보인다.
    thick = 0.62 if n == 1 else min(0.72 / n, 0.3)
    if kind == 'hbar':
        figsize = (8.2, max(2.4, 0.52 * len(labels) + 0.8))
    elif kind == 'line':
        figsize = (8.2, 4.4)
    else:
        figsize = (max(5.6, 1.45 * len(labels) + 1.2), 4.2)
    fig, ax = plt.subplots(figsize=(figsize[0], min(figsize[1], 13)), dpi=170)

    import numpy as np

    def fmt(v):
        """값 라벨. 축을 지웠으므로 단위를 값에 붙여 읽는 사람이 헷갈리지 않게 한다."""
        return f'{v:g}{unit}' if unit and len(unit) <= 3 else f'{v:g}'

    if kind == 'line':
        for i, s in enumerate(series):
            ax.plot([_wrap_label(x, 12) for x in labels], s['values'], marker='o', markersize=5,
                    linewidth=2, color=PALETTE[i % len(PALETTE)], label=s.get('name', ''))
        ax.grid(axis='y', color=GRID, linewidth=.8)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right', 'left']].set_visible(False)
        ax.spines['bottom'].set_color(GRID)
        ax.tick_params(length=0, labelsize=10.5, colors=INK_SOFT)
        if unit:
            ax.set_ylabel(unit, fontsize=10, color=INK_SOFT)
    elif kind == 'hbar':
        y = np.arange(len(labels))
        h = thick
        for i, s in enumerate(series):
            bars = ax.barh(y + (i - (n - 1) / 2) * h, s['values'], height=h,
                           color=PALETTE[i % len(PALETTE)], label=s.get('name', ''),
                           zorder=3)
            ax.bar_label(bars, labels=[fmt(v) for v in s['values']],
                         fontsize=10.5, padding=6, color=INK, fontweight='bold')
        ax.set_yticks(y, [_wrap_label(x, 20) for x in labels])
        ax.invert_yaxis()
        ax.margins(x=0.16, y=0.12 if len(labels) > 2 else 0.3)
        # 값을 막대 옆에 직접 적었으므로 수치 축은 군더더기다 — 지운다
        ax.xaxis.set_visible(False)
        ax.spines[['top', 'right', 'bottom']].set_visible(False)
        ax.spines['left'].set_color(GRID)
        ax.spines['left'].set_bounds(y[0] - 0.5, y[-1] + 0.5)   # 축선이 여백까지 삐져나오지 않게
        ax.tick_params(axis='y', length=0, pad=10, labelsize=11, colors=INK)
    else:
        x = np.arange(len(labels))
        w = thick
        for i, s in enumerate(series):
            bars = ax.bar(x + (i - (n - 1) / 2) * w, s['values'], width=w,
                          color=PALETTE[i % len(PALETTE)], label=s.get('name', ''), zorder=3)
            ax.bar_label(bars, labels=[fmt(v) for v in s['values']],
                         fontsize=10.5, padding=5, color=INK, fontweight='bold')
        ax.set_xticks(x, [_wrap_label(v, 11) for v in labels])
        ax.margins(y=0.2)
        ax.yaxis.set_visible(False)
        ax.spines[['top', 'right', 'left']].set_visible(False)
        ax.spines['bottom'].set_color(GRID)
        ax.spines['bottom'].set_bounds(x[0] - 0.5, x[-1] + 0.5)
        ax.tick_params(axis='x', length=0, pad=8, labelsize=11, colors=INK)

    # 계열이 하나뿐이면 범례는 같은 말을 반복할 뿐이라 자리만 차지한다
    if n > 1:
        ax.legend(frameon=False, fontsize=10.5, loc='upper right',
                  bbox_to_anchor=(1, 1.08), ncol=min(n, 3), handlelength=1.1)

    # 제목·출처는 그림에 넣지 않는다. 본문 캡션 블록이 "그림 N. 제목 / 설명 / 출처" 를
    # 맡으므로, 그림 안에 또 적으면 같은 문장이 두 번 보인다(저널 도판의 관행이기도 하다).
    fig.tight_layout(pad=0.6)

    out_dir = Path(settings.MEDIA_ROOT) / 'columns'
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = f'columns/{filename_stem}.png'
    fig.savefig(out_dir / f'{filename_stem}.png', facecolor='white', bbox_inches='tight',
                pad_inches=0.22)
    plt.close(fig)
    return rel, ''


def chart_markdown(rel_path: str, spec: dict, caption: str = '', figure_no: int = 1) -> str:
    """도판 한 벌(그림 + 캡션 + 표)의 마크다운. rel_path 가 비면 표만 만든다.

    학술지 도판 형식을 따른다 — 그림 아래에 **그림 N. 제목**, 그 다음 줄에 "이 그림에서
    무엇을 읽어야 하는지" 한 문장, 마지막에 단위·출처. 제목과 출처를 그림 안에 또 넣지
    않는 이유도 같다(중복). 캡션을 여기서 함께 만들기 때문에 호출부가 따로 덧붙이지
    않으며, 예전처럼 설명이 그림 앞뒤로 두 번 들어가는 일이 없다.
    """
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

    title = (spec.get('title') or '').strip()
    label = f'그림 {figure_no}' if rel_path else f'표 {figure_no}'
    parts = []
    if rel_path:
        url = f"{settings.MEDIA_URL.rstrip('/')}/{rel_path}"
        parts += [f"![{label}. {title}]({url})", '']

    parts.append(f"**{label}. {title}**" if title else f"**{label}**")
    caption = (caption or '').strip()
    if caption:
        parts += ['', caption]

    note = []
    if spec.get('unit'):
        note.append(f"단위: {spec['unit']}")
    if spec.get('source'):
        note.append(f"출처: {spec['source']}")
    if note:
        parts += ['', f"*{'. '.join(note)}.*"]

    parts += ['', head, sep, *rows]
    return '\n'.join(parts)
