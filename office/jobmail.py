"""cron 작업이 멈췄을 때 운영자 메일 — 이유·구독 한도 해제 시각·한 번에 누르는 재실행 버튼.

구독(CLI)만 쓰므로(CLAUDE_CLI_FALLBACK=false) 한도에 걸리면 그 작업은 실패한다. 예전 메일은 사유만 적어,
운영자가 해제 시각을 계산해 서버에서 직접 다시 돌려야 했다. 이제:
  - 한도 중단 메일: 멈춘 작업 · 사유 · 해제 예정 시각 · [한도 풀리면 다시 실행] 버튼
  - 준비 미달 메일(office.schedule): 남은 필수 수정 · [지적대로 고쳐 재심 요청] 버튼(실패면 [다시 준비])
버튼은 서명된 링크(3일) → 확인 화면에서 한 번 더 눌러야 예약된다(메일 보안 검사기가 링크를 열어도 실행되지 않게).
예약(JobRequest)은 office_release(10분마다)가 실행 시각에 띄운다. 그때도 한도 중이면 해제 뒤로 미룬다.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger(__name__)

SALT = 'office.jobmail'
MAX_AGE = 3 * 24 * 3600
SITE = 'https://techchang.com'
AFTER_RESET = timedelta(minutes=5)          # 해제 직후는 피한다
# 메일로 다시 실행할 수 있는 명령 — 연구실 제작 작업만(서버 관리·데이터 삭제 명령은 열지 않는다)
RERUNNABLE = {'office_publish', 'auto_write_series', 'make_newsletter', 'hold_meeting', 'office_revise',
              'remake_column', 'update_column_map'}
LIMIT_RE = re.compile(r'session limit|usage limit|rate limit|hit your .*limit', re.I)
RESET_RE = re.compile(r'resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)', re.I)
REVISE_NOTE = '편집장 필수 수정과 팩트체크 지적을 모두 반영해 고쳐 주세요(운영자 메일에서 재심 요청).'


# ───────────────────────────── 한도
def is_limit(reason: str) -> bool:
    return bool(LIMIT_RE.search(reason or ''))


def reset_at(reason: str, now=None):
    """'resets 2:50am (Asia/Seoul)' → 해제 시각(aware). 한도 오류가 아니면 None, 시각을 못 읽으면 30분 뒤."""
    if not is_limit(reason):
        return None
    now = timezone.localtime(now) if now else timezone.localtime()
    m = RESET_RE.search(reason)
    if not m:
        return now + timedelta(minutes=30)
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0)
    at = now.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def record_limit(reason: str, job: str = ''):
    at = reset_at(reason)
    if at is None:
        return None
    from office.models import CliLimit
    CliLimit.objects.create(reset_at=at, reason=(reason or '')[:300], job=job[:200])
    return at


def limited_until(now=None):
    """아직 풀리지 않은 한도의 해제 시각(없으면 None)."""
    from office.models import CliLimit
    now = now or timezone.now()
    row = CliLimit.objects.filter(reset_at__gt=now).order_by('-reset_at').first()
    return row.reset_at if row else None


def earliest_run(now=None):
    now = now or timezone.now()
    until = limited_until(now)
    return max(now, until + AFTER_RESET) if until else now


# ───────────────────────────── 서명 링크 · 예약
def make_token(kind: str, args: list, label: str, *, draft_id=None, run_after=None) -> str:
    return signing.dumps({'k': kind, 'a': [str(x) for x in args], 'l': label[:200], 'd': draft_id,
                          'r': run_after.isoformat() if run_after else None}, salt=SALT, compress=True)


def read_token(token: str) -> dict:
    """서명·기한·명령 허용 목록을 확인한다. 틀리면 signing.BadSignature."""
    data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    if not data.get('a') or data['a'][0] not in RERUNNABLE or data.get('k') not in ('rerun', 'revise'):
        raise signing.BadSignature('허용되지 않은 작업')
    return data


def link(token: str) -> str:
    from django.urls import reverse
    return SITE + reverse('office:job_request', args=[token])


def enqueue(data: dict, *, via: str = 'mail'):
    """서명 확인된 요청을 예약한다. 같은 인자의 대기 요청이 있으면 그것을 돌려준다(두 번 눌러도 한 번)."""
    from datetime import datetime

    from office.models import JobRequest
    # JSON 필드 비교는 DB 마다 다르게 굴어(MySQL/SQLite) 파이썬에서 맞춘다 — 대기 요청은 몇 건뿐이다
    have = next((j for j in JobRequest.objects.filter(status=JobRequest.ST_PENDING) if list(j.args) == list(data['a'])),
                None)
    if have:
        return have, False
    wanted = datetime.fromisoformat(data['r']) if data.get('r') else None
    run_after = max(wanted, earliest_run()) if wanted else earliest_run()
    job = JobRequest.objects.create(kind=data['k'], args=data['a'], label=data.get('l', ''), draft_id=data.get('d'),
                                    run_after=run_after, requested_via=via)
    return job, True


def run_due(now=None, out=print) -> list:
    """실행 시각이 된 예약을 띄운다. 한도 중이면 해제 뒤로 미루고, 재심 대상 원고가 이미 처리됐으면 건너뛴다."""
    from office.jobs import spawn
    from office.models import ColumnDraft, JobRequest
    now = now or timezone.now()
    until = limited_until(now)
    started = []
    for job in JobRequest.objects.filter(status=JobRequest.ST_PENDING, run_after__lte=now):
        if until:
            job.run_after = until + AFTER_RESET
            job.save(update_fields=['run_after'])
            out(f'한도 중 — #{job.pk} {job.label} 을 {timezone.localtime(job.run_after):%m.%d %H:%M} 로 미룸')
            continue
        if job.kind == JobRequest.KIND_REVISE and job.draft and job.draft.status != ColumnDraft.STATUS_HOLD:
            job.status, job.note = JobRequest.ST_SKIPPED, f'원고가 이미 {job.draft.get_status_display()} 상태'
            job.save(update_fields=['status', 'note'])
            continue
        # 동시에 두 runner 가 집지 않게 상태를 먼저 바꾼다
        if not JobRequest.objects.filter(pk=job.pk, status=JobRequest.ST_PENDING).update(
                status=JobRequest.ST_STARTED, started_at=now):
            continue
        spawn(list(job.args), by=f'jobrequest#{job.pk}', env={'CLAUDE_CLI_FALLBACK': 'false'})
        started.append(job)
        out(f'재실행: #{job.pk} {" ".join(job.args)}')
    return started


# ───────────────────────────── 메일
def _recipient() -> str:
    to = os.environ.get('DJANGO_ADMIN_EMAIL', '').strip()
    if not to and getattr(settings, 'ADMINS', None):
        to = settings.ADMINS[0][1]
    return to


def send(subject: str, lines: list[str], buttons: list[tuple[str, str, str]]) -> bool:
    """text + HTML(버튼). buttons: [(라벨, 링크, 한 줄 설명)]."""
    from django.core.mail import EmailMultiAlternatives
    to = _recipient()
    if not to:
        return False
    text = '\n'.join(lines + [''] + [f'▶ {label}: {url}\n   {note}' for label, url, note in buttons]
                     + ['', f'관리 화면: {SITE}/lab/admin/'])
    paras = ''.join(f'<p style="margin:0 0 8px;line-height:1.6">{escape(l)}</p>' if l else '<div style="height:8px"></div>'
                    for l in lines)
    btns = ''.join(
        f'<div style="margin:14px 0 4px"><a href="{escape(url)}" style="display:inline-block;padding:11px 18px;'
        f'background:#4f46e5;color:#fff;border-radius:10px;text-decoration:none;font-weight:700">{escape(label)}</a>'
        f'<div style="font-size:13px;color:#6b7280;margin-top:6px">{escape(note)}</div></div>' for label, url, note in buttons)
    html = (f'<div style="font-family:Pretendard,Apple SD Gothic Neo,sans-serif;font-size:15px;color:#18181b;max-width:560px">'
            f'{paras}{btns}<p style="margin-top:18px;font-size:13px;color:#6b7280">버튼은 3일 동안 쓸 수 있고, 누르면 확인 화면에서 '
            f'한 번 더 눌러야 예약됩니다. · <a href="{SITE}/lab/admin/">관리 화면</a></p></div>')
    try:
        msg = EmailMultiAlternatives(f'[TechChang] {subject}', text, settings.DEFAULT_FROM_EMAIL, [to])
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=False)
        return True
    except Exception:  # noqa: BLE001 — 알림 실패가 본 작업을 막으면 안 된다
        logger.exception('운영자 메일 실패: %s', subject)
        return False


def _fmt(at) -> str:
    return f'{timezone.localtime(at):%m.%d(%a) %H:%M}'


def limit_mail(args: list, reason: str, model: str = '') -> bool:
    """구독 한도로 cron 작업이 멈췄다 — 해제 시각과 [한도 풀리면 다시 실행]."""
    job = ' '.join(args) or '?'
    at = record_limit(reason, job)
    lines = [f'구독(CLI) 호출이 실패해 작업이 멈췄습니다. 유료 API 로는 넘기지 않습니다(CLAUDE_CLI_FALLBACK=false).', '',
             f'멈춘 작업: manage.py {job}', f'사유: {reason[:240]}']
    if model:
        lines.append(f'모델: {model}')
    buttons = []
    if at is not None:
        lines += [f'한도 해제 예정: {_fmt(at)}', '']
        if args and args[0] in RERUNNABLE:
            run = at + AFTER_RESET
            buttons.append(('한도 풀리면 다시 실행', link(make_token('rerun', args, f'다시 실행: {job}', run_after=run)),
                            f'{_fmt(run)}에 같은 작업을 다시 돌립니다.'))
        if '--prepare' in args:
            lines.append('예약 공개 준비 작업이면 정기 재시도(전날 22시·당일 4시)도 그대로 돌아갑니다.')
    else:
        lines += ['', '한도 문구가 아니라 다른 실패입니다(토큰 만료·CLI 경로 등). 서버 .env 의 CLAUDE_CODE_OAUTH_TOKEN·CLAUDE_CLI_BIN 을 확인하세요.']
        if args and args[0] in RERUNNABLE:
            buttons.append(('지금 다시 실행', link(make_token('rerun', args, f'다시 실행: {job}')),
                            '원인을 고친 뒤 눌러 주세요. 10분 안에 실행됩니다.'))
    subject = (f'구독 한도로 작업 중단 — {args[0] if args else "?"} · {_fmt(at)} 해제' if at
               else f'구독 호출 실패로 작업 중단 — {args[0] if args else "?"}')
    return send(subject, lines, buttons)


def revise_args(draft) -> list:
    owner = getattr(settings, 'SITE_OWNER_USERNAME', 'admin')
    if draft.series_key:
        return ['auto_write_series', '--revise-draft', str(draft.pk), '--by', owner]
    return ['office_revise', '--draft', str(draft.pk), '--note', REVISE_NOTE, '--by', owner]


def not_ready_mail(draft, label: str, reason: str, *, rerun_args: list | None = None) -> bool:
    """예약 공개 준비가 심사를 통과하지 못했거나 멈췄다 — 남은 필수 수정과 [재심 요청]/[다시 준비]."""
    from office import review_protocol as R
    from office.models import ColumnDraft
    qa = draft.qa_report or {}
    when = _fmt(draft.publish_at) if draft.publish_at else '(예정 없음)'
    lines = [f'{when} 공개 예정인 {label} 원고가 준비 단계에서 {reason}.',
             f'제목: {draft.subject or draft.brief or "(제목 없음)"}']
    if qa:
        lines.append(f'편집 심사: {qa.get("score", "-")}점 · 판정 {qa.get("verdict", "-")}'
                     + (f' · 치명 결함 {", ".join(qa.get("fatal") or [])}' if qa.get('fatal') else ''))
    must = R.must_fix_items(qa)
    if must:
        lines += ['', '남은 필수 수정:'] + [f'  - {R.as_line(m)}' for m in must]
    elif qa.get('notes'):
        lines += ['', f'편집장: {qa["notes"]}']
    until = limited_until()
    if until:
        lines += ['', f'지금은 구독 한도 중입니다(해제 {_fmt(until)}). 버튼을 누르면 해제 뒤에 실행됩니다.']
    lines += ['', '공개 시각 전에 통과하면 공개 대기로 들어가 그 시각에 공개되고, 지났으면 바로 발행됩니다.']
    buttons = []
    if draft.status == ColumnDraft.STATUS_HOLD:
        buttons.append(('지적대로 고쳐 재심 요청',
                        link(make_token('revise', revise_args(draft), f'재심 요청: {draft.subject or draft.brief}',
                                        draft_id=draft.pk)),
                        '담당 연구원이 남은 필수 수정을 고치고 편집장이 다시 심사합니다.'))
    elif rerun_args and rerun_args[0] in RERUNNABLE:
        buttons.append(('다시 준비', link(make_token('rerun', rerun_args, f'다시 준비: {label}')),
                        '같은 공개 시각 몫을 처음부터 다시 만듭니다.'))
    return send(f'{when} 공개 예정 {label} — {reason}', lines, buttons)
