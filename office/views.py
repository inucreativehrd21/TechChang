"""
연구실 뷰.
  공개:   /lab/            픽셀 연구실 + 최근 회의·결정·작업 로그
          /lab/state.json  캔버스가 폴링하는 상태
  관리자: /lab/admin/      회의 안건 선택 · 보류 칼럼 검수 · 작업 로그 · 수동 소집
"""
import os
import subprocess
import sys
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.views import admin_required
from .agents import AGENTS, MEETING_ORDER, public_roster
from .models import ColumnDraft, Decision, Meeting, WorkLog

TOPIC_LABEL = {'hrd': 'HRD', 'data': '데이터분석', 'coding': '프로그래밍'}


def _public_meeting(meeting):
    if meeting is None:
        return None
    return {
        'id': meeting.id, 'week_start': meeting.week_start.isoformat(), 'held_at': meeting.held_at.isoformat(),
        'summary': meeting.summary,
        'transcript': [{'agent': t['agent'], 'name': AGENTS.get(t['agent'], {}).get('name', ''), 'round': t.get('round', 1),
                        'text': t['text']} for t in meeting.transcript if t.get('agent') in AGENTS],
        'decisions': [{'kind': d.kind, 'kind_label': d.get_kind_display(), 'topic': TOPIC_LABEL.get(d.topic, ''),
                       'question': d.question, 'options': d.options, 'chosen_key': d.chosen_key,
                       'chosen': d.chosen} for d in meeting.decisions.all() if d.is_public],
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


def _agent_status():
    """에이전트별 최근 활동 1건 → 상태 말풍선."""
    latest = {}
    for wl in WorkLog.objects.order_by('-created_at')[:200]:
        if wl.agent in AGENTS and wl.agent not in latest:
            latest[wl.agent] = wl
        if len(latest) == len(AGENTS):
            break
    now = timezone.now()
    result = []
    for a in public_roster():
        wl = latest.get(a['key'])
        status = {'action': 'idle', 'text': '', 'age_min': None}
        if wl:
            status = {'action': wl.action, 'text': wl.text, 'age_min': int((now - wl.created_at).total_seconds() // 60)}
        result.append({**a, 'status': status})
    return result


def _lab_assets_url():
    """media/lab/manifest.json 이 있으면 그 URL — 캔버스가 타일 모드로 전환된다. 없으면 ''."""
    path = os.path.join(settings.MEDIA_ROOT, 'lab', 'manifest.json')
    if not os.path.exists(path):
        return ''
    ver = int(os.path.getmtime(path))
    return f"{settings.MEDIA_URL.rstrip('/')}/lab/manifest.json?v={ver}"


def office_home(request):
    meeting = Meeting.objects.prefetch_related('decisions').first()
    recent_drafts = list(ColumnDraft.objects.filter(status=ColumnDraft.STATUS_PUBLISHED, question__isnull=False)
                         .select_related('question')[:6])
    decisions = [d for d in meeting.decisions.all() if d.is_public] if meeting else []
    for d in decisions:
        d.topic_name = TOPIC_LABEL.get(d.topic, '')
    for d in recent_drafts:
        d.topic_name = TOPIC_LABEL.get(d.topic, '')
    return render(request, 'office/office.html', {
        'roster': public_roster(),
        'meeting': meeting,
        'public_decisions': decisions,
        'recent_drafts': recent_drafts,
        'logs': decorate_logs(WorkLog.objects.exclude(action='fail')[:30]),
        'assets_url': _lab_assets_url(),
        'media_url': settings.MEDIA_URL.rstrip('/') + '/lab/',
    })


def office_state(request):
    meeting = Meeting.objects.prefetch_related('decisions').first()
    return JsonResponse({
        'now': timezone.localtime().isoformat(),
        'agents': _agent_status(),
        'meeting': _public_meeting(meeting),
        'recent_logs': [{'agent': l.agent, 'name': AGENTS.get(l.agent, {}).get('name', ''), 'action': l.action,
                         'text': l.text, 'at': timezone.localtime(l.created_at).strftime('%m-%d %H:%M')}
                        for l in WorkLog.objects.exclude(action='fail')[:20] if l.agent in AGENTS],
    })


# ───────────────────────────── 관리자
@admin_required
def office_admin(request):
    meetings = Meeting.objects.prefetch_related('decisions').order_by('-held_at')[:8]
    held = ColumnDraft.objects.filter(
        status__in=[ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_REVISING]).select_related('decision')
    recent_drafts = ColumnDraft.objects.exclude(
        status__in=[ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_REVISING]).select_related('question')[:12]
    logs = decorate_logs(WorkLog.objects.select_related('draft', 'meeting')[:80])
    for d in list(held) + list(recent_drafts):
        d.topic_name = TOPIC_LABEL.get(d.topic, '')
    for m in meetings:
        for d in m.decisions.all():
            d.topic_name = TOPIC_LABEL.get(d.topic, '')
        # 회의록 탭용: 발언에 이름·색 부여
        m.turns = [
            {'name': AGENTS[t['agent']]['name'], 'title': AGENTS[t['agent']]['title'],
             'color': AGENTS[t['agent']]['sprite']['shirt'], 'round': t.get('round', 1), 'text': t['text']}
            for t in m.transcript if t.get('agent') in AGENTS
        ]
    job_log = _job_log_tail()
    return render(request, 'office/admin.html', {
        'meetings': meetings, 'held': held, 'recent_drafts': recent_drafts, 'logs': logs,
        'agents': AGENTS, 'topic_label': TOPIC_LABEL, 'job_log': job_log,
        'has_api_key': bool(getattr(settings, 'ANTHROPIC_API_KEY', '')),
    })


@admin_required
@require_POST
def decision_choose(request, decision_id):
    d = get_object_or_404(Decision, pk=decision_id)
    key = request.POST.get('key', '')
    if key not in {o.get('key') for o in d.options}:
        messages.error(request, '선택지가 올바르지 않습니다.')
        return redirect('office:admin')
    d.chosen_key, d.chosen_by, d.chosen_at = key, request.user, timezone.now()
    d.note = request.POST.get('note', '').strip()[:300]
    d.save(update_fields=['chosen_key', 'chosen_by', 'chosen_at', 'note'])
    m = d.meeting
    if m.pending_count == 0 and m.status != Meeting.STATUS_CLOSED:
        m.status = Meeting.STATUS_CLOSED
        m.save(update_fields=['status'])
    WorkLog.objects.create(agent='lead', action='decision', meeting=m,
                           text=f"관리자 결정: {d.question} → {(d.chosen or {}).get('title', '')}")
    messages.success(request, f'결정 저장: {(d.chosen or {}).get("title", "")}')
    return redirect('office:admin')


@admin_required
@require_POST
def draft_publish(request, draft_id):
    from common.management.commands.auto_write_columns import TOPICS, _get_or_create_bot_user
    from community.models import Category, Question

    draft = get_object_or_404(ColumnDraft, pk=draft_id, status=ColumnDraft.STATUS_HOLD)
    category = Category.objects.filter(name=TOPICS[draft.topic]['category_name']).first()
    if category is None:
        messages.error(request, '카테고리를 찾을 수 없습니다.')
        return redirect('office:admin')
    q = Question.objects.create(author=_get_or_create_bot_user(), subject=draft.subject, content=draft.content,
                                create_date=timezone.now(), category=category)
    draft.question, draft.status = q, ColumnDraft.STATUS_PUBLISHED
    draft.decided_by, draft.decided_at = request.user, timezone.now()
    draft.save(update_fields=['question', 'status', 'decided_by', 'decided_at'])
    if draft.decision and draft.decision.consumed_at is None:
        draft.decision.consumed_at = timezone.now()
        draft.decision.save(update_fields=['consumed_at'])
    WorkLog.objects.create(agent='lead', action='publish', draft=draft, text=f'관리자 검수 후 발행: {draft.subject}')
    messages.success(request, f'발행: {draft.subject}')
    return redirect('office:admin')


@admin_required
@require_POST
def draft_reject(request, draft_id):
    draft = get_object_or_404(ColumnDraft, pk=draft_id, status=ColumnDraft.STATUS_HOLD)
    draft.status, draft.decided_by, draft.decided_at = ColumnDraft.STATUS_REJECTED, request.user, timezone.now()
    draft.save(update_fields=['status', 'decided_by', 'decided_at'])
    WorkLog.objects.create(agent='lead', action='reject', draft=draft, text=f'관리자 반려: {draft.subject}')
    messages.info(request, f'반려: {draft.subject}')
    return redirect('office:admin')


def _spawn(request, args: list):
    """manage.py <args> 를 백그라운드로 실행하고 출력을 logs/office_jobs.log 에 이어 쓴다."""
    manage = os.path.join(settings.BASE_DIR, 'manage.py')
    os.makedirs(os.path.join(settings.BASE_DIR, 'logs'), exist_ok=True)
    logf = open(os.path.join(settings.BASE_DIR, 'logs', 'office_jobs.log'), 'a', encoding='utf-8')
    logf.write(f"\n=== {timezone.localtime():%Y-%m-%d %H:%M:%S} {' '.join(args)} (by {request.user.username})\n")
    logf.flush()
    env = {**os.environ, 'DJANGO_SETTINGS_MODULE': os.environ.get('DJANGO_SETTINGS_MODULE', 'config.settings')}
    subprocess.Popen([sys.executable, manage, *args], cwd=settings.BASE_DIR,
                     stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)


def _job_log_tail(lines: int = 60) -> str:
    p = os.path.join(settings.BASE_DIR, 'logs', 'office_jobs.log')
    if not os.path.exists(p):
        return ''
    with open(p, encoding='utf-8', errors='replace') as f:
        return ''.join(f.readlines()[-lines:])


@admin_required
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
    note = request.POST.get('note', '').strip()
    if not note:
        messages.error(request, '수정 지시 내용을 입력하세요.')
        return redirect('office:admin')
    if draft.status not in (ColumnDraft.STATUS_HOLD, ColumnDraft.STATUS_REJECTED):
        messages.error(request, '검수 대기 중인 칼럼만 재작성할 수 있습니다.')
        return redirect('office:admin')

    draft.admin_note = note
    draft.status = ColumnDraft.STATUS_REVISING
    draft.decided_by, draft.decided_at = request.user, timezone.now()
    draft.save(update_fields=['admin_note', 'status', 'decided_by', 'decided_at'])
    _spawn(request, ['office_revise', '--draft', str(draft.id), '--note', note, '--by', request.user.username])
    messages.success(request, '수정 지시를 전달했습니다. 작업 로그에서 진행 상황이 실시간으로 갱신됩니다.')
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
        cmd = ['office_publish', '--topic', request.POST['topic']]
    else:
        messages.error(request, '알 수 없는 작업입니다.')
        return redirect('office:admin')

    _spawn(request, cmd)
    messages.success(request, '작업을 시작했습니다. 작업 로그 탭에서 진행 상황이 실시간으로 갱신됩니다.')
    return redirect('office:admin')
