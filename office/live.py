"""연구실 '칼럼이 만들어지는 과정' 라이브 표시.

칼럼 제작은 cron 이 띄운 별도 프로세스(office_publish·hold_meeting 등)에서 돌고, 웹(gunicorn)과
메모리를 공유하지 않는다(캐시도 프로세스별 LocMem). 그래서 단계가 **시작될 때** 작은 JSON 파일에
지금 단계를 적고, 웹은 그 파일만 읽는다. 마이그레이션도, 추가 API 비용도 없다.

- 단계는 공개 표시줄의 9칸과 같은 키를 쓴다(STEPS). 내부 단계(fix·recheck 등)는 mark() 에서 접는다.
- 갱신이 STALE_AFTER 넘게 없으면 프로세스가 죽은 것으로 보고 무시한다.
- '운영자 결정'은 실행 중인 작업이 아니라 기다리는 상태라 파일이 아니라 DB(미결 안건)로 판단한다.
- 기록 실패가 제작을 멈추게 하면 안 된다 — 모든 쓰기는 예외를 삼킨다.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

STEPS = ['meeting', 'decision', 'brief', 'draft', 'check', 'critique', 'chart', 'review', 'publish']
STEP_LABEL = {
    'meeting': '편집회의', 'decision': '운영자 결정', 'brief': '기획', 'draft': '집필', 'check': '검증',
    'critique': '평론', 'chart': '시각화', 'review': '편집 심사', 'publish': '발행',
}
STEP_VERB = {
    'meeting': '편집회의를 하고 있습니다', 'brief': '집필 의뢰서를 쓰고 있습니다', 'draft': '원고를 쓰고 있습니다',
    'check': '수치와 출처를 확인하고 있습니다', 'critique': '독자 입장에서 읽고 있습니다',
    'chart': '도표를 만들고 있습니다', 'review': '편집 심사를 하고 있습니다', 'publish': '칼럼을 발행했습니다',
}
# 내부 단계 → 공개 단계
STAGE_TO_STEP = {
    'brief': 'brief', 'draft': 'draft', 'fix': 'draft', 'revise': 'draft', 'editor_revise': 'draft',
    'precheck': 'check', 'check': 'check', 'recheck': 'check', 'reverify': 'check',
    'critique': 'critique', 'chart': 'chart', 'review': 'review', 'publish': 'publish', 'meeting': 'meeting',
}
TOPIC_LABEL = {'hrd': 'HRD', 'data': '데이터분석', 'coding': '프로그래밍'}

STALE_AFTER = timedelta(minutes=15)      # 한 단계가 이보다 오래 갱신이 없으면 죽은 작업
DONE_VISIBLE = timedelta(minutes=30)     # 발행 직후 '발행' 칸을 켜 두는 시간

# 서버 crontab(ubuntu) 과 같은 일정 — crontab 을 바꾸면 여기도 바꾼다
SCHEDULE = [  # (weekday 0=월, hour, minute, step, topic)
    (6, 20, 0, 'meeting', ''),
    (1, 10, 0, 'brief', 'hrd'),
    (3, 10, 0, 'brief', 'data'),
    (5, 10, 0, 'brief', 'coding'),
]


def _path() -> Path:
    return Path(getattr(settings, 'OFFICE_LIVE_PATH', '') or Path(settings.BASE_DIR) / 'logs' / 'office_live.json')


def _write(data: dict) -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)   # 읽는 쪽이 반쯤 쓴 파일을 보지 않게
    except Exception:  # noqa: BLE001
        logger.exception('live 상태 기록 실패')


def _read() -> dict:
    try:
        return json.loads(_path().read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 — 파일이 없거나 쓰는 중이면 '쉬는 중'
        return {}


def mark(stage: str, agent: str = '', topic: str = '') -> None:
    """단계 시작을 알린다. stage 는 내부 단계명(fix·recheck 등)도 받는다."""
    step = STAGE_TO_STEP.get(stage, stage)
    if step not in STEPS:
        return
    prev = _read()
    now = timezone.now()
    same = prev.get('step') == step and prev.get('state') == 'running'
    _write({
        'step': step, 'state': 'done' if step == 'publish' else 'running',
        'agent': agent or prev.get('agent', ''), 'topic': topic or prev.get('topic', ''),
        'since': prev.get('since') if same else now.isoformat(),   # 같은 단계를 이어 가면 시작 시각 유지
        'at': now.isoformat(),
        'job_started': prev.get('job_started') if prev.get('state') == 'running' else now.isoformat(),
    })


def finish() -> None:
    """작업 종료. 발행으로 끝났으면 'done' 을 남겨 두고, 아니면 쉬는 상태로."""
    prev = _read()
    if prev.get('state') == 'done':
        return
    _write({'step': None, 'state': 'idle', 'at': timezone.now().isoformat()})


def _josa(word: str) -> str:
    """받침이 있으면 '이', 없으면 '가'."""
    code = ord(word[-1]) - 0xAC00 if word else -1
    return '이' if 0 <= code <= 11171 and code % 28 else '가'


def _parse(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def next_run(now=None) -> dict | None:
    now = timezone.localtime(now or timezone.now())
    best = None
    for wd, h, m, step, topic in SCHEDULE:
        days = (wd - now.weekday()) % 7
        at = (now + timedelta(days=days)).replace(hour=h, minute=m, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=7)
        if best is None or at < best[0]:
            best = (at, step, topic)
    at, step, topic = best
    what = '편집회의' if step == 'meeting' else f'{TOPIC_LABEL.get(topic, "")} 칼럼 제작'
    return {'at': at.isoformat(), 'label': f'{at.month}월 {at.day}일({"월화수목금토일"[at.weekday()]}) {at:%H:%M}',
            'what': what}


def snapshot(now=None) -> dict:
    """공개용 현재 상태. {step, state(running|done|waiting|idle), message, since, next}"""
    from office.agents import AGENTS
    from office.models import Meeting

    now = now or timezone.now()
    data = _read()
    at = _parse(data.get('at', ''))
    out = {'step': None, 'state': 'idle', 'message': '', 'since': None, 'next': next_run(now)}

    if data.get('step') and at:
        age = now - at
        alive = (data.get('state') == 'running' and age <= STALE_AFTER) or \
                (data.get('state') == 'done' and age <= DONE_VISIBLE)
        if alive:
            step = data['step']
            a = AGENTS.get(data.get('agent', ''), {})
            who = f"{a['title']} {a['name']}{_josa(a['name'])}" if a else '연구팀이'
            topic = TOPIC_LABEL.get(data.get('topic', ''), '')
            subject = f'{topic} 칼럼 — ' if topic and step != 'meeting' else ''
            if data['state'] == 'done':
                message = f'{subject}칼럼을 발행했습니다.'
            else:
                message = f'{subject}지금 {who} {STEP_VERB.get(step, "작업 중입니다")}.'
            out.update(step=step, state=data['state'], message=message,
                       since=data.get('since'), job_started=data.get('job_started'))
            return out

    # 실행 중인 작업이 없으면, 회의가 끝나고 안건이 결정을 기다리는지 본다
    meeting = Meeting.objects.order_by('-held_at').first()
    if meeting and meeting.status == Meeting.STATUS_OPEN and meeting.pending_count:
        out.update(step='decision', state='waiting', since=meeting.held_at.isoformat(),
                   message=f'편집회의가 끝났고, 운영자가 안건 {meeting.pending_count}건을 고르는 중입니다.')
        return out

    out['message'] = '지금은 쉬는 중입니다.'
    return out
