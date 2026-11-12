"""
연구실 뷰.
  공개:   /lab/            픽셀 연구실 + 최근 회의·결정·작업 로그
          /lab/state.json  캔버스가 폴링하는 상태
  관리자: /lab/admin/      회의 안건 선택 · 보류 칼럼 검수 · 작업 로그 · 수동 소집
"""
import os
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .security import operator_required as admin_required
from common.views import admin_otp_required, _admin_otp_session_ok
from . import github
from .agents import AGENTS, MEETING_ORDER, public_roster, public_roster_groups
from .models import ColumnDraft, Decision, Meeting, Task, WorkLog
from .publiclog import post_id, public_line, public_logs

TOPIC_LABEL = {'hrd': 'HRD', 'data': '데이터분석', 'coding': '프로그래밍'}


def _public_meeting(meeting):
    if meeting is None:
        return None
    from .agenda import public_item
    decisions = []
    for decision in meeting.decisions.all():
        if decision.kind not in (Decision.KIND_COLUMN, Decision.KIND_SERIES) or not decision.chosen_key:
            continue
        item = public_item(decision)
        if item:
            decisions.append(item)
    return {
        'id': meeting.id, 'week_start': meeting.week_start.isoformat(), 'held_at': meeting.held_at.isoformat(),
        'summary': meeting.public_summary,
        'transcript': ([{'agent': 'lead', 'name': AGENTS['lead']['name'], 'round': 1,
                         'text': meeting.public_summary}] if meeting.public_summary else []),
        'decisions': decisions,
    }


def decorate_logs(qs):
    out = []
    for l in qs:
        a = AGENTS.get(l.agent)
        if not a:
            continue
        l.agent_name, l.agent_color = a['name'], a['sprite']['shirt']
        out.append(l)
    return out


def _public_log_rows(limit: int = 20) -> list:
    """공개 연구실에 내보낼 활동 로그. 원문 대신 publiclog 가 다듬은 문장을 쓴다."""
    rows = []
    qs = WorkLog.objects.select_related('draft').order_by('-created_at')[:120]
    for log, label, line in public_logs(qs, limit=limit):
        a = AGENTS.get(log.agent)
        if not a:
            continue
        pid = post_id(log)
        rows.append({'agent': log.agent, 'agent_name': a['name'], 'agent_color': a['sprite']['shirt'],
                     'action': log.action, 'label': label, 'text': line, 'created_at': log.created_at,
                     'url': reverse('community:detail', args=[pid]) if pid else ''})
    return rows


def _agent_status():
    """에이전트별 최근 '공개 가능한' 활동 1건 → 상태 말풍선.

    말풍선도 로그 원문을 그대로 쓰면 운영자 지시문·정비 내역이 캔버스에 뜬다.
    publiclog 를 통과한 문장만 쓴다.
    """
    latest = {}
    for wl in WorkLog.objects.select_related('draft').order_by('-created_at')[:300]:
        if wl.agent in AGENTS and wl.agent not in latest:
            line = public_line(wl)
            if line:
                latest[wl.agent] = (wl, line)
        if len(latest) == len(AGENTS):
            break
    now = timezone.now()
    result = []
    for a in public_roster():
        found = latest.get(a['key'])
        status = {'action': 'idle', 'text': '', 'age_min': None}
        if found:
            wl, line = found
            status = {'action': wl.action, 'text': line,
                      'age_min': int((now - wl.created_at).total_seconds() // 60)}
        result.append({**a, 'status': status})
    return result


def _lab_assets_url():
    """media/lab/manifest.json 이 있으면 그 URL — 캔버스가 타일 모드로 전환된다. 없으면 ''."""
    path = os.path.join(settings.MEDIA_ROOT, 'lab', 'manifest.json')
    if not os.path.exists(path):
        return ''
    ver = int(os.path.getmtime(path))
    return f"{settings.MEDIA_URL.rstrip('/')}/lab/manifest.json?v={ver}"


@never_cache
def making(request, question_id):
    """발행 칼럼의 제작·심사 기록 — 운영진에게만 공개."""
    from .security import is_operator
    if not is_operator(request.user):
        from django.http import Http404
        raise Http404
    from .making import build_making
    draft = get_object_or_404(ColumnDraft.objects.select_related('question', 'decision__meeting'),
                              question_id=question_id, question__is_deleted=False,
                              status=ColumnDraft.STATUS_PUBLISHED)
    data = build_making(draft)
    if data is None:
        from django.http import Http404
        raise Http404
    response = render(request, 'office/making.html', {'mk': data, 'question': draft.question})
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


def office_home(request):
    meeting = Meeting.objects.prefetch_related('decisions').first()
    recent_drafts = list(ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED, question__isnull=False)
                         .select_related('question')[:6])
    # 공개 페이지에는 '무엇을 쓰기로 했는지'만 보여 준다. 사이트 개선·운영 안건은
    # 독자의 관심사가 아니고, 탈락 선택지와 그 사유는 내부 판단이라 내보내지 않는다.
    decisions = []
    if meeting:
        from .agenda import public_item
        for d in meeting.decisions.all():
            if d.kind not in (Decision.KIND_COLUMN, Decision.KIND_SERIES) or not d.chosen_key:
                continue
            # 선택지 제목은 '기존 칼럼 /123/ 보강: …' 같은 내부 기획 문장이라 독자가 읽을 형태로 바꾼다(office.agenda)
            item = public_item(d)
            if item:
                item['topic_name'] = '연재' if d.kind == Decision.KIND_SERIES else TOPIC_LABEL.get(d.topic, '')
                decisions.append(item)
    for d in recent_drafts:
        d.topic_name = TOPIC_LABEL.get(d.topic, '')
    return render(request, 'office/office.html', {
        'roster_groups': public_roster_groups(),
        'roster': public_roster(),
        'agent_count': len(AGENTS),
        'meeting': meeting,
        'public_decisions': decisions,
        'recent_drafts': recent_drafts,
        'logs': _public_log_rows(limit=20),
        'assets_url': _lab_assets_url(),
        'media_url': settings.MEDIA_URL.rstrip('/') + '/lab/',
    })


def office_live(request):
    """'칼럼이 만들어지는 과정' 라이브 표시용 — 파일 하나와 회의 한 건만 읽는 가벼운 응답 (office.live)."""
    from . import live
    res = JsonResponse(live.snapshot())
    res['Cache-Control'] = 'no-store'
    return res


def office_state(request):
    meeting = Meeting.objects.prefetch_related('decisions').first()
    return JsonResponse({
        'now': timezone.localtime().isoformat(),
        'agents': _agent_status(),
        'meeting': _public_meeting(meeting),
        'recent_logs': [{'agent': r['agent'], 'name': r['agent_name'], 'action': r['action'],
                         'label': r['label'], 'text': r['text'],
                         'at': timezone.localtime(r['created_at']).strftime('%m-%d %H:%M')}
                        for r in _public_log_rows(limit=20)],
    })


# ───────────────────────────── 관리자
@admin_required
def office_admin(request, *, decision_payload=None, decision_errors=None, decision_meeting_id=None, response_status=200):
    from common.models import LogFinding

    meetings = list(Meeting.objects.prefetch_related('decisions').order_by('-held_at')[:8])
    if decision_meeting_id and (not meetings or meetings[0].pk != decision_meeting_id):
        selected = get_object_or_404(Meeting.objects.prefetch_related('decisions'), pk=decision_meeting_id)
        meetings = [selected] + [m for m in meetings if m.pk != selected.pk]
    held = ColumnDraft.objects.filter(
        status__in=[ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_REVISING]).select_related('decision')
    ready = list(ColumnDraft.objects.filter(status=ColumnDraft.STATUS_READY).order_by('publish_at'))
    from .models import JobRequest
    jobs = list(JobRequest.objects.select_related('draft').order_by('-created_at')[:30])
    recent_drafts = ColumnDraft.objects.exclude(
        status__in=[ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_REVISING, ColumnDraft.STATUS_READY]
    ).select_related('question')[:12]
    logs = decorate_logs(WorkLog.objects.select_related('draft', 'meeting')[:80])
    from .audit import snapshot, fingerprint
    for d in list(held) + list(recent_drafts) + ready:
        d.topic_name = TOPIC_LABEL.get(d.topic, '')
        if d.status in (ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_READY):
            d.approval_version = fingerprint(snapshot(d))
    for m in meetings:
        for d in m.decisions.all():
            d.topic_name = TOPIC_LABEL.get(d.topic, '')
            if m == meetings[0]:
                from .decision_review import decorate
                decorate(d, decision_payload if m.pk == decision_meeting_id else None,
                         (decision_errors or {}).get(d.pk, ''))
        # 회의록 탭용: 발언에 이름·색 부여
        m.turns = [
            {'name': AGENTS[t['agent']]['name'], 'title': AGENTS[t['agent']]['title'],
             'color': AGENTS[t['agent']]['sprite']['shirt'], 'round': t.get('round', 1), 'text': t['text']}
            for t in m.transcript if t.get('agent') in AGENTS
        ]
    tasks = list(Task.objects.exclude(status__in=[Task.ST_DONE, Task.ST_REJECTED])
                 .select_related('decision', 'finding')[:30])
    pending_findings = list(LogFinding.objects.filter(status=LogFinding.STATUS_PENDING))
    recent_findings = list(LogFinding.objects.exclude(status=LogFinding.STATUS_PENDING)
                           .prefetch_related('tasks')[:10])
    crew_pending = sum(1 for t in tasks if t.status == Task.ST_BACKLOG) + len(pending_findings)
    done_tasks = list(Task.objects.filter(status__in=[Task.ST_DONE, Task.ST_REJECTED, Task.ST_PR])
                      .select_related('decision')[:10])
    job_log = _job_log_tail() if _admin_otp_session_ok(request) else '원본 작업 로그는 관리자 재인증 후 확인할 수 있어요.'
    from . import switches as SW
    open_meeting = next((m for m in meetings if m.status == Meeting.STATUS_OPEN), None)
    revising = [d for d in held if d.status == ColumnDraft.STATUS_REVISING]
    status = [   # 위쪽 상태 줄 — 누르면 해당 탭으로
        {'tab': 'decisions', 'label': '결정 대기 안건', 'n': open_meeting.pending_count if open_meeting else 0},
        {'tab': 'drafts', 'label': '검수 대기 원고', 'n': len(held) - len(revising),
         'note': f'재작성 중 {len(revising)}' if revising else ''},
        {'tab': 'drafts', 'label': '공개 대기', 'n': len(ready),
         'note': f'다음 {timezone.localtime(ready[0].publish_at):%m/%d %H:%M}' if ready and ready[0].publish_at else ''},
        {'tab': 'crew', 'label': '정비·지적사항', 'n': crew_pending},
    ]
    return render(request, 'office/admin.html', {
        'status': status, 'switch_groups': SW.panel(), 'switch_summary': SW.summary(),
        'meetings': meetings, 'held': held, 'ready': ready, 'jobs': jobs, 'recent_drafts': recent_drafts, 'logs': logs,
        'tasks': tasks, 'done_tasks': done_tasks, 'github_ok': github.available(),
        'pending_findings': pending_findings, 'recent_findings': recent_findings,
        'crew_pending': crew_pending,
        'agents': AGENTS, 'topic_label': TOPIC_LABEL, 'job_log': job_log,
        'manual_jobs_available': (os.environ.get('CLAUDE_BACKEND', 'api').lower() == 'cli'
                                  or (bool(getattr(settings, 'ANTHROPIC_API_KEY', ''))
                                      and os.environ.get('AI_ALLOW_PAID_API', 'false').lower() == 'true')),
    }, status=response_status)


@admin_required
@require_POST
def switch_set(request, key):
    """설정 탭 — 기능 스위치 하나를 바꾸거나 기본값으로 되돌린다(office.switches)."""
    from django.http import Http404

    from . import switches as SW
    spec = SW.BY_KEY.get(key)
    if spec is None:
        raise Http404
    try:
        if request.POST.get('reset'):
            SW.reset(key)
            messages.success(request, f'{spec.label}: 기본값({SW.value_label(spec, spec.default)})으로 되돌렸어요.')
        else:
            raw = request.POST.get('value', '')
            if spec.kind == 'bool' and raw not in ('on', 'off'):
                raw = 'on' if request.POST.get('enabled') else 'off'
            value = SW.set_value(key, raw, request.user)
            messages.success(request, f'{spec.label}: {SW.value_label(spec, value)}(으)로 바꿨어요. 다음 제작부터 적용돼요.')
    except ValueError as exc:
        messages.error(request, f'{spec.label}: {exc}')
    return redirect(reverse('office:admin') + '#settings')


@admin_required
@require_POST
def decision_choose(request, decision_id):
    """이전 개별 저장 주소도 같은 검증·잠금 규칙을 사용해요."""
    d = get_object_or_404(Decision, pk=decision_id)
    from django.http import QueryDict
    from .decision_review import decorate
    payload = QueryDict(mutable=True)
    for item in d.meeting.decisions.all():
        decorate(item)
        payload.appendlist('decision_ids', str(item.pk))
        payload[f'version_{item.pk}'] = item.review_token
    payload[f'choice_{d.pk}'] = request.POST.get('key', '')
    payload[f'note_{d.pk}'] = request.POST.get('note', d.note)
    return _save_meeting_decisions(request, d.meeting_id, payload)


@admin_required
@require_POST
def meeting_decisions_save(request, meeting_id):
    get_object_or_404(Meeting, pk=meeting_id)
    return _save_meeting_decisions(request, meeting_id, request.POST)


def _save_meeting_decisions(request, meeting_id, payload):
    from .decision_review import save_review, ReviewError
    try:
        result = save_review(meeting_id, payload, request.user)
    except ReviewError as exc:
        messages.error(request, str(exc))
        return office_admin(request, decision_payload=payload, decision_errors=exc.errors,
                            decision_meeting_id=meeting_id, response_status=409)
    if result['polish']:
        # 전체 저장 트랜잭션이 끝난 뒤에 한 번만 후속 요약을 예약해요.
        _spawn(request, ['polish_meeting', '--meeting', str(meeting_id)])
    messages.success(request, f"선택·의견 {result['changed']}개 안건을 저장했어요. 미결정 {result['pending']}개예요.")
    return redirect(reverse('office:admin') + '#decisions')


@admin_required
@require_POST
def draft_publish(request, draft_id):
    from .approval import approve, valid
    from . import schedule as S
    draft = get_object_or_404(ColumnDraft, pk=draft_id, status__in=[ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_READY])
    mode = request.POST.get('mode', 'normal')
    if mode == 'exception' and not _admin_otp_session_ok(request):
        request.session['admin_otp_next'] = reverse('office:admin') + '#drafts'
        return redirect('common:admin_otp')
    try:
        from .audit import snapshot, fingerprint
        version = request.POST.get('version')
        if not version or version != fingerprint(snapshot(draft)):
            raise ValueError('검수 화면을 연 뒤 원고나 검증 자료가 바뀌었어요. 새로고침 후 다시 확인해 주세요.')
        if not request.POST.get('now'):
            approve(draft, request.user, request.POST.get('reason', ''), mode=mode, expected_snapshot=version)
        if not valid(draft):
            raise ValueError('현재 원고를 먼저 검수하고 승인해 주세요.')
        if draft.publish_at and draft.publish_at > timezone.now() and not request.POST.get('now'):
            draft.status = ColumnDraft.STATUS_READY
            draft.save(update_fields=['status'])
            messages.success(request, '승인한 원고를 예약 공개해요.')
        else:
            S.publish_now(draft, by=request.user)
            messages.success(request, '검수한 원고를 공개했어요.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('office:admin')


@admin_required
@require_POST
def draft_reject(request, draft_id):
    draft = get_object_or_404(ColumnDraft, pk=draft_id, status=ColumnDraft.STATUS_HOLD)
    from .approval import revoke
    revoke(draft, request.user, '반려')
    draft.status, draft.decided_by, draft.decided_at = ColumnDraft.STATUS_REJECTED, request.user, timezone.now()
    draft.save(update_fields=['status', 'decided_by', 'decided_at'])
    WorkLog.objects.create(agent='lead', action='reject', draft=draft, text=f'관리자 반려: {draft.subject}')
    messages.info(request, f'반려: {draft.subject}')
    return redirect('office:admin')


def _spawn(request, args: list):
    """웹 서비스의 자식 프로세스로 만들지 않고 cron 작업 대기열에 넣는다."""
    from .jobs import enqueue
    enqueue(args, by=request.user.username, actor=request.user)


def _job_log_tail(lines: int = 60) -> str:
    p = os.path.join(settings.BASE_DIR, 'logs', 'office_jobs.log')
    if not os.path.exists(p):
        return ''
    with open(p, encoding='utf-8', errors='replace') as f:
        return ''.join(f.readlines()[-lines:])


@admin_required
@admin_otp_required
def admin_activity(request):
    """관리 화면이 폴링하는 실시간 활동 — 작업 로그 · 진행 중 작업 · 프로세스 출력."""
    since_id = request.GET.get('since')
    qs = WorkLog.objects.select_related('draft')[:60]
    logs = []
    for l in qs:
        a = AGENTS.get(l.agent)
        if not a:
            continue
        logs.append({
            'id': l.id, 'agent': l.agent, 'name': a['name'], 'color': a['sprite']['shirt'],
            'action': l.action, 'text': l.text, 'draft_id': l.draft_id,
            'at': timezone.localtime(l.created_at).strftime('%m/%d %H:%M:%S'),
        })
    running = [
        {'id': d.id, 'subject': d.subject or d.brief, 'topic': TOPIC_LABEL.get(d.topic, ''),
         'since': timezone.localtime(d.decided_at or d.created_at).strftime('%H:%M')}
        for d in ColumnDraft.objects.filter(status=ColumnDraft.STATUS_REVISING)
    ]
    running += [
        {'id': f'T{t.id}', 'subject': t.title, 'topic': '정비',
         'since': timezone.localtime(t.decided_at or t.created_at).strftime('%H:%M')}
        for t in Task.objects.filter(status=Task.ST_WORKING)
    ]
    return JsonResponse({
        'now': timezone.localtime().strftime('%H:%M:%S'),
        'logs': logs,
        'latest_id': logs[0]['id'] if logs else 0,
        'has_new': bool(logs and since_id and str(logs[0]['id']) != str(since_id)),
        'running': running,
        'job_log': _job_log_tail(),
    })


@admin_required
@require_POST
def draft_revise(request, draft_id):
    """운영자 코멘트를 반영해 다시 쓰도록 연구팀에 되돌린다 (백그라운드 실행)."""
    draft = get_object_or_404(ColumnDraft, pk=draft_id)
    from .models import JobRequest
    if JobRequest.objects.filter(draft=draft, status__in=['pending', 'started']).exists():
        messages.info(request, '이미 이 원고의 수정 작업을 기다리고 있어요.')
        return redirect('office:admin')
    note = request.POST.get('note', '').strip()
    if not note:
        messages.error(request, '수정 지시 내용을 입력하세요.')
        return redirect('office:admin')
    if draft.status not in (ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_REJECTED):
        messages.error(request, '검수 대기 중인 칼럼만 재작성할 수 있습니다.')
        return redirect('office:admin')

    from .approval import revoke
    revoke(draft, request.user, '수정 지시')
    draft.admin_note = note
    from .audit import append, snapshot
    append('revision_requested', actor_id=request.user.pk, draft_id=draft.pk,
           payload={'note': note, 'before': snapshot(draft)})
    draft.status = ColumnDraft.STATUS_HOLD
    draft.decided_by, draft.decided_at = request.user, timezone.now()
    draft.save(update_fields=['admin_note', 'status', 'decided_by', 'decided_at'])
    if draft.series_key:      # 연재 원고는 연재 기준(골격·기준표)으로 다시 검증한다
        _spawn(request, ['auto_write_series', '--revise-draft', str(draft.id), '--note', note,
                         '--by', request.user.username])
    else:
        _spawn(request, ['office_revise', '--draft', str(draft.id), '--note', note, '--by', request.user.username])
    messages.success(request, '수정 지시를 전달했습니다. 작업 로그에서 진행 상황이 실시간으로 갱신됩니다.')
    return redirect('office:admin')


@admin_required
@require_POST
def task_action(request, task_id):
    """정비 작업 카드 조작: 이슈 생성 / 승인·착수 / 반려 / 재시도"""
    t = get_object_or_404(Task, pk=task_id)
    act = request.POST.get('act', '')

    if act == 'issue':
        from office.maintenance import issue_body, step_triage
        if not t.triage:
            try:
                step_triage(t)
            except Exception as ex:  # noqa: BLE001
                messages.warning(request, f'분류 실패(이슈는 그대로 생성): {ex}')
        issue, err = github.create_issue(
            t.title, issue_body(t),
            labels=['maintenance', t.kind, t.priority])
        if issue:
            t.issue_number = issue.get('number')
            t.issue_url = issue.get('html_url', '')
            t.save(update_fields=['issue_number', 'issue_url'])
            WorkLog.objects.create(agent='coding', action='issue', text=f'GitHub 이슈 #{t.issue_number} 생성: {t.title}')
            messages.success(request, f'이슈 #{t.issue_number} 생성')
        else:
            messages.error(request, f'이슈 생성 실패: {err}')

    elif act == 'start':
        messages.error(request, '서버에서는 정비반을 실행하지 않아요. 로컬에서 처리해 주세요.')
        return redirect('office:admin')

    elif act == 'reject':
        t.status = Task.ST_REJECTED
        t.decided_by, t.decided_at = request.user, timezone.now()
        t.note = request.POST.get('note', '')[:300]
        t.save(update_fields=['status', 'decided_by', 'decided_at', 'note'])
        if t.issue_number:
            github.close_issue(t.issue_number, 'not_planned')
        messages.info(request, '반려했습니다.')

    elif act == 'done':
        t.status = Task.ST_DONE
        t.save(update_fields=['status'])
        if t.issue_number:
            github.close_issue(t.issue_number)
        messages.success(request, '완료 처리했습니다.')

    return redirect('office:admin')


@admin_required
@require_POST
def task_create(request):
    t = Task.objects.create(
        source=Task.SRC_MANUAL,
        title=request.POST.get('title', '').strip()[:300],
        body=request.POST.get('body', '').strip(),
        kind=request.POST.get('kind', Task.KIND_DEV),
    )
    if not t.title:
        t.delete()
        messages.error(request, '제목을 입력하세요.')
    else:
        messages.success(request, f'작업 #{t.id} 등록')
    return redirect('office:admin')


@admin_required
@require_POST
def run_job(request):
    """회의 소집 / 칼럼 제작을 백그라운드 프로세스로 실행 (API 호출이 수 분 걸려 요청 안에서 못 돈다)."""
    job = request.POST.get('job', '')
    if job == 'meeting':
        cmd = ['hold_meeting', '--force']
        admin_email = os.environ.get('DJANGO_ADMIN_EMAIL', '')
        if admin_email:
            cmd += ['--email', admin_email]
    elif job == 'publish' and request.POST.get('topic') in TOPIC_LABEL:
        track = request.POST.get('track', 'both')
        if track not in ('research', 'practical', 'both'):
            messages.error(request, '올바른 칼럼 유형을 골라 주세요.')
            return redirect('office:admin')
        cmd = ['office_publish', '--topic', request.POST['topic'], '--track', track]
    elif job == 'column_map':
        from .jobs import enqueue
        enqueue(['update_column_map'], by=request.user.username, dedupe=True, actor=request.user)
        messages.success(request, '칼럼 지도 갱신을 예약했습니다. 요약이 없거나 바뀐 칼럼만 다시 만들고, 몇 분 뒤 새로고침하면 반영됩니다.')
        return redirect('community:column_map')
    else:
        messages.error(request, '알 수 없는 작업입니다.')
        return redirect('office:admin')

    _spawn(request, cmd)
    messages.success(request, '작업을 예약했습니다. 다음 실행 때 작업 로그 탭에서 진행 상황을 확인할 수 있습니다.')
    return redirect('office:admin')


# ───────────────────────────── 칼럼 지도
@admin_required
def column_map(request):
    """예전 관리자 전용 주소 — 칼럼 지도는 공개 페이지(community:column_map)로 옮겼다. 요약 갱신·연구실 관리
    버튼은 그 페이지에서 관리자에게만 보인다."""
    return redirect('community:column_map')


# ───────────────────────────── 연구실 위클리(공개)
def newsletter_list(request):
    from .models import Newsletter
    issues = Newsletter.objects.filter(status=Newsletter.STATUS_PUBLISHED)
    return render(request, 'newsletter/list.html', {'issues': issues})


def newsletter_detail(request, slug):
    from .models import Newsletter
    issue = get_object_or_404(Newsletter, slug=slug, status=Newsletter.STATUS_PUBLISHED)
    newer = Newsletter.objects.filter(status=Newsletter.STATUS_PUBLISHED, issue_no__gt=issue.issue_no).order_by('issue_no').first()
    older = Newsletter.objects.filter(status=Newsletter.STATUS_PUBLISHED, issue_no__lt=issue.issue_no).order_by('-issue_no').first()
    data = issue.data or {}
    facts, copy = data.get('facts', {}), data.get('copy', {})
    cp = copy.get('picks') or {}
    picks = [{**p, **(cp.get(str(p.get('id'))) or {}), 'author': AGENTS.get(p.get('author_key'), {}).get('name', '')}
             for p in facts.get('picks') or []]
    chat = [{'name': AGENTS.get(c.get('agent'), {}).get('name', ''), 'line': c.get('line', '')}
            for c in copy.get('chat') or [] if isinstance(c, dict) and c.get('agent') in AGENTS]
    pick_ids = {p.get('id') for p in picks}
    others = [p for p in facts.get('published', []) if p.get('id') not in pick_ids]
    alts = data.get('alts') or []
    return render(request, 'newsletter/detail.html', {
        'issue': issue, 'facts': facts, 'newer': newer, 'older': older, 'picks': picks, 'chat': chat,
        'meeting_date': (facts.get('meeting') or {}).get('date', ''), 'others': others,
        'remade': sum(1 for p in others if p.get('remake')), 'other_new': sum(1 for p in others if not p.get('remake')),
        'cards': [(u, alts[i] if i < len(alts) else f'{i + 1}번째 카드') for i, u in enumerate(issue.cards)],
        'og_abs': request.build_absolute_uri(issue.og_image) if issue.og_image else '',
    })


# ───────────────────────────── 운영자 메일 버튼(재실행·재심 요청)
@admin_required
def job_request(request, token):
    """메일의 서명 링크 — GET 은 무엇을 언제 할지 보여 주고, POST 해야 예약한다(링크를 미리 여는 메일 검사기 대비)."""
    from django.core import signing

    from . import jobmail
    try:
        data = jobmail.read_token(token)
    except signing.SignatureExpired:
        return render(request, 'office/job_request.html', {'error': '링크 기한(3일)이 지났습니다. 관리 화면에서 직접 실행해 주세요.'},
                      status=410)
    except signing.BadSignature:
        return render(request, 'office/job_request.html', {'error': '올바르지 않은 링크입니다.'}, status=400)
    job, created = None, False
    if request.method == 'POST':
        job, created = jobmail.enqueue(data, actor=request.user)
    from datetime import datetime
    wanted = datetime.fromisoformat(data['r']) if data.get('r') else None
    planned = max(wanted, jobmail.earliest_run()) if wanted else jobmail.earliest_run()
    return render(request, 'office/job_request.html', {
        'data': data, 'command': ' '.join(data['a']), 'planned': planned, 'limited': jobmail.limited_until(),
        'job': job, 'created': created,
    })


@admin_required
@require_POST
def job_cancel(request, job_id):
    from .models import JobRequest
    get_object_or_404(JobRequest, pk=job_id)
    from .job_control import cancel
    cancel(job_id, request.user.pk)
    messages.info(request, '예약을 취소했습니다.')
    return redirect('office:admin')


@admin_required
@require_POST
def job_restart(request, job_id):
    from .job_control import restart
    from .models import JobRequest
    get_object_or_404(JobRequest, pk=job_id)
    try:
        new = restart(job_id, request.user.pk)
        messages.success(request, f'작업 #{new.pk}로 다시 예약했어요.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('office:admin')


@admin_required
@admin_otp_required
def audit_export(request, draft_id):
    from .models import AuditEvent
    from django.http import HttpResponse
    rows = list(AuditEvent.objects.filter(draft_id=draft_id).values())
    response = HttpResponse(json.dumps({'events': rows}, ensure_ascii=False, default=str), content_type='application/json')
    response['Cache-Control'] = 'no-store'
    return response

