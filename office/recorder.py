"""칼럼 제작·회의의 단계별 산출물 기록기 (office.models.StageRun).

- 메인 스레드에서만 쓴다. 병렬 단계(office.concurrency.fan_out)의 워커는 결과만 돌려주고,
  호출부가 그 결과를 순서대로 record() 한다 — SQLite 동시 쓰기·스레드별 연결 문제를 피한다.
- dry-run 이면 DB 대신 메모리에만 쌓는다 (stages 로 확인 가능).
- 기록 실패가 제작을 멈추게 하지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)


def digest(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


class StageRecorder:
    def __init__(self, *, draft=None, question=None, meeting=None, dry: bool = False, run_id=None):
        self.run_id = run_id or uuid.uuid4()
        self.draft, self.question, self.meeting = draft, question, meeting
        self.dry = dry
        self.seq = 0
        self.stages: list[dict] = []

    def record(self, stage: str, agent: str = '', output=None, *, status: str = 'ok', kind: str = '',
               sender: str = '', recipient: str = '', attempt: int = 1, text: str = '',
               seconds: float = 0.0, calls=None, error: str = '') -> dict:
        self.seq += 1
        row = {
            'seq': self.seq, 'stage': stage, 'agent': agent, 'kind': kind, 'sender': sender,
            'recipient': recipient, 'attempt': attempt, 'status': status,
            'output': output if isinstance(output, (dict, list)) else ({'value': output} if output else {}),
            'text_digest': digest(text) if text else '', 'seconds': seconds,
            'calls': list(calls or []), 'error': (error or '')[:300],
        }
        self.stages.append(row)
        if not self.dry:
            try:
                from .models import StageRun
                StageRun.objects.create(run_id=self.run_id, draft=self.draft, question=self.question,
                                        meeting=self.meeting, **row)
            except Exception:  # noqa: BLE001 — 기록 실패로 제작이 멈추면 안 된다
                logger.exception('StageRun 기록 실패: %s', stage)
        return row

    def outcome(self, stage: str, agent: str, oc, **kw) -> dict:
        """office.concurrency.Outcome 을 그대로 기록한다."""
        return self.record(stage, agent, oc.value if oc.ok else None, status='ok' if oc.ok else 'failed',
                           seconds=oc.seconds, error=oc.error, **kw)
