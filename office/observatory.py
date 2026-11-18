"""운영자 전용 작업 → 에이전트 → 호출·산출물 계층. 읽기만 하며 실행 상태를 변경하지 않아요."""
from collections import defaultdict
from datetime import timedelta
import json

from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .agents import AGENTS, INTERNAL_AGENTS
from .models import ColumnDraft, JobRequest, StageRun
from . import activity
from .observatory_reports import OUTCOME_KEYS, outcome, report

STAGES = {'brief': '기획', 'draft': '집필', 'check': '사실 검증', 'recheck': '재검증',
          'review': '편집 심사', 'critique': '독자 관점 평론', 'chart': '도판 제작',
          'revision_candidate': '수정 요청 반영', 'revision_verify': '요구별 이행 검수',
          'revision_repair': '최종 검수 지적 보완', 'revision_decision': '수정본 채택 판단',
          'precheck': '자동 점검', 'final': '최종 결과', 'fail': '작업 중단', 'research': '자료 조사'}
GROUPS = [('기획·집필', ('lead', 'hrd', 'data', 'coding', 'research')),
          ('검증·도판', ('checker', 'critic', 'charter')), ('편집·판정', ('editor',))]
ACTIVE = ('pending', 'started', 'quarantined')


def _detail(value):
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text[:24000]+('\n\n(긴 산출물은 앞 24,000자까지 표시해요.)' if len(text) > 24000 else '')


def _call_state(call, meta, job, now):
    state = call.get('state', 'unknown')
    if state != 'running':
        return state
    started = parse_datetime(call.get('started_at', ''))
    valid_job = (job and job.status == 'started' and job.lease_until and job.lease_until > now
                 and (not meta.get('execution_id') or str(job.execution_id) == meta['execution_id']))
    recent_manual = (not meta.get('job_id') and started and timezone.is_aware(started)
                     and timedelta(0) <= now-started < timedelta(minutes=21))
    return 'running' if valid_job or recent_manual else 'unknown'


def snapshot():
    now = timezone.now()
    live = activity.recent()
    job_query = JobRequest.objects.select_related('draft').defer('args', 'draft__content', 'draft__check_report')
    jobs = list(job_query.filter(status__in=ACTIVE).order_by('created_at')[:50])
    jobs += list(job_query.exclude(status__in=ACTIVE).order_by('-created_at')[:8])
    by_job = {str(j.pk): j for j in jobs}
    run_ids = {str(r['run_id']) for r in StageRun.objects.values('run_id').annotate(last=Max('created_at'))
               .order_by('-last')[:12]}
    run_ids.update(p['run_id'] for p in live)
    run_ids.update(str(j.checkpoint_run_id) for j in jobs if j.checkpoint_run_id)
    rows = list(StageRun.objects.filter(run_id__in=run_ids).only(
                    'id', 'run_id', 'draft_id', 'seq', 'stage', 'agent', 'sender', 'recipient', 'status', 'created_at')
                .order_by('-created_at', '-pk')[:1000])
    latest = {}
    for row in rows:  # 최신 담당자별 결과만 작은 JSON 필드로 읽어요. 본문은 상세 선택 시에만 읽어요.
        latest.setdefault((str(row.run_id), row.agent), row.pk)
    verdicts = {}
    for value in StageRun.objects.filter(pk__in=latest.values()).values('pk', *('output__'+key for key in OUTCOME_KEYS)):
        verdicts[value['pk']] = {key: value['output__'+key] for key in OUTCOME_KEYS if value['output__'+key] is not None}
    draft_ids = {s.draft_id for s in rows if s.draft_id}
    draft_ids.update(p.get('metadata', {}).get('draft_id') for p in live
                     if type(p.get('metadata', {}).get('draft_id')) is int)
    drafts = {d.pk: d for d in ColumnDraft.objects.filter(pk__in=draft_ids).only(
        'id', 'subject', 'status', 'qa_report', 'admin_note')}
    by_run = defaultdict(list)
    for row in reversed(rows):
        by_run[str(row.run_id)].append(row)
    payloads = {p['run_id']: p for p in live}
    for run_id in by_run:
        payloads.setdefault(run_id, {'run_id': run_id, 'metadata': {}, 'calls': []})
    works, linked = [], set()
    for run_id, payload in payloads.items():
        meta = payload.get('metadata') or {}
        stages = by_run.get(run_id, [])
        job = by_job.get(str(meta.get('job_id')))
        if job is None:
            job = next((j for j in jobs if str(j.checkpoint_run_id) == run_id), None)
        if job and meta.get('execution_id') and str(job.execution_id) != meta['execution_id']:
            job = None   # 재시작 전 호출을 현재 실행에 연결하지 않아요.
        draft = (drafts.get(meta.get('draft_id'))
                 or next((drafts.get(s.draft_id) for s in stages if s.draft_id), None)
                 or (job.draft if job else None))
        if job:
            linked.add(job.pk)
        call_rows = []
        for call in payload.get('calls', [])[-120:]:
            call = dict(call)
            call['state'] = _call_state(call, meta, job, now)
            call_rows.append({'id': 'call-'+str(call.get('id')), 'agent': call.get('agent', ''),
                'stage': call.get('stage', ''),
                'label': STAGES.get(call.get('stage'), call.get('stage') or '에이전트 작업'),
                'state': call.get('state', 'unknown'), 'at': call.get('started_at'),
                'ended_at': call.get('ended_at'), 'model': call.get('model', ''),
                'detail': (call.get('result') or '응답을 기다려요. 완료되면 내용을 표시해요.')[:240]})
        for row in stages:
            execution = {'ok': 'done', 'failed': 'failed', 'skipped': 'skipped'}.get(row.status, 'unknown')
            call_rows.append({'id': 'stage-'+str(row.pk), 'agent': row.agent or 'lead',
                'stage': row.stage,
                'label': STAGES.get(row.stage, row.stage),
                'state': execution,
                'outcome': outcome(row.stage, verdicts[row.pk], execution) if row.pk in verdicts else None,
                'at': row.created_at.isoformat(), 'ended_at': row.created_at.isoformat(), 'model': '',
                'detail': '선택하면 저장된 산출물 내용을 확인할 수 있어요.',
                'sender': row.sender, 'recipient': row.recipient,
                'transfer': f'{row.sender} → {row.recipient}' if row.recipient else ''})
        state = (job.status if job else 'started' if any(c['state'] == 'running' for c in call_rows)
                 else 'unknown' if any(c['state'] == 'unknown' for c in call_rows) else 'completed')
        revision = (draft.qa_report or {}).get('admin_revision') if draft else None
        if revision and revision.get('run_id') != run_id:
            revision = None
        works.append({'id': run_id, 'job_id': job.pk if job else None,
            'title': (draft.subject if draft else '') or (job.label if job else '') or '연구실 작업',
            'state': state, 'state_label': dict(JobRequest.ST_CHOICES).get(state, '종료 확인 필요'),
            'draft_status': draft.get_status_display() if draft else '',
            'score': draft.qa_score if draft else None,
            'at': payload.get('updated_at') or (stages[-1].created_at.isoformat() if stages else ''),
            'note': draft.admin_note if draft else '', 'budget': payload.get('budget'),
            'revision': {'status': revision.get('status'), 'items': revision.get('items', []),
                         'reasons': revision.get('reasons', []), 'previous_score': revision.get('previous_score'),
                         'candidate_score': revision.get('candidate_score')} if revision else None,
            'audit_url': reverse('office:audit_view', args=[draft.pk]) if draft else '',
            'calls': sorted(call_rows, key=lambda c: c.get('at') or '')})
    for job in jobs:
        if job.pk not in linked:
            works.append({'id': 'job-'+str(job.pk), 'job_id': job.pk,
                'title': (job.draft.subject if job.draft else '') or job.label or '연구실 작업',
                'state': job.status, 'state_label': job.get_status_display(),
                'draft_status': job.draft.get_status_display() if job.draft else '',
                'at': job.created_at.isoformat(), 'calls': [], 'note': job.note,
                'run_after': job.run_after.isoformat(), 'audit_url': '', 'revision': None})
    priority = {'started': 3, 'quarantined': 2, 'pending': 1}
    works.sort(key=lambda w: (priority.get(w['state'], 0), w['at']), reverse=True)
    roster = {k: {'name': a['name'], 'title': a['title']} for k, a in {**AGENTS, **INTERNAL_AGENTS}.items()}
    return {'now': now.isoformat(), 'works': works[:40], 'agents': roster,
            'groups': [{'label': label, 'agents': keys} for label, keys in GROUPS]}


def detail(run_id, item_id):
    """완료 내용은 선택할 때만 읽어 폴링 응답을 작게 유지해요."""
    import uuid
    from django.http import Http404
    try:
        run_id = str(uuid.UUID(run_id))
        if item_id.startswith('stage-'):
            row = StageRun.objects.only('output', 'stage', 'status', 'error', 'seq').get(run_id=run_id, pk=int(item_id[6:]))
            execution = {'ok': 'done', 'failed': 'failed', 'skipped': 'skipped'}.get(row.status, 'unknown')
            value = row.output
            if row.stage == 'final' and isinstance(value, dict) and value.get('review_digest'):
                review = StageRun.objects.filter(run_id=run_id, stage='review', seq__lt=row.seq, status='ok').only('output').order_by('-seq').first()
                if review and isinstance(review.output, dict):
                    from .audit import fingerprint
                    from .evidence_bundle import report_payload
                    if fingerprint(report_payload(review.output)) == value['review_digest']:
                        value = {**review.output, **value}
            return {'text': _detail(row.output), 'report': report(row.stage, value, execution, error=row.error)}
        if item_id.startswith('call-'):
            path = activity.root()/(run_id+'.json')
            if path.is_symlink():
                raise ValueError
            payload = json.loads(path.read_text(encoding='utf-8'))
            row = next(c for c in payload['calls'] if c['id'] == item_id[5:])
            meta = payload.get('metadata') or {}
            job_id = str(meta.get('job_id', ''))
            job = JobRequest.objects.filter(pk=job_id).first() if job_id.isdigit() else None
            state = _call_state(row, meta, job, timezone.now())
            call_id = uuid.UUID(hex=item_id[5:]).hex
            result_path = activity.root()/run_id/(call_id+'.txt')
            if result_path.exists():
                if result_path.resolve() != result_path.absolute():
                    raise ValueError
                value = result_path.read_text(encoding='utf-8')[:24000]
            else:
                value = row.get('result') or '응답을 기다려요. 완료되면 내용을 표시해요.'
            return {'text': value, 'report': report(row.get('stage', ''), value, state, canonical=False)}
    except (ValueError, OSError, StopIteration, KeyError, StageRun.DoesNotExist):
        pass
    raise Http404
