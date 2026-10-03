"""
연구팀 칼럼 제작 — 편집 조직 절차 그대로 (office/pipeline.py 의 단계 정의를 실행).

  기획서(팀장) → 집필(칼럼니스트) → 팩트체크(검증관) → [수정] → 데이터 시각화(차트 담당)
  → 편집 심사(팀장 루브릭 100점) → Accept 발행 / Minor 자동 1회 재작성 후 재심 / Major 보류

주제는 주간 회의에서 관리자가 고른 안건(Decision)을 우선 사용하고, 없으면 칼럼니스트가 직접 고른다.

사용법:
  python manage.py office_publish --topic hrd
  python manage.py office_publish --topic data --dry-run      # DB 저장 없이 콘솔 출력
  python manage.py office_publish --topic coding --no-chart

cron:
  0 10 * * 2  .../python manage.py office_publish --topic hrd
  0 10 * * 4  .../python manage.py office_publish --topic data
  0 10 * * 6  .../python manage.py office_publish --topic coding
"""
import json

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from common.management.commands.auto_write_columns import COLUMN_STRUCTURE, TOPICS
from office import pipeline as P
from office.agents import AGENTS, TOPIC_AGENT
from office.models import ColumnDraft
from office.services import ask_agent, log, take_column_brief


class Command(BaseCommand):
    help = '연구팀이 칼럼 1편을 기획·집필·검증·시각화·심사 후 발행(또는 보류)합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', choices=['hrd', 'data', 'coding'], required=True)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-chart', action='store_true')

    def handle(self, *args, **opts):
        topic_key = opts['topic']
        dry = opts['dry_run']
        writer = TOPIC_AGENT[topic_key]
        wname = AGENTS[writer]['name']
        label = TOPICS[topic_key]['label']
        out = self.stdout.write

        brief_decision = take_column_brief(topic_key)
        draft = None if dry else ColumnDraft.objects.create(
            topic=topic_key, decision=brief_decision, status=ColumnDraft.STATUS_FAILED,
            brief=(brief_decision.chosen or {}).get('title', '') if brief_decision else '')

        def rec(agent, action, text):
            out(f'  [{AGENTS[agent]["name"]}] {text[:100]}')
            if not dry:
                log(agent, action, text, draft=draft)

        try:
            recent = P.recent_titles(topic_key)
            out(f'[{timezone.localtime():%H:%M:%S}] {label} — 제작 시작'
                + (f' (회의 주제: {draft.brief})' if draft and draft.brief else ' (회의 결정 없음)'))

            # 1) 기획서 (팀장 지시 + 데이터 담당이 필요한 지표 제시)
            brief = P.step_brief(topic_key, brief_decision, recent, rec=rec)
            rec('lead', 'brief', f"집필 의뢰서: {brief.get('angle', '')[:120]}")

            # 2) 집필 → 자동 점검(코드) → 필요하면 즉시 보완
            #    분량·문체·섹션·수치처럼 기계로 판별되는 결함을 여기서 잡는다. 팩트체크·평론·
            #    심사는 전부 모델 호출이라, 거기까지 끌고 가면 호출 세 번을 더 태운 뒤에야
            #    재작성에 들어간다.
            subject, content = P.step_draft(topic_key, brief_decision, brief, recent)
            rec(writer, 'draft', f'초안 완성: {subject} ({P.body_length(content)}자)')
            flaws = P.precheck_draft(content)
            if flaws:
                rec('editor', 'precheck', f'초안 자동 점검 {len(flaws)}건: {flaws[0][:90]}')
                subject, content, flaws = P.step_fix_draft(topic_key, subject, content, flaws)
                rec(writer, 'revise', f'자동 점검 지적 반영 ({P.body_length(content)}자)'
                    + (f' · 남은 지적 {len(flaws)}건' if flaws else ' · 모두 해소'))
            else:
                rec('editor', 'precheck', '초안 자동 점검 통과')

            # 3) 팩트체크 → 4) 수정
            check = P.step_check(subject, content, recent)
            bad = [c for c in check.get('claims', []) if c.get('status') in ('unverifiable', 'wrong')]
            rec('checker', 'check', f"팩트체크 {check.get('verdict')}: 확인 필요 {len(bad)}건"
                + (', 기존 칼럼과 중복' if check.get('duplicate') else ''))
            revisions = 0
            if check.get('verdict') == 'revise':
                subject, content, ok, why = P.step_author_revise(topic_key, subject, content, check)
                if ok:
                    revisions = 1
                    rec(writer, 'revise', f'팩트체크 {len(bad)}건 반영해 재작성 ({P.body_length(content)}자)')
                    check2 = P.step_check(subject, content, recent)
                    check = {'first': check, **check2}
                    rec('checker', 'check', f"재검증 {check2.get('verdict')}")
                else:
                    rec(writer, 'revise', f'재작성 실패 — {why}')

            # 5) 평론 — 읽을 이유가 있는 글인지
            critique = P.step_critique(subject, content)
            rec('critic', 'critique', self._critique_line(critique))

            # 6) 데이터 시각화
            chart_rel, chart_note, visual_report = '', '옵션으로 생략(--no-chart)', ''
            if not opts['no_chart']:
                content, chart_rel, chart_note, visual_report = P.step_visual(
                    content, topic_key, rec=rec, dry=dry)

            # 7) 편집 심사 → 8) 판정 (기준 미달이면 자동 1회 재작성 후 재심, 그 뒤는 사람 검수)
            qa = P.step_review(subject, content, check, chart_rel, visual_report, critique)
            rec('editor', 'qa', self._qa_line(qa))
            # 기준 미달이면 — 보류든 수정 요청이든 — 자동으로 **한 번만** 다시 쓴다.
            # 편집장 지적과 팩트체크 보고를 함께 물려 준다. 그 뒤로는 사람이 보고
            # /lab/admin/ 에서 수정 지시를 내리는 기존 흐름으로 넘어간다.
            if qa['verdict'] in ('minor', 'major'):
                raw = ask_agent(writer, P.EDITOR_REVISE_PROMPT.format(
                    issues='\n'.join(f'- {i}' for i in qa.get('issues', [])), notes=qa.get('notes', ''),
                    check=P.check_text(check), critique=P.critique_text(critique),
                    subject=subject, content=content, structure=COLUMN_STRUCTURE,
                    standard=P.WRITING_STANDARD.format(min_chars=P.MIN_CHARS, rubric=P.rubric_text())),
                    max_tokens=P.COLUMN_MAX_TOKENS)
                subject, content = P.parse_output(raw)
                revisions += 1
                rec(writer, 'revise', f'편집 심사 지적 반영해 재작성 ({P.body_length(content)}자)')
                # 본문이 통째로 다시 쓰였으므로 도판도 다시 만든다. 옛 블록을 남겨 두면
                # 표의 숫자만 고쳐지고 그림은 예전 수치 그대로 남는다.
                if not opts['no_chart']:
                    content = P.strip_visual_block(content)
                    content, chart_rel, chart_note, visual_report = P.step_visual(
                        content, topic_key, rec=rec, dry=dry)
                critique = P.step_critique(subject, content)
                rec('critic', 'critique', '재검토 ' + self._critique_line(critique))
                qa = P.step_review(subject, content, check, chart_rel, visual_report, critique)
                # 재심에서는 '수정 요청'을 통과로 본다 (학술지의 minor revision 수리와 같은 처리).
                # 치명 결함이 남아 있으면 verdict 가 major 라 그대로 보류된다.
                if qa['verdict'] == 'minor':
                    qa['verdict'] = 'accept'
                    qa['accepted_after_revision'] = True
                rec('editor', 'qa', '재심 ' + self._qa_line(qa))

            if dry:
                out('=' * 60 + f'\nTITLE: {subject}\n' + content[:2000] + '\n' + '=' * 60)
                out(json.dumps({'brief': brief, 'chart': chart_note, 'qa': qa}, ensure_ascii=False, indent=1)[:2500])
                return

            draft.subject, draft.content, draft.chart_path = subject, content, chart_rel
            draft.check_report, draft.qa_report, draft.revisions = check, qa, revisions
            draft.chart_note = chart_note

            if qa['verdict'] == 'accept':
                q = P.publish_draft(draft)
                rec('lead', 'publish', f'발행: {subject} (id={q.pk}, {qa["score"]}점)')
                out(self.style.SUCCESS(f'발행 완료 [{label}] {subject} (id={q.pk}, {qa["score"]}점)'))
            else:
                draft.status = ColumnDraft.STATUS_HOLD
                draft.save()
                rec('lead', 'hold', f'보류({qa["verdict"]}, {qa["score"]}점): {subject} — 운영자 검수 대기')
                out(self.style.WARNING(f'보류 [{label}] {subject} — /lab/admin/ 에서 검수'))

            # 이번에 쌓인 활동 기록을 공개용 말투로 다듬어 둔다. 연구실 페이지가 폴링하므로
            # 조회 시점에 만들 수 없고, 여기서 한 번(한 호출) 처리한다. 실패해도 본작업과
            # 무관하므로 틀 문장으로 넘어간다.
            try:
                call_command('polish_logs', limit=24, verbosity=0)
            except Exception as ex:  # noqa: BLE001
                out(self.style.WARNING(f'활동 문장 다듬기 건너뜀: {str(ex)[:120]}'))

        except Exception as ex:  # noqa: BLE001 — 실패도 기록해 연구실에 보이게
            if draft:
                draft.status = ColumnDraft.STATUS_FAILED
                draft.save(update_fields=['status'])
                log('lead', 'fail', f'{label} 제작 실패: {str(ex)[:200]}', draft=draft)
            raise

    @staticmethod
    def _critique_line(cr: dict) -> str:
        ko = {'recommend': '추천', 'revise': '수정 후 재검토', 'reject': '반대'}
        head = f"평론 {ko.get(cr['verdict'], cr['verdict'])}"
        issues = cr.get('issues') or []
        if issues:
            head += f" · 지적 {len(issues)}건 — 「{issues[0]['quote'][:32]}」 {issues[0]['why'][:60]}"
        return f"{head}: {cr.get('reason', '')[:100]}"

    @staticmethod
    def _qa_line(qa: dict) -> str:
        v = {'accept': '발행', 'minor': '수정 요청', 'major': '보류(운영자 검수)'}.get(qa['verdict'], qa['verdict'])
        fatal = f" · 치명결함 {','.join(qa['fatal'])}" if qa.get('fatal') else ''
        return f"편집 심사 {qa['score']}/100 ({qa['length']}자){fatal} → {v}: {qa.get('notes', '')}"
