"""
보류된 칼럼을 **운영자 코멘트를 반영해** 다시 쓰고 재심받는다.

  운영자 지시 + 직전 편집 심사·팩트체크 지적 → 칼럼니스트 재작성 → 팩트체크 → 시각화(없으면) → 편집 심사
  → Accept 면 발행, 아니면 다시 보류(운영자 검수)

보통은 /lab/admin/ 의 "코멘트 반영해 재작성" 버튼이 이 명령을 백그라운드로 실행한다.

사용법:
  python manage.py office_revise --draft 12 --note "사례를 국내 중심으로 바꾸고 2번 섹션을 줄여주세요"
  python manage.py office_revise --draft 12 --note "..." --publish-on-accept   (기본값: 켜짐)
  python manage.py office_revise --draft 12 --note "..." --no-publish          (심사만, 발행은 수동)
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from common.management.commands.auto_write_columns import COLUMN_STRUCTURE, TOPICS
from office import pipeline as P
from office.agents import AGENTS, TOPIC_AGENT
from office.models import ColumnDraft
from office.services import ask_agent, log


class Command(BaseCommand):
    help = '보류 칼럼을 운영자 코멘트대로 재작성하고 다시 심사합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--draft', type=int, required=True, help='ColumnDraft id')
        parser.add_argument('--note', default='', help='운영자 수정 지시 (없으면 저장된 admin_note 사용)')
        parser.add_argument('--by', default='', help='지시한 관리자 username (기록용)')
        parser.add_argument('--no-publish', action='store_true', help='Accept 여도 자동 발행하지 않음')

    def handle(self, *args, **opts):
        draft = ColumnDraft.objects.filter(pk=opts['draft']).first()
        if draft is None:
            raise CommandError(f"ColumnDraft {opts['draft']} 를 찾을 수 없습니다.")
        if draft.status == ColumnDraft.STATUS_PUBLISHED:
            raise CommandError('이미 발행된 칼럼입니다.')

        admin_note = (opts['note'] or draft.admin_note or '').strip()
        if not admin_note:
            raise CommandError('운영자 수정 지시(--note)가 필요합니다.')

        topic_key = draft.topic
        writer = TOPIC_AGENT[topic_key]
        label = TOPICS[topic_key]['label']
        out = self.stdout.write
        by = User.objects.filter(username=opts['by']).first() if opts['by'] else None

        def rec(agent, action, text):
            out(f'  [{AGENTS[agent]["name"]}] {text[:100]}')
            log(agent, action, text, draft=draft)

        draft.admin_note = admin_note
        draft.status = ColumnDraft.STATUS_REVISING
        draft.save(update_fields=['admin_note', 'status'])
        rec('lead', 'admin_note', f'운영자 수정 지시 접수: {admin_note[:150]}')

        try:
            recent = P.recent_titles(topic_key)
            prev_qa = draft.qa_report or {}
            prev_check = draft.check_report or {}

            # 1) 운영자 지시 반영 재작성
            raw = ask_agent(writer, P.ADMIN_REVISE_PROMPT.format(
                admin_note=admin_note,
                qa_issues='\n'.join(f'- {i}' for i in prev_qa.get('issues', [])) or '(없음)',
                check_notes=prev_check.get('notes', '') or '(없음)',
                subject=draft.subject, content=draft.content, structure=COLUMN_STRUCTURE), max_tokens=12000)
            subject, content, ok, why = P.safe_rewrite(raw, draft.subject, draft.content)
            if not ok:
                rec(writer, 'revise', f'재작성 실패 — {why}. 원고를 그대로 두고 검수 대기로 되돌립니다')
                draft.status = ColumnDraft.STATUS_HOLD
                draft.save(update_fields=['status'])
                return
            rec(writer, 'revise', f'운영자 지시 반영해 재작성: {subject} ({P.body_length(content)}자)')

            # 2) 팩트체크
            check = P.step_check(subject, content, recent)
            bad = [c for c in check.get('claims', []) if c.get('status') in ('unverifiable', 'wrong')]
            rec('checker', 'check', f"팩트체크 {check.get('verdict')}: 확인 필요 {len(bad)}건")

            # 3) 시각화 — 본문이 다시 쓰였으므로 이전 차트·표를 걷어내고 현재 수치로 새로 만든다
            content = P.strip_visual_block(content)
            content, chart_rel, chart_note = P.step_visual(content, topic_key, rec=rec)

            # 4) 재심
            qa = P.step_review(subject, content, check, chart_rel)
            verdict_ko = {'accept': '발행', 'minor': '수정 요청', 'major': '보류'}.get(qa['verdict'], qa['verdict'])
            rec('lead', 'qa', f"재심 {qa['score']}/100 ({qa['length']}자) → {verdict_ko}: {qa.get('notes', '')}")

            draft.subject, draft.content, draft.chart_path, draft.chart_note = subject, content, chart_rel, chart_note
            draft.check_report, draft.qa_report = check, qa
            draft.revisions += 1

            if qa['verdict'] == 'accept' and not opts['no_publish']:
                q = P.publish_draft(draft, by=by)
                rec('lead', 'publish', f'운영자 지시 반영 후 발행: {subject} (id={q.pk}, {qa["score"]}점)')
                out(self.style.SUCCESS(f'발행 완료 [{label}] {subject} (id={q.pk}, {qa["score"]}점)'))
            else:
                draft.status = ColumnDraft.STATUS_HOLD
                draft.save()
                out(self.style.WARNING(f'재작성 완료 — 여전히 검수 대기 [{label}] {subject} ({qa["score"]}점)'))

        except Exception as ex:  # noqa: BLE001
            draft.status = ColumnDraft.STATUS_HOLD
            draft.save(update_fields=['status'])
            log('lead', 'fail', f'재작성 실패: {str(ex)[:200]}', draft=draft)
            raise
