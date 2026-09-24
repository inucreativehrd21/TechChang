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

            # 1) 기획서
            brief = P.step_brief(topic_key, brief_decision, recent)
            rec('lead', 'brief', f"집필 의뢰서: {brief.get('angle', '')[:120]}")

            # 2) 집필
            subject, content = P.step_draft(topic_key, brief_decision, brief, recent)
            rec(writer, 'draft', f'초안 완성: {subject} ({P.body_length(content)}자)')

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

            # 5) 데이터 시각화
            chart_rel, chart_note = '', '옵션으로 생략(--no-chart)'
            if not opts['no_chart']:
                content, chart_rel, chart_note = P.step_visual(content, topic_key, rec=rec, dry=dry)

            # 6) 편집 심사 → 7) 판정 (Minor 는 자동 1회 재작성 후 재심)
            qa = P.step_review(subject, content, check, chart_rel)
            rec('lead', 'qa', self._qa_line(qa))
            if qa['verdict'] == 'minor' and revisions < P.MAX_AUTO_REVISIONS + 1:
                raw = ask_agent(writer, P.EDITOR_REVISE_PROMPT.format(
                    issues='\n'.join(f'- {i}' for i in qa.get('issues', [])), notes=qa.get('notes', ''),
                    subject=subject, content=content, structure=COLUMN_STRUCTURE), max_tokens=8000)
                subject, content = P.parse_output(raw)
                revisions += 1
                rec(writer, 'revise', f'편집 심사 지적 반영해 재작성 ({P.body_length(content)}자)')
                if not P.has_visual(content) and not opts['no_chart']:
                    content, chart_rel, chart_note = P.step_visual(content, topic_key, rec=rec, dry=dry)
                qa = P.step_review(subject, content, check, chart_rel)
                # 재심에서는 '수정 요청'을 통과로 본다 (학술지의 minor revision 수리와 같은 처리).
                # 치명 결함이 남아 있으면 verdict 가 major 라 그대로 보류된다.
                if qa['verdict'] == 'minor':
                    qa['verdict'] = 'accept'
                    qa['accepted_after_revision'] = True
                rec('lead', 'qa', '재심 ' + self._qa_line(qa))

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

        except Exception as ex:  # noqa: BLE001 — 실패도 기록해 연구실에 보이게
            if draft:
                draft.status = ColumnDraft.STATUS_FAILED
                draft.save(update_fields=['status'])
                log('lead', 'fail', f'{label} 제작 실패: {str(ex)[:200]}', draft=draft)
            raise

    @staticmethod
    def _qa_line(qa: dict) -> str:
        v = {'accept': '발행', 'minor': '수정 요청', 'major': '보류(운영자 검수)'}.get(qa['verdict'], qa['verdict'])
        fatal = f" · 치명결함 {','.join(qa['fatal'])}" if qa.get('fatal') else ''
        return f"편집 심사 {qa['score']}/100 ({qa['length']}자){fatal} → {v}: {qa.get('notes', '')}"
