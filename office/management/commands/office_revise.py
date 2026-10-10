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
from office import live
from office import evidence as E
from office import pipeline as P
from office import review_protocol as R
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
        parser.add_argument('--review-only', action='store_true',
                            help='재작성 없이 심사만 다시 받는다(사람이 직접 교열한 원고용)')
        parser.add_argument('--content-file', default='', help='--review-only 때 쓸 교열본 마크다운 파일')
        parser.add_argument('--subject', default='', help='--review-only 때 바꿀 제목')
        parser.add_argument('--facts', default='', help='운영자가 원문을 확인한 사실 — 칼럼니스트·검증관·편집장에게 모두 전달')

    def handle(self, *args, **opts):
        # 어떻게 끝나든(발행·보류·실패) 연구실 라이브 표시를 정리한다
        try:
            return self._run(*args, **opts)
        finally:
            live.finish()

    def _run(self, *args, **opts):
        draft = ColumnDraft.objects.filter(pk=opts['draft']).first()
        if draft is None:
            raise CommandError(f"ColumnDraft {opts['draft']} 를 찾을 수 없습니다.")
        if draft.status == ColumnDraft.STATUS_PUBLISHED:
            raise CommandError('이미 발행된 칼럼입니다.')

        admin_note = (opts['note'] or draft.admin_note or '').strip()
        facts = (opts['facts'] or '').strip()
        review_only = opts['review_only']
        edited = None
        if opts['content_file']:
            if not review_only:
                raise CommandError('--content-file 은 --review-only 와 함께 씁니다.')
            with open(opts['content_file'], encoding='utf-8') as f:
                edited = f.read().strip() + '\n'
        if review_only:
            admin_note = admin_note or '운영자가 원고를 직접 교열했습니다.'
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
            # 근거 묶음 — 운영자 확인 사실 + 지난 팩트체크가 URL 과 함께 확인한 사실(office.evidence)
            pack = E.merge(facts, E.from_check(prev_check))

            if review_only:
                # 1') 사람이 직접 교열한 원고 — 재작성 없이 그대로 심사만 받는다.
                #     전체 재작성은 한 곳을 고치면 다른 곳에 새 반복이 생겨 수렴하지 않았다(원고 #8: 70→71→65).
                subject = (opts['subject'] or draft.subject).strip()
                content = edited if edited is not None else draft.content
                rec('lead', 'revise', f'운영자 직접 교열본으로 재심 요청: {subject} ({P.body_length(content)}자)')
            else:
                # 1) 운영자 지시 반영 재작성
                live.mark('revise', writer, topic_key)
                raw = ask_agent(writer, P.ADMIN_REVISE_PROMPT.format(
                    admin_note=admin_note + (f'\n\n[운영자가 원문을 확인한 사실 — 이것만 새로 쓸 수 있습니다]\n{facts}'
                                             if facts else ''),
                    qa_issues='\n'.join(f'- {i}' for i in R.revision_notes(prev_qa)) or '(없음)',
                    check_notes=prev_check.get('notes', '') or '(없음)',
                    subject=draft.subject, content=draft.content, structure=COLUMN_STRUCTURE,
                    standard=P.writing_standard(topic_key)) + P.pack_block(pack),
                    max_tokens=P.COLUMN_MAX_TOKENS)
                subject, content, ok, why = P.safe_rewrite(raw, draft.subject, draft.content)
                if not ok:
                    rec(writer, 'revise', f'재작성 실패 — {why}. 원고를 그대로 두고 검수 대기로 되돌립니다')
                    draft.status = ColumnDraft.STATUS_HOLD
                    draft.save(update_fields=['status'])
                    return
                rec(writer, 'revise', f'운영자 지시 반영해 재작성: {subject} ({P.body_length(content)}자)')

            # 2) 팩트체크
            check = P.step_check(subject, content, recent, verified=pack)
            bad = [c for c in check.get('claims', []) if c.get('status') in P.BAD_CLAIMS]
            rec('checker', 'check', f"팩트체크 {check.get('verdict')}: 확인 필요 {len(bad)}건")
            pack = E.merge(pack, E.from_check(check))
            if not review_only:
                # 재작성이 기억으로 들여온 새 수치는 지운다(이전 원고에 있던 수치는 그대로)
                content, dropped = P.lock_numbers(content, pack, baseline=draft.content)
                if dropped:
                    check = E.prune_check(check, content)
                    rec('checker', 'check', f'재작성이 들여온 근거 없는 수치 문장 {len(dropped)}개 삭제')

            # 3) 시각화 — 본문이 다시 쓰였으므로 이전 차트·표를 걷어내고 현재 수치로 새로 만든다.
            #    사람이 교열하며 기존 그림을 남겼으면 손대지 않는다(교열본을 그대로 심사받는 게 목적).
            #    교열본에 그림이 없어도 표가 있으면 그대로 심사받는다 — 예전엔 사람이 일부러 뺀 그림 자리에
            #    차트 담당이 옛 그림을 다시 넣어, 교열 의도와 다른 원고가 심사됐다(#36).
            if review_only and P.has_visual(content):
                keep_img = '![' in content and draft.chart_path
                chart_rel = draft.chart_path if keep_img else ''
                chart_note = draft.chart_note if keep_img else '운영자 교열본의 표를 핵심 도판으로 사용'
                visual_report = f'운영자 교열본 — 도판 그대로 심사: {chart_note}'
            else:
                content = P.strip_visual_block(content)
                content, chart_rel, chart_note, visual_report = P.step_visual(
                    content, topic_key, rec=rec, feedback=P.visual_feedback(draft.qa_report))

            # 4) 재심
            critique = P.step_critique(subject, content)
            rec('critic', 'critique', f"평론 {critique['verdict']} · 지적 {len(critique.get('issues') or [])}건: "
                                      f"{critique.get('reason', '')[:100]}")
            qa = P.step_review(subject, content, check, chart_rel, visual_report, critique, verified=pack,
                               previous=draft.qa_report or None, previous_content=draft.content)
            verdict_ko = {'accept': '발행', 'minor': '수정 요청', 'major': '보류'}.get(qa['verdict'], qa['verdict'])
            rec('editor', 'qa', f"재심 {qa['score']}/100 ({qa['length']}자) → {verdict_ko}: {qa.get('notes', '')}")

            draft.subject, draft.content, draft.chart_path, draft.chart_note = subject, content, chart_rel, chart_note
            draft.check_report, draft.qa_report = check, qa
            draft.revisions += 1

            if qa['verdict'] == 'accept' and not opts['no_publish']:
                keywords = P.headline_keywords((draft.decision.chosen or {}) if draft.decision else {})
                new_title, why = P.step_headline(subject, content, keywords=keywords, recent=recent)
                if new_title != subject:
                    rec('editor', 'headline', f'제목 다듬기: 「{subject}」 → 「{new_title}」 — {why}'[:300])
                    subject = draft.subject = new_title
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
