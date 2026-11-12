"""승인 대상 원고와 필수 제작 기록을 연결한다."""
import uuid
from .audit import fingerprint
from .recorder import digest


def report_payload(report):
    return {k: v for k, v in report.items() if k not in ('human_approval', 'evidence_run_id')}


def validate(draft):
    from .models import StageRun
    try:
        run_id = uuid.UUID(str(draft.qa_report.get('evidence_run_id')))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('현재 원고의 필수 제작 기록이 없어요. 검증·심사를 다시 실행해 주세요.') from exc
    rows = list(StageRun.objects.filter(draft_id=draft.pk, run_id=run_id).exclude(stage='applied').order_by('seq'))
    if not rows or [r.seq for r in rows] != list(range(1, len(rows)+1)):
        raise ValueError('제작 단계 기록이 누락됐어요. 승인할 수 없어요.')
    finals = [r for r in rows if r.stage == 'final' and r.status == 'ok']
    if not finals:
        raise ValueError('최종 제작 기록이 없어요. 승인할 수 없어요.')
    final = finals[-1]
    if final.seq != rows[-1].seq:
        raise ValueError('최종 기록 뒤 새 실행 기록이 있어요. 다시 검증해 주세요.')
    preceding = [r for r in rows if r.seq < final.seq and r.status == 'ok']
    checks = [r for r in preceding if r.stage in ('check', 'recheck', 'reverify')]
    reviews = [r for r in preceding if r.stage == 'review']
    if not checks or not reviews or checks[-1].seq >= reviews[-1].seq:
        raise ValueError('팩트체크와 편집 심사 기록이 완전하지 않아요.')
    from .pipeline import verification_hash
    check, review = checks[-1].output, reviews[-1].output
    if (check.get('subject') != draft.subject or check.get('verification_hash') != verification_hash(draft.content)
            or review.get('verified_subject') != draft.subject or review.get('reviewed_full_hash') != digest(draft.content)):
        raise ValueError('단계 기록이 현재 원고 버전과 달라요.')
    expected = {'subject': draft.subject, 'content_hash': digest(draft.content),
                'check_digest': fingerprint(draft.check_report),
                'review_digest': fingerprint(report_payload(draft.qa_report))}
    if final.text_digest != digest(draft.content) or any(final.output.get(k) != v for k, v in expected.items()):
        raise ValueError('최종 기록의 원고·검증·심사 지문이 일치하지 않아요.')
    latest = StageRun.objects.filter(draft_id=draft.pk).exclude(stage='applied').order_by('-pk').first()
    if latest and latest.run_id != run_id:
        raise ValueError('새 제작 실행이 있어요. 현재 실행의 검증·심사를 완료해 주세요.')
    return run_id
