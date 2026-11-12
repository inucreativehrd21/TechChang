"""칼럼 제작·회의의 단계별 산출물 기록기 (office.models.StageRun).

- 메인 스레드에서만 쓴다. 병렬 단계(office.concurrency.fan_out)의 워커는 결과만 돌려주고,
  호출부가 그 결과를 순서대로 record() 한다 — SQLite 동시 쓰기·스레드별 연결 문제를 피한다.
- dry-run 이면 DB 대신 메모리에만 쌓는다 (stages 로 확인 가능).
- 기록 실패 시 제작을 중단해 필수 근거가 빠진 원고의 승인을 막는다.
"""
from __future__ import annotations

import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)


class StagePersistenceError(RuntimeError):
    pass


def digest(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


class StageRecorder:
    def __init__(self, *, draft=None, question=None, meeting=None, dry: bool = False, run_id=None):
        from .run_context import current
        context = current()
        run_id = run_id or (context.run_id if context else None)
        self.run_id = run_id or uuid.uuid4()
        self.draft, self.question, self.meeting = draft, question, meeting
        self.dry = dry
        self.seq = 0
        if run_id and not dry:
            from .models import StageRun
            from django.db.models import Max
            self.seq = StageRun.objects.filter(run_id=self.run_id).aggregate(n=Max('seq'))['n'] or 0
        self.stages: list[dict] = []
        from .model_router import profile
        from .switches import SWITCHES, get
        self.metadata = {'profile': profile(), 'switches': {s.key: get(s.key) for s in SWITCHES}}
        from .editorial import current_track
        self.metadata['column_track'] = current_track()
        from .release import code_fingerprint
        self.metadata['code_fingerprint'] = code_fingerprint()
        import subprocess
        try:
            self.metadata['code_revision'] = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], text=True, timeout=3).strip()
        except (OSError, subprocess.SubprocessError):
            self.metadata['code_revision'] = None

    def record(self, stage: str, agent: str = '', output=None, *, status: str = 'ok', kind: str = '',
               sender: str = '', recipient: str = '', attempt: int = 1, text: str = '',
               seconds: float = 0.0, calls=None, error: str = '') -> dict:
        from .run_context import current
        from .execution import assert_current
        assert_current()
        context = current()
        if context:
            if calls is None:
                calls = [c for c in context.active_calls
                         if (stage in ('fail', 'final') or not c.get('tags', {}).get('stage')
                             or c.get('tags', {}).get('stage') == stage)
                         and id(c) not in context.recorded_call_ids]
            else:
                calls = [c for c in calls if id(c) not in context.recorded_call_ids]
        self.seq += 1
        if self.seq == 1:
            output = {**(output if isinstance(output, dict) else {}), 'execution': self.metadata}
        row = {
            'seq': self.seq, 'stage': stage, 'agent': agent, 'kind': kind, 'sender': sender,
            'recipient': recipient, 'attempt': attempt, 'status': status,
            'output': output if isinstance(output, (dict, list)) else ({'value': output} if output else {}),
            'text_digest': digest(text) if text else '', 'seconds': seconds,
            'calls': list(calls or []), 'error': (error or '')[:300],
        }
        if not self.dry:
            try:
                from .models import StageRun
                StageRun.objects.create(run_id=self.run_id, draft=self.draft, question=self.question,
                                        meeting=self.meeting, **row)
            except Exception as exc:
                logger.exception('StageRun 기록 실패: %s', stage)
                raise StagePersistenceError('필수 제작 기록을 저장하지 못했어요. 제작을 중단해요.') from exc
        self.stages.append(row)
        if context:
            context.recorded_call_ids.update(id(c) for c in calls)
        return row

    def complete(self, subject, content, check, review, **extra):
        from .audit import fingerprint
        from .evidence_bundle import report_payload
        review['evidence_run_id'] = str(self.run_id)
        return self.record('final', 'editor', {'subject': subject, 'content_hash': digest(content),
            'check_digest': fingerprint(check), 'review_digest': fingerprint(report_payload(review)),
            'verdict': review.get('verdict'), 'score': review.get('score'), **extra}, text=content)

    def outcome(self, stage: str, agent: str, oc, **kw) -> dict:
        """office.concurrency.Outcome 을 그대로 기록한다."""
        return self.record(stage, agent, oc.value if oc.ok else None, status='ok' if oc.ok else 'failed',
                           seconds=oc.seconds, error=oc.error, **kw)
