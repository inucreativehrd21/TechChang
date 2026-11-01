"""같은 원고의 독립 검토만 병렬 실행한다. 통합·본문 변경·기록은 호출자가 한다."""
from contextvars import ContextVar
from common.services.claude import call_tags, track_calls, _call_tags
from .concurrency import fan_out

_worker = ContextVar('office_review_worker', default=False)


class ReviewIncomplete(RuntimeError):
    pass


def in_worker():
    return _worker.get()


def run(tasks, *, stages=None, attempt=1):
    """tasks={stage: (agent_key, callable)}. 실패한 필수 검토를 누락하지 않는다."""
    def job(stage, agent, fn):
        def invoke():
            token = _worker.set(True)
            try:
                call_filter = {'stage': stage}
                if _call_tags.get().get('run_id'):
                    call_filter['run_id'] = _call_tags.get()['run_id']
                with call_tags(stage=stage, agent=agent), track_calls(alert=False, filter=call_filter) as calls:
                    value = fn()
                return {'value': value, 'calls': list(calls)}
            finally:
                from django.db import connections
                connections.close_all()  # 검토 스레드가 연 DB 연결을 실행 밖으로 남기지 않아요.
                _worker.reset(token)
        return invoke
    outcomes = fan_out({s: job(s, agent, fn) for s, (agent, fn) in tasks.items()}, workers=2)
    result = {}
    errors = []
    for stage, outcome in outcomes.items():
        agent = tasks[stage][0]
        payload = outcome.value if outcome.ok else {}
        if stages:
            stages.record(stage, agent, payload.get('value'), attempt=attempt,
                          status='ok' if outcome.ok else 'failed', seconds=outcome.seconds,
                          calls=payload.get('calls'), error=outcome.error)
        if not outcome.ok:
            errors.append(stage + ': ' + outcome.error)
        else:
            result[stage] = payload['value']
    if errors:
        raise ReviewIncomplete('독립 검토를 끝내지 못해 보류해요. ' + ' / '.join(errors))
    return result
