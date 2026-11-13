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
from contextlib import nullcontext

from common.management.commands.auto_write_columns import TOPICS
from office import genres as G
from office import live
from office import evidence as E
from office import pipeline as P
from office import review_protocol as R
from office import schedule as S
from office.agents import AGENTS, TOPIC_AGENT
from office.models import ColumnDraft
from office.services import ask_agent, log
from office.run_context import bounded_run
from office.recorder import StageRecorder


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
            from office.editorial import use_track
            track = ColumnDraft.objects.filter(pk=opts['draft']).values_list('column_track', flat=True).first() or ''
            with use_track(track):
                return self._run(*args, **opts)
        finally:
            live.finish()

    @bounded_run
    def _run(self, *args, **opts):
        draft = ColumnDraft.objects.filter(pk=opts['draft']).first()
        if draft is None:
            raise CommandError(f"ColumnDraft {opts['draft']} 를 찾을 수 없습니다.")
        if draft.status == ColumnDraft.STATUS_PUBLISHED:
            raise CommandError('이미 발행된 칼럼입니다.')
        from office.run_context import current
        if current():
            current().metadata(draft_id=draft.pk, topic=draft.topic, column_track=draft.column_track)
        if not draft.content.strip() and not opts['content_file']:
            raise CommandError('재심할 본문이 비어 있어요. 제작 기록에서 원고를 복구한 뒤 다시 요청해 주세요.')

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
        stages = StageRecorder(draft=draft)

        def rec(agent, action, text):
            out(f'  [{AGENTS[agent]["name"]}] {text[:100]}')
            log(agent, action, text, draft=draft)

        draft.admin_note = admin_note
        draft.status = ColumnDraft.STATUS_REVISING
        draft.save(update_fields=['admin_note', 'status'])
        rec('lead', 'admin_note', f'운영자 수정 지시 접수: {admin_note[:150]}')

        revision = None
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
                # 요청에 연결된 편집만 적용하고, 독립 검증으로 빠진 요구를 확인한다.
                from office.revision_requests import RevisionRequests
                genre = G.genre_for(topic_key, content=draft.content)
                live.mark('revise', writer, topic_key)
                revision = RevisionRequests(draft, admin_note, writer, stages,
                    guide=G.structure(genre)+'\n'+P.writing_standard(topic_key, genre)
                    +P.pack_block(pack)+'\n[참고: 기존 필수 지적]\n'+'\n'.join(R.revision_notes(prev_qa)))
                candidate = revision.generate()
                if candidate is None:
                    revision.retain()
                    rec(writer, 'hold', '수정 요청의 반영을 확인하지 못해 기존 원고를 유지해요.')
                    return
                subject, content = candidate
                rec(writer, 'revise', f'요청별 편집 후보 검증: {subject} ({P.body_length(content)}자)')

            # 2) 팩트체크
            check = P.step_check(subject, content, recent, verified=pack)
            stages.record('check', 'checker', check)
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
            render_requested = revision and any(r.get('visual_action') == 'render' for r in revision.requirements)
            if render_requested:
                content = P.strip_visual_block(content)
                content, chart_rel, chart_note, visual_report = P.step_visual(
                    content, topic_key, rec=rec, feedback=admin_note+'\n'+'\n'.join(
                        r['request']+' / 완료 기준: '+r['done_when'] for r in revision.requirements
                        if r.get('visual_action') == 'render'))
            elif P.has_visual(content):
                keep_img = draft.chart_path and '/media/'+draft.chart_path in content
                chart_rel = draft.chart_path if keep_img else ''
                chart_note = draft.chart_note if keep_img else '수정본의 표를 핵심 도판으로 사용'
                visual_report = f'수정본 — 도판 그대로 심사: {chart_note}'
            elif revision:
                # 요청으로 지운 도판을 자동 생성으로 되살리지 않는다.
                chart_rel, chart_note, visual_report = '', '수정 요청의 도판 구성을 유지해요.', '도판 없음'
            else:
                content = P.strip_visual_block(content)
                content, chart_rel, chart_note, visual_report = P.step_visual(
                    content, topic_key, rec=rec, feedback=P.visual_feedback(draft.qa_report))

            if review_only and not opts['no_publish']:
                keywords = P.headline_keywords((draft.decision.chosen or {}) if draft.decision else {})
                subject, _why = P.step_headline(subject, content, keywords=keywords, recent=recent)
            if check.get('subject') != subject or check.get('verification_hash') != P.verification_hash(content):
                check = P.step_check(subject, content, recent, verified=pack)
                stages.record('recheck', 'checker', check)

            # 4) 재심
            critique = P.step_critique(subject, content)
            rec('critic', 'critique', f"평론 {critique['verdict']} · 지적 {len(critique.get('issues') or [])}건: "
                                      f"{critique.get('reason', '')[:100]}")
            qa = P.step_review(subject, content, check, chart_rel, visual_report, critique, verified=pack,
                               previous=draft.qa_report or None, previous_content=draft.content)
            if revision and not revision.finish(subject, content, qa, check):
                rec('editor', 'hold', '미반영·품질 하락으로 보완본을 채택하지 않고 기존 원고를 유지해요.')
                out(self.style.WARNING('수정 결과 보류 — 요청별 결과를 확인해 주세요. 기존 원고를 유지했어요.'))
                return
            stages.record('review', 'editor', qa)
            stages.complete(subject, content, check, qa)
            verdict_ko = {'accept': '발행', 'minor': '수정 요청', 'major': '보류'}.get(qa['verdict'], qa['verdict'])
            rec('editor', 'qa', f"재심 {qa['score']}/100 ({qa['length']}자) → {verdict_ko}: {qa.get('notes', '')}")

            with revision.commit() if revision else nullcontext():
                draft.subject, draft.content, draft.chart_path, draft.chart_note = subject, content, chart_rel, chart_note
                draft.check_report, draft.qa_report = check, qa
                draft.revisions += 1

                if qa['verdict'] == 'accept' and not opts['no_publish']:
                    q = S.finish_accepted(draft, P.publish_draft, by=by)
                    if draft.status == ColumnDraft.STATUS_HOLD:
                        rec('lead', 'hold', '재작성 심사를 통과했어요. 새 원고의 승인을 기다려요.')
                        return
                    if q is None:
                        rec('lead', 'ready', S.ready_line(draft))
                        out(self.style.SUCCESS(f'공개 대기 [{label}] {subject} ({qa["score"]}점)'))
                    else:
                        rec('lead', 'publish', f'운영자 지시 반영 후 발행: {subject} (id={q.pk}, {qa["score"]}점)')
                        out(self.style.SUCCESS(f'발행 완료 [{label}] {subject} (id={q.pk}, {qa["score"]}점)'))
                else:
                    draft.status = ColumnDraft.STATUS_HOLD
                    draft.save()
                    out(self.style.WARNING(f'재작성 완료 — 여전히 검수 대기 [{label}] {subject} ({qa["score"]}점)'))

        except Exception as ex:  # noqa: BLE001
            if revision:
                revision.retain('수정 작업을 완료하지 못했어요: '+str(ex))
                stages.record('fail', 'lead', {'reason': str(ex)[:300]}, status='failed')
            draft.status = ColumnDraft.STATUS_HOLD
            draft.save(update_fields=['status'])
            log('lead', 'fail', f'재작성 실패: {str(ex)[:200]}', draft=draft)
            raise
