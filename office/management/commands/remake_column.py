"""이미 발행된 칼럼을 현재 기준으로 다시 만들어 **제자리에서 갱신**한다.

옛 로직으로 쓰인 칼럼에는 '숫자로 보는 현황' 섹션이 없어 수치 근거도 도판도 없다.
새 글로 다시 올리면 같은 주제가 두 URL에 생겨 검색에서 서로를 깎아먹으므로, 기존 글을
그대로 두고 내용만 갱신한다 — URL·조회수·유입이 유지된다.

흐름은 발행 파이프라인과 같다: 재집필 → 자동 점검 → 팩트체크 → 도판 → 평론 → 편집 심사.
자동 재작성은 하지 않는다 — 심사에서 기준 미달이면 **원문을 그대로 두고** 보고만 한다.
(발행된 글을 더 나쁜 판본으로 덮어쓰지 않기 위해서다. 다시 돌리려면 명령을 한 번 더 실행.)
단계별 산출물은 StageRun(question=…)에 남는다.

OFFICE_AGENT_SPOOL 을 걸면 API 대신 파일로 주고받는다 — 과금 없이 돌릴 때 쓴다.

사용법:
  python manage.py remake_column --question 47
  python manage.py remake_column --question 47 --dry-run   # 저장하지 않고 결과만
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from common.management.commands.auto_write_columns import COLUMN_STRUCTURE
from community.models import Question
from office import pipeline as P
from office import quality
from office.recorder import StageRecorder
from office.agents import TOPIC_AGENT
from office.management.commands.audit_columns import audit_one
from office.services import ask_agent, log

REMAKE_PROMPT = (
    '이미 발행된 칼럼을 현재 편집 기준에 맞게 다시 만듭니다. '
    '**주제와 논지는 그대로 두고**, 아래 지적을 해결하는 데 집중하세요.\n\n'
    '[이 칼럼이 지금 기준에 어긋나는 점]\n{flaws}\n\n'
    '가장 중요한 것은 **"## 숫자로 보는 현황" 섹션 신설**입니다. '
    '이 주제를 뒷받침하는 **실제 공표 통계 3~5개**를 기관·보고서명과 함께 넣으세요. '
    '값이 기억나지 않으면 그 수치는 쓰지 말고 확실히 아는 다른 지표로 바꿉니다. '
    '지어낸 수치나 "가상의 예시"로 이 섹션을 채우면 반려됩니다. '
    '같은 단위로 나란히 놓을 수 있는 값을 우선하세요 — 이 수치들이 그대로 도표가 됩니다.\n\n'
    '기존 본문에서 살아 있는 서술·사례·문장은 최대한 보존하고, 새 섹션과 어긋나는 부분만 손봅니다. '
    '이미 좋은 글을 헤집어 다시 쓰는 것이 아닙니다.\n\n'
    '[현재 칼럼]\nTITLE: {subject}\n---\n{content}\n\n{structure}\n\n{standard}'
)


class Command(BaseCommand):
    help = '발행된 칼럼을 현재 기준으로 다시 만들어 제자리에서 갱신합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true', help='저장하지 않고 결과만 출력')
        parser.add_argument('--no-chart', action='store_true')

    def handle(self, *args, **opts):
        out = self.stdout.write
        q = Question.objects.filter(pk=opts['question'], is_deleted=False).first()
        if q is None:
            raise CommandError(f"칼럼 #{opts['question']} 없음")

        topic_key = {'HRD': 'hrd', '데이터분석': 'data', '프로그래밍': 'coding'}.get(
            q.category.name if q.category else '', 'data')
        writer = TOPIC_AGENT[topic_key]
        flaws = audit_one(q)['flaws']
        out(f'#{q.id} [{q.category.name if q.category else "-"}] {q.subject}')
        out(f'  현재 {P.body_length(q.content):,}자 · 조회 {q.view_count} · 지적 {len(flaws)}건')
        for f in flaws:
            out(f'    · {f[:120]}')
        if not flaws:
            out(self.style.SUCCESS('  이미 현재 기준을 통과합니다 — 손대지 않습니다.'))
            return

        standard = P.writing_standard()
        # 단계별 산출물 기록 (내부 전용). 발행된 글을 갱신하므로 question 에 묶는다
        stages = StageRecorder(question=q, dry=opts['dry_run'])
        stages.record('audit', 'editor', {'flaws': flaws}, text=q.content)

        def rec(agent, action, text):
            out(f'  [{agent}] {text[:120]}')
            log(agent, action, text)

        # 1) 재집필
        raw = ask_agent(writer, REMAKE_PROMPT.format(
            flaws='\n'.join(f'- {f}' for f in flaws), subject=q.subject, content=q.content,
            structure=COLUMN_STRUCTURE, standard=standard), max_tokens=P.COLUMN_MAX_TOKENS)
        subject, content, ok, why = P.safe_rewrite(raw, q.subject, q.content)
        stages.record('draft', writer, {'subject': subject, 'content': content, 'ok': ok, 'why': why},
                      status='ok' if ok else 'failed', text=content)
        if not ok:
            out(self.style.ERROR(f'  재집필 실패 — {why}'))
            return
        rec(writer, 'revise', f'리메이크 재집필: {subject} ({P.body_length(content)}자)')

        left = P.precheck_draft(content)
        stages.record('precheck', 'editor', {'issues': left, 'quality': quality.report(subject, content)})
        if left:
            subject, content, left = P.step_fix_draft(topic_key, subject, content, left)
            stages.record('fix', writer, {'subject': subject, 'content': content, 'remaining': left},
                          text=content)
            rec(writer, 'revise', f'자동 점검 보완 — 남은 지적 {len(left)}건')

        # 2) 팩트체크 → 3) 도판 → 4) 평론 → 5) 편집 심사
        recent = list(Question.objects.filter(is_deleted=False).exclude(pk=q.pk)
                      .order_by('-create_date').values_list('subject', flat=True)[:20])
        check = P.step_check(subject, content, recent)
        stages.record('check', 'checker', check, kind='report', sender='checker', recipient='editor')
        rec('checker', 'check', f"팩트체크 {check.get('verdict')}")

        chart_rel, visual_report = '', ''
        if not opts['no_chart']:
            content = P.strip_visual_block(content)
            content, chart_rel, _note, visual_report = P.step_visual(content, topic_key, rec=rec)
            stages.record('chart', 'charter', {'chart': chart_rel, 'note': _note, 'report': visual_report})

        critique = P.step_critique(subject, content)
        stages.record('critique', 'critic', critique, kind='report', sender='critic', recipient='editor')
        rec('critic', 'critique', f"평론 {critique['verdict']} · 지적 {len(critique.get('issues') or [])}건")

        qa = P.step_review(subject, content, check, chart_rel, visual_report, critique)
        stages.record('review', 'editor', qa)
        stages.record('final', 'editor', {'verdict': qa['verdict'], 'score': qa.get('score'),
                                          'quality': quality.report(subject, content)}, text=content)
        rec('editor', 'qa', f"심사 {qa['score']}/100 ({qa['length']}자) → {qa['verdict']}"
                            + (f" · 치명 {','.join(qa['fatal'])}" if qa.get('fatal') else ''))

        if qa['verdict'] != 'accept':
            out(self.style.WARNING(
                f"  기준 미달({qa['score']}점) — 원문을 그대로 둡니다. 발행된 글을 더 나쁜 "
                '판본으로 덮어쓰지 않습니다.'))
            for i in (qa.get('issues') or [])[:3]:
                out(f'    · {str(i)[:140]}')
            return

        if opts['dry_run']:
            out(self.style.WARNING(f'\n[dry-run] {qa["score"]}점 통과 — 저장하지 않았습니다.'))
            return

        q.subject, q.content = subject, content
        q.modify_date = timezone.now()
        q.save(update_fields=['subject', 'content', 'modify_date'])
        rec('editor', 'publish', f'리메이크 반영(제자리 갱신): {subject} (id={q.pk}, {qa["score"]}점)')
        out(self.style.SUCCESS(f'\n갱신 완료 — #{q.pk} {subject} ({qa["score"]}점)'))
        try:
            call_command('polish_logs', limit=12, verbosity=0)
        except Exception:  # noqa: BLE001
            pass
