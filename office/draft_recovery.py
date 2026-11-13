"""저장 전 중단된 빈 원고에서, 지문이 일치하는 마지막 검수본만 찾는다."""
from .models import StageRun
from .pipeline import verification_hash
from .recorder import digest


def reviewed_candidate(draft):
    rows = list(StageRun.objects.filter(draft=draft).order_by('pk'))
    for review in reversed(rows):
        qa = review.output
        if review.stage != 'review' or review.status != 'ok' or not isinstance(qa, dict):
            continue
        prior = [s for s in rows if s.run_id == review.run_id and s.seq < review.seq and s.status == 'ok']
        bodies = [s for s in prior if isinstance(s.output, dict) and s.output.get('content')
                  and digest(s.output['content']) == qa.get('reviewed_full_hash')]
        if not bodies:
            continue
        body = bodies[-1]
        content, subject = body.output['content'], qa.get('verified_subject')
        checks = [s for s in prior if s.stage in ('check', 'recheck', 'reverify')
                  and isinstance(s.output, dict) and s.output.get('subject') == subject
                  and s.output.get('verification_hash') == verification_hash(content)]
        if not subject or not checks:
            continue
        # 관리 도판이 삽입된 뒤의 본문을 재구성하지 않는다. 정확히 보존된 본문만 허용한다.
        return {'subject': subject, 'content': content, 'check_report': checks[-1].output,
                'qa_report': {k: v for k, v in qa.items() if k not in ('human_approval', 'evidence_run_id')},
                'source': {'run_id': str(review.run_id), 'body_stage': body.pk,
                           'check_stage': checks[-1].pk, 'review_stage': review.pk,
                           'content_hash': digest(content)}}
    raise ValueError('본문·팩트체크·심사 지문이 일치하는 검수본이 없어요. 수동 복구가 필요해요.')
