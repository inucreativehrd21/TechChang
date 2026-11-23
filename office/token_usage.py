"""칼럼별·단계별 토큰 사용량과 누수 신호 — 관리 화면 토큰 탭(/lab/admin/tokens/). 모델 호출은 없어요. (2026-11-23)

무엇을 보나:
- 칼럼(원고)마다 단계 묶음(팩트체크·집필·심사·기획·도판·제목·판 비교)별 입력·출력 토큰과 호출 수.
- 팩트체크를 따로 자세히 — 호출 수, 웹 검색·열람 횟수, 도구를 돈 횟수(turns), 본문 1,000자당 토큰, 최근 칼럼 중앙값 대비 배수.
- 누수 신호: ① 프롬프트보다 입력이 훨씬 큰 호출(웹 열람 결과가 맥락을 불림) ② 같은 본문을 한 실행에서 다시 검증
  ③ 한 실행의 팩트체크 호출이 너무 많음 ④ 중앙값보다 크게 많은 팩트체크 ⑤ 측정이 빠진 호출.
- 채택되지 않은 재작성(기존 원고 유지)과 실패·건너뜀 단계에 쓴 토큰은 '낭비 후보'로 따로 보여 줘요.

한계(화면에도 표시): 토큰은 제공자(CLI) 기록 기준이고 구독 한도 차감량·금액이 아니에요. Claude 캐시 읽기·쓰기는 입력에
더해 보여 주고, Codex 캐시는 입력에 이미 포함될 수 있어 다시 더하지 않아요. 호출 기록이 없는 과거 실행은 0으로 보지 않아요.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import median

GROUPS = (('fact', '팩트체크'), ('write', '집필·재작성'), ('review', '심사·평론'), ('plan', '기획·설계'),
          ('visual', '도판'), ('title', '제목 점검'), ('compare', '판 비교'), ('other', '기타'))
GROUP_LABEL = dict(GROUPS)
STAGE_GROUP = {
    'check': 'fact', 'recheck': 'fact', 'reverify': 'fact', 'code_run': 'fact', 'grounded': 'fact',
    'draft': 'write', 'fix': 'write', 'revise': 'write', 'editor_patch': 'write', 'editor_patch_claims': 'write',
    'editor_revise': 'write', 'revision_candidate': 'write', 'revision_repair': 'write', 'lock': 'write',
    'review': 'review', 'critique': 'review', 'revision_verify': 'review', 'adjudicate': 'review', 'audit': 'review',
    'brief': 'plan', 'blueprint': 'plan',
    'chart': 'visual', 'chart_plan': 'visual',
    'title_lab': 'title', 'pairwise': 'compare', 'best_version': 'compare',
}

# 누수 판정 기준 — 운영 표본이 쌓이면 조정해요
EST_TOKENS_PER_CHAR = 0.8           # 한국어 위주 프롬프트의 대략적인 토큰/글자(넉넉하게 잡아 오탐을 줄여요)
BLOAT_MIN_EXTRA = 40_000            # 프롬프트 추정치를 이만큼 넘고
BLOAT_RATIO = 2.5                   # 추정치의 이 배수를 넘으면 '도구 결과로 불어남'
MAX_FACT_CALLS_PER_RUN = 5
OUTLIER_RATIO = 2.0                 # 1,000자당 팩트체크 토큰이 중앙값의 이 배수를 넘으면 표시
MIN_SAMPLE_FOR_MEDIAN = 5

LIMITS = ['토큰은 제공자(CLI) 기록 기준이며 구독 한도 차감량이나 금액이 아니에요.',
          'Claude 캐시 읽기·쓰기는 입력에 더해 보여 줘요. Codex 캐시는 입력에 포함될 수 있어 다시 더하지 않아요.',
          '호출 기록이 없는 과거 실행·측정이 빠진 호출은 0토큰으로 보지 않고 따로 세요.',
          '누수 신호는 확인할 곳을 가리키는 표시예요. 원인 판정은 단계 상세의 호출 기록을 보고 해요.']


# ───────────────────────────── 호출 하나
def call_tokens(call: dict) -> dict:
    """호출 기록 → {in, fresh, cache, out, measured, web, turns, prompt_chars}."""
    fresh = call.get('input_tokens')
    measured = isinstance(fresh, int)
    fresh = fresh if measured else 0
    codex = call.get('backend') == 'codex_cli'
    cache_read = call.get('cache_read_input_tokens') if not codex else call.get('cached_input_tokens')
    cache_write = call.get('cache_creation_input_tokens') if not codex else 0
    cache = (cache_read or 0) + (cache_write or 0)
    total = fresh if codex else fresh + cache
    web = sum(int(call.get(k) or 0) for k in ('web_search_requests', 'web_fetch_requests', 'web_search_calls'))
    out = call.get('output_tokens')
    return {'in': total, 'fresh': fresh, 'cache': cache, 'out': out if isinstance(out, int) else 0, 'measured': measured,
            'web': web, 'turns': int(call.get('num_turns') or 0), 'prompt_chars': call.get('prompt_chars')}


def bloated(t: dict) -> bool:
    """보낸 프롬프트보다 입력이 훨씬 큰 호출 — 도구(웹 열람) 결과가 여러 차례 맥락에 쌓인 경우."""
    chars = t.get('prompt_chars')
    if not isinstance(chars, int) or not t['measured']:
        return False
    est = chars * EST_TOKENS_PER_CHAR
    return t['in'] - est > BLOAT_MIN_EXTRA and t['in'] > est * BLOAT_RATIO


def group_of(stage: str, call: dict) -> str:
    tag = (call.get('tags') or {}).get('stage') or ''
    return STAGE_GROUP.get(tag) or STAGE_GROUP.get(stage) or 'other'


# ───────────────────────────── 원고 하나
def _empty_bucket():
    return {'in': 0, 'out': 0, 'calls': 0, 'unmeasured': 0, 'web': 0, 'turns': 0}


def summarize_draft(rows: list[dict], *, body_chars: int = 0) -> dict:
    """한 원고의 StageRun 행들(run_id·stage·status·calls·decision_status) → 묶음별 합계와 누수 신호."""
    groups = defaultdict(_empty_bucket)
    stages = defaultdict(_empty_bucket)
    runs = defaultdict(lambda: {'fact_calls': 0, 'hashes': defaultdict(int), 'in': 0, 'failed': 0, 'retained': False})
    bloat_calls, unmeasured = [], 0
    for row in rows:
        run = runs[str(row['run_id'])]
        if row.get('decision_status') == 'retained':
            run['retained'] = True
        for call in row.get('calls') or []:
            if not isinstance(call, dict):
                continue
            t = call_tokens(call)
            g = group_of(row['stage'], call)
            for bucket in (groups[g], stages[row['stage']]):
                bucket['in'] += t['in']
                bucket['out'] += t['out']
                bucket['calls'] += 1
                bucket['web'] += t['web']
                bucket['turns'] += t['turns']
                bucket['unmeasured'] += 0 if t['measured'] else 1
            run['in'] += t['in'] + t['out']
            if not t['measured']:
                unmeasured += 1
            if row.get('status') in ('failed', 'skipped'):
                run['failed'] += t['in'] + t['out']
            if g == 'fact':
                run['fact_calls'] += 1
                body = (call.get('tags') or {}).get('body_hash')
                if body:
                    run['hashes'][body] += 1
            if bloated(t):
                bloat_calls.append({'stage': row['stage'], 'in': t['in'], 'prompt_chars': t['prompt_chars'],
                                    'web': t['web'], 'turns': t['turns'], 'group': GROUP_LABEL[g]})
    retained_tokens = sum(r['in'] for r in runs.values() if r['retained'])
    wasted = sum(r['failed'] for r in runs.values() if not r['retained'])   # 유지된 실행은 retained_tokens 로만 세요
    repeats = sum(n - 1 for r in runs.values() for n in r['hashes'].values() if n > 1)
    busiest = max((r['fact_calls'] for r in runs.values()), default=0)
    total_in = sum(b['in'] for b in groups.values())
    total_out = sum(b['out'] for b in groups.values())
    fact = groups.get('fact', _empty_bucket())
    flags = []
    if bloat_calls:
        top = max(bloat_calls, key=lambda c: c['in'])
        flags.append({'kind': 'bloat', 'label': '도구 결과로 불어난 호출',
                      'text': f"{len(bloat_calls)}회 — 최대 {top['in']:,}토큰({top['group']}, 프롬프트 {top['prompt_chars']:,}자, "
                              f"웹 {top['web']}회·도구 {top['turns']}턴). 웹 열람 결과가 맥락에 쌓였는지 확인해요."})
    if repeats:
        flags.append({'kind': 'repeat', 'label': '같은 본문 재검증',
                      'text': f'한 실행 안에서 바뀌지 않은 본문을 {repeats}번 더 팩트체크했어요.'})
    if busiest > MAX_FACT_CALLS_PER_RUN:
        flags.append({'kind': 'many', 'label': '팩트체크 호출 과다',
                      'text': f'한 실행에서 팩트체크를 {busiest}번 불렀어요(기준 {MAX_FACT_CALLS_PER_RUN}번).'})
    if unmeasured:
        flags.append({'kind': 'unmeasured', 'label': '측정 누락',
                      'text': f'토큰 기록이 없는 호출 {unmeasured}회 — 합계보다 실제 사용량이 커요.'})
    return {'groups': {k: dict(v) for k, v in groups.items()}, 'stages': {k: dict(v) for k, v in stages.items()},
            'total_in': total_in, 'total_out': total_out, 'runs': len(runs), 'calls': sum(b['calls'] for b in groups.values()),
            'fact': {**dict(fact), 'per_1k': round(fact['in'] / body_chars * 1000) if body_chars and fact['in'] else None,
                     'share': round(fact['in'] / total_in * 100, 1) if total_in else None,
                     'max_calls_per_run': busiest, 'repeats': repeats},
            'bloat_calls': bloat_calls, 'wasted': wasted, 'retained_tokens': retained_tokens,
            'unmeasured': unmeasured, 'flags': flags}


# ───────────────────────────── 최근 칼럼 전체
def overview(*, days: int = 30, limit: int = 40) -> dict:
    from django.utils import timezone
    from .models import ColumnDraft, StageRun
    since = timezone.now() - timedelta(days=days)
    draft_ids = list(StageRun.objects.filter(created_at__gte=since, draft__isnull=False)
                     .order_by('-created_at').values_list('draft_id', flat=True).distinct()[:limit * 4])
    draft_ids = list(dict.fromkeys(draft_ids))[:limit]
    drafts = {d.pk: d for d in ColumnDraft.objects.filter(pk__in=draft_ids).only(
        'id', 'subject', 'brief', 'status', 'topic', 'column_track', 'series_key', 'episode_number', 'content', 'created_at')}
    rows = _rows_for(draft_ids, since=since)
    columns = []
    for pk in draft_ids:
        d = drafts.get(pk)
        if d is None:
            continue
        s = summarize_draft(rows[pk], body_chars=len(d.content or ''))
        columns.append({'draft': d, 'chars': len(d.content or ''), **s})
    _mark_outliers(columns)
    totals = defaultdict(_empty_bucket)
    for c in columns:
        for key, b in c['groups'].items():
            for k in ('in', 'out', 'calls', 'web', 'turns', 'unmeasured'):
                totals[key][k] += b[k]
    total_in = sum(b['in'] for b in totals.values())
    group_rows = [{'key': key, 'label': label, **totals.get(key, _empty_bucket()),
                   'share': round(totals[key]['in'] / total_in * 100, 1) if total_in and key in totals else 0}
                  for key, label in GROUPS if key in totals]
    fact_per_draft = [c['fact']['in'] for c in columns if c['fact']['in']]
    return {'days': days, 'columns': columns, 'groups': group_rows, 'total_in': total_in,
            'total_out': sum(b['out'] for b in totals.values()), 'calls': sum(b['calls'] for b in totals.values()),
            'fact_in': totals['fact']['in'] if 'fact' in totals else 0,
            'fact_share': round(totals['fact']['in'] / total_in * 100, 1) if total_in and 'fact' in totals else None,
            'median_fact': round(median(fact_per_draft)) if fact_per_draft else None,
            'median_fact_per_1k': _median_per_1k(columns),
            'flagged': sum(bool(c['flags']) for c in columns),
            'wasted': sum(c['wasted'] + c['retained_tokens'] for c in columns),
            'unmeasured': sum(c['unmeasured'] for c in columns), 'limits': LIMITS}


def _median_per_1k(columns) -> int | None:
    values = [c['fact']['per_1k'] for c in columns if c['fact'].get('per_1k')]
    return round(median(values)) if len(values) >= MIN_SAMPLE_FOR_MEDIAN else None


def _mark_outliers(columns) -> None:
    base = _median_per_1k(columns)
    for c in columns:
        per = c['fact'].get('per_1k')
        c['fact']['vs_median'] = round(per / base, 1) if base and per else None
        if base and per and per > base * OUTLIER_RATIO:
            c['flags'].append({'kind': 'outlier', 'label': '팩트체크 과다(중앙값 대비)',
                               'text': f'본문 1,000자당 {per:,}토큰 — 최근 칼럼 중앙값 {base:,}의 {per / base:.1f}배예요.'})


def detail(draft_id: int) -> dict:
    """한 원고의 실행별·단계별 호출 목록 — 누수 신호를 눌렀을 때 보는 화면."""
    from .models import ColumnDraft, StageRun
    draft = ColumnDraft.objects.filter(pk=draft_id).first()
    if draft is None:
        return {}
    runs = defaultdict(list)
    for row in StageRun.objects.filter(draft_id=draft_id).order_by('pk').values(
            'run_id', 'seq', 'stage', 'status', 'calls', 'created_at'):
        calls = []
        for call in row['calls'] or []:
            if isinstance(call, dict):
                t = call_tokens(call)
                calls.append({**t, 'model': call.get('model', ''), 'backend': call.get('backend', ''),
                              'seconds': call.get('seconds'), 'group': GROUP_LABEL[group_of(row['stage'], call)],
                              'tag': (call.get('tags') or {}).get('stage', ''), 'bloated': bloated(t),
                              'error': (call.get('error') or '')[:120]})
        if calls or row['status'] != 'ok':
            runs[str(row['run_id'])].append({**row, 'calls': calls,
                                             'in': sum(c['in'] for c in calls), 'out': sum(c['out'] for c in calls)})
    ordered = sorted(runs.items(), key=lambda kv: kv[1][0]['created_at'])
    return {'draft': draft, 'runs': [{'run_id': k, 'started': v[0]['created_at'], 'stages': v,
                                      'in': sum(s['in'] for s in v), 'out': sum(s['out'] for s in v)} for k, v in ordered],
            'summary': summarize_draft(_rows_for([draft_id])[draft_id], body_chars=len(draft.content or ''))}


def _rows_for(draft_ids, *, since=None) -> dict:
    """원고별 StageRun 행 — 채택되지 않은 재작성(revision_decision=retained)도 표시해요."""
    from .models import StageRun
    qs = StageRun.objects.filter(draft_id__in=draft_ids)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    rows = defaultdict(list)
    for row in qs.values('draft_id', 'run_id', 'stage', 'status', 'calls'):
        rows[row['draft_id']].append(row)
    for row in qs.filter(stage='revision_decision').values('draft_id', 'run_id', 'output'):
        status = row['output'].get('status') if isinstance(row['output'], dict) else None
        for r in rows[row['draft_id']]:
            if r['run_id'] == row['run_id'] and r['stage'] == 'revision_decision':
                r['decision_status'] = status
    return rows
