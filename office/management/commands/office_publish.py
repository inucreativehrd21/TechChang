"""
연구팀 칼럼 제작 — 편집 조직 절차 그대로 (office/pipeline.py 의 단계 정의를 실행).

  기획서(팀장 은혜 + 지표 재원) → 집필(칼럼니스트) → 자동 점검 → 팩트체크(검증관 하경) → [수정]
  → 평론(평론가 예원) → 데이터 시각화(재원) → 편집 심사(편집장 승현, 루브릭 100점)
  → Accept 발행 / 기준 미달이면 자동 재작성(MAX_AUTO_REVISIONS 회) 후 재심 / 그래도 미달이면 보류

주제는 주간 회의에서 관리자가 고른 안건(Decision)을 우선 사용하고, 없으면 칼럼니스트가 직접 고른다.
단계마다 산출물을 StageRun 에 남긴다(내부 전용) — 평론·1차 심사·초고가 덮어써져 사라지지 않게.

사용법:
  python manage.py office_publish --topic hrd
  python manage.py office_publish --topic data --dry-run      # DB 저장 없이 콘솔 출력
  python manage.py office_publish --topic data --no-publish   # 끝까지 만들되 발행하지 않고 보류로 저장(검증용)
  python manage.py office_publish --topic coding --no-chart
  python manage.py office_publish --topic hrd --prepare      # 다음 공개 시각 몫을 미리 만들어 '공개 대기'로
  python manage.py office_publish --topic hrd --if-missing   # 오늘 공개 몫이 아예 없을 때만 바로 만든다

cron (예약 공개 — office/schedule.py):
  0 13 * * 1  ... office_publish --topic hrd --prepare        # 전날 13시 준비, 22시 재시도(실패했을 때만)
  0 22 * * 1  ... office_publish --topic hrd --prepare
  0 4 * * 2   ... office_publish --topic hrd --prepare        # 당일 4시 — 밤사이 구독 한도가 풀린 뒤 한 번 더
  0 10 * * 2  ... office_publish --topic hrd --if-missing     # 당일 안전망
  (data: 수 13·22시 / 목 10시, coding: 금 13·22시 / 토 10시)
  */10 * * * * ... office_release                              # 예정 시각이 지난 공개 대기 원고 발행
"""
import json
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from pathlib import Path

from common.management.commands.auto_write_columns import TOPICS
from office import genres as G
from office import grounded as GR
from office import sources as SRC
from common.services.claude import call_tags, track_calls
from office import live
from office import pipeline as P
from office import quality
from office import blueprint as B
from office import review_protocol as R
from office import evidence as E
from office import schedule as S
from office.patching import patch_revise
from office.agents import AGENTS, TOPIC_AGENT
from office.models import ColumnDraft
from office.recorder import StageRecorder
from office.services import ask_agent, log, take_column_brief
from office.model_router import profile, use_profile
from office.run_context import run_context, current, RunBudgetExceeded
from office.review_batch import run as review_batch, ReviewIncomplete


class Command(BaseCommand):
    help = '연구팀이 칼럼 1편을 기획·집필·검증·시각화·심사 후 발행(또는 보류)합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', choices=['hrd', 'data', 'coding'], required=True)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--profile', choices=['legacy', 'a', 'b'])
        parser.add_argument('--resume-run', help='B안 체크포인트 UUID. 동일 원고의 완료 응답을 재사용해요.')
        parser.add_argument('--no-chart', action='store_true')
        parser.add_argument('--no-publish', action='store_true',
                            help='심사를 통과해도 발행하지 않고 보류로 저장 (로컬 검증용)')
        parser.add_argument('--prepare', action='store_true',
                            help='다음 공개 시각 몫을 미리 만든다 — 통과하면 공개 대기, 미달이면 보류 + 운영자 메일')
        parser.add_argument('--if-missing', action='store_true',
                            help='오늘 공개 시각 몫의 원고가 없을 때만 만든다(당일 안전망)')

    def handle(self, *args, **opts):
        # 어떻게 끝나든(발행·보류·실패) 연구실 라이브 표시를 정리한다
        try:
            with use_profile(opts.get('profile') or profile()):
                if opts.get('resume_run') and profile() != 'b':
                    raise ValueError('체크포인트 재개는 B 프로필에서만 가능해요.')
                if opts.get('resume_run') and opts['dry_run']:
                    raise ValueError('dry-run은 체크포인트를 저장하거나 재개하지 않아요.')
                checkpoint_root = Path(settings.BASE_DIR)/'logs/lab-runs'
                if opts.get('resume_run'):
                    from uuid import UUID
                    resume_id = str(UUID(opts['resume_run']))
                    if not (checkpoint_root/(resume_id+'.json')).exists():
                        raise ValueError('재개할 연구실 체크포인트가 없어요.')
                with run_context(run_id=opts.get('resume_run'), root=checkpoint_root,
                                 dry=opts['dry_run']) as context:
                    if context:
                        self.stdout.write('연구 실행: ' + context.run_id)
                    return self._run(*args, **opts)
        finally:
            live.finish()

    def _run(self, *args, **opts):
        topic_key = opts['topic']
        dry = opts['dry_run']
        context = current()
        saved = context.data['metadata'] if context else {}
        if saved.get('topic') and saved['topic'] != topic_key:
            raise ValueError('체크포인트의 원고 주제와 요청이 달라요.')
        writer = TOPIC_AGENT[topic_key]
        label = TOPICS[topic_key]['label']
        out = self.stdout.write

        prepare = opts.get('prepare')
        slot = None
        if (prepare or opts.get('if_missing')) and not saved.get('draft_id'):
            slot = S.column_slot(topic_key, upcoming=bool(prepare))
            if slot is None:
                out(f'{label} — 오늘은 공개 요일이 아닙니다. 건너뜁니다.')
                return
            have = S.taken(slot, topic=topic_key)
            if have is not None:
                out(f'{label} — {timezone.localtime(slot):%m.%d %H:%M} 몫이 이미 있습니다'
                    f'({have.get_status_display()}: {have.subject or have.brief}). 건너뜁니다.')
                return

        if saved.get('draft_id') and not dry:
            draft = ColumnDraft.objects.get(pk=saved['draft_id'], topic=topic_key)
            if draft.status in (ColumnDraft.STATUS_PUBLISHED, ColumnDraft.STATUS_READY):
                raise ValueError('이미 발행되거나 공개 대기 중인 실행은 재개하지 않아요.')
            brief_decision = draft.decision
        else:
            brief_decision = take_column_brief(topic_key)
            draft = None if dry else ColumnDraft.objects.create(
                topic=topic_key, decision=brief_decision, status=ColumnDraft.STATUS_FAILED, publish_at=slot,
                brief=(brief_decision.chosen or {}).get('title', '') if brief_decision else '')
        if context:
            context.metadata(topic=topic_key, draft_id=draft.pk if draft else None)
        stages = StageRecorder(draft=draft, dry=dry, run_id=context.run_id if context else None)

        def rec(agent, action, text):
            out(f'  [{AGENTS[agent]["name"]}] {text[:100]}')
            if not dry:
                log(agent, action, text, draft=draft)

        def timed(stage, agent, fn, **kw):
            """단계를 실행하고 결과·소요 시간을 기록한다. 호출에는 단계 꼬리표가 붙는다."""
            started = time.monotonic()
            with call_tags(run_id=str(stages.run_id), stage=stage), \
                    track_calls(alert=False, filter={'run_id': str(stages.run_id), 'stage': stage}) as calls:
                result = fn()
            kw.setdefault('output', result if isinstance(result, (dict, list)) else None)
            kw.setdefault('calls', list(calls))
            stages.record(stage, agent, seconds=round(time.monotonic() - started, 1), **kw)
            return result

        try:
            recent = P.recent_titles(topic_key)
            out(f'[{timezone.localtime():%H:%M:%S}] {label} — 제작 시작'
                + (f' (회의 주제: {draft.brief})' if draft and draft.brief else ' (회의 결정 없음)'))

            # 1) 기획서 (팀장 지시 + 데이터 담당이 필요한 지표 제시)
            brief = timed('brief', 'lead', lambda: P.step_brief(topic_key, brief_decision, recent, rec=rec),
                          kind='commission', sender='lead', recipient=writer)
            rec('lead', 'brief', f"집필 의뢰서: {brief.get('angle', '')[:120]}")
            # 코드가 공식 API 로 직접 받은 통계는 검증관·편집장에게 확인 사실로 넘긴다
            facts = P.brief_facts(brief)
            genre = G.genre_for(topic_key, brief)  # 장르별 구조(office.genres) — 집필·점검·심사·재작성이 같은 틀을 쓴다

            # 2) 집필 → 자동 점검(코드) → 필요하면 즉시 보완
            #    분량·문체·섹션·수치처럼 기계로 판별되는 결함을 여기서 잡는다. 팩트체크·평론·
            #    심사는 전부 모델 호출이라, 거기까지 끌고 가면 호출 세 번을 더 태운 뒤에야
            #    재작성에 들어간다.
            # 1.5) 설계도 → 검증관 사전 검증 — 본문 쓰기 전에 주장·근거·핵심 표를 확정한다(office.blueprint)
            bp, ver = timed('blueprint', writer, lambda: P.step_blueprint(topic_key, brief_decision, brief, recent),
                            kind='report', sender='checker', recipient=writer)
            self._update_last(stages, {'blueprint': bp, 'verification': ver})
            if bp:
                rec(writer, 'blueprint', B.summary(bp, ver))
            # 근거 묶음 — 원문 문장으로 확인된 사실. 본문 수치는 여기에 묶인다(office.evidence)
            pack = E.merge(facts, ver.get('pack', ''))
            # 원장 — 원문 발췌가 있는 확인 결과. B의 사실 관문은 웹 대신 이것과 대조한다(office.grounded)
            ledger_rows = list(ver.get('claims') or [])
            corpus = SRC.Corpus()     # 원고가 기대는 공식 문서 — 코드가 받아 문단으로(토큰 0, office.sources)
            detail = str(((brief_decision.chosen or {}) if brief_decision else {}).get('detail', ''))

            def evidence():
                corpus.add(SRC.urls_in(*(str(r.get('url') or '') for r in ledger_rows), detail, content))
                return GR.entries(ledger_rows, code_facts=pack, documents=SRC.entries(corpus.select(content)))
            subject, content = timed('draft', writer,
                                     lambda: P.step_draft(topic_key, brief_decision, brief, recent,
                                                          blueprint=B.block(bp, ver)))
            self._update_last(stages, {'subject': subject, 'content': content}, text=content)
            rec(writer, 'draft', f'초안 완성: {subject} ({P.body_length(content)}자)')
            flaws = P.precheck_draft(content, pack, genre)
            stages.record('precheck', 'editor', {'issues': flaws, 'quality': quality.report(subject, content),
                                                 'genre': genre})
            if flaws and profile() != 'b':
                rec('editor', 'precheck', f'초안 자동 점검 {len(flaws)}건: {flaws[0][:90]}')
                subject, content, flaws = timed('fix', writer,
                                                lambda: P.step_fix_draft(topic_key, subject, content, flaws, pack,
                                                                         genre))
                self._update_last(stages, {'subject': subject, 'content': content, 'remaining': flaws},
                                  text=content)
                rec(writer, 'revise', f'자동 점검 지적 반영 ({P.body_length(content)}자)'
                    + (f' · 남은 지적 {len(flaws)}건' if flaws else ' · 모두 해소'))
            elif not flaws:
                rec('editor', 'precheck', '초안 자동 점검 통과')
            else:
                rec('editor', 'precheck', '자동 점검 지적을 첫 통합 심사에 모아 한 번에 수정해요.')
            pack = self._code_facts(stages, rec, content, pack)
            if profile() == 'b' and genre == 'tutorial':
                subject, content, pack = self._run_first(stages, rec, timed, topic_key, writer, subject, content,
                                                         pack, genre)

            # 3) 팩트체크 → 4) 수정
            parallel_reviews = {}
            reviewed_content = content
            if profile() == 'b':
                tasks = {'check': ('checker', lambda: P.step_check(subject, content, recent, verified=pack,
                                                                   evidence=evidence())),
                         'critique': ('critic', lambda: P.step_critique(subject, content))}
                parallel_reviews = review_batch(tasks, stages=stages)
                check = parallel_reviews['check']
                from office.ledger import record as record_facts
                record_facts(check)
                ledger_rows += check.get('claims') or []
            else:
                check = timed('check', 'checker', lambda: P.step_check(subject, content, recent, verified=pack),
                              kind='report', sender='checker', recipient='editor')
            bad = [c for c in check.get('claims', []) if c.get('status') in P.BAD_CLAIMS]
            rec('checker', 'check', f"팩트체크 {check.get('verdict')}: 확인 필요 {len(bad)}건"
                + (', 기존 칼럼과 중복' if check.get('duplicate') else ''))
            revisions = 0
            if check.get('verdict') == 'revise' and profile() != 'b':
                res = timed('revise', writer, lambda: P.step_author_revise(topic_key, subject, content, check))
                subject, content, ok, why = res
                self._update_last(stages, {'subject': subject, 'content': content, 'ok': ok, 'why': why},
                                  text=content, status='ok' if ok else 'failed')
                if ok:
                    revisions = 1
                    rec(writer, 'revise', f'팩트체크 {len(bad)}건 반영해 재작성 ({P.body_length(content)}자)')
                    check2 = timed('recheck', 'checker', lambda: P.step_check(subject, content, recent, verified=pack))
                    check = {'first': check, **check2}
                    rec('checker', 'check', f"재검증 {check2.get('verdict')}")
                else:
                    rec(writer, 'revise', f'재작성 실패 — {why}')

            # 4.5) 수치 잠금 — 팩트체크가 새로 확인한 근거까지 묶음에 더하고, 그래도 묶음에 없는 수치의 문장은 지운다.
            #      기억으로 쓴 숫자 하나가 심사에서 치명 결함(확인 불가)이 되는 것을 여기서 끊는다(#89·#100).
            pack = E.merge(pack, E.from_check(check))
            content, dropped = P.lock_numbers(content, pack) if profile() != 'b' else (content, [])
            if dropped:
                check = E.prune_check(check, content)
                stages.record('lock', 'checker', {'removed': dropped}, text=content)
                rec('checker', 'check', f'근거 없는 수치 문장 {len(dropped)}개 삭제: {dropped[0][:60]}')

            # 5) 평론 — 읽을 이유가 있는 글인지
            if profile() == 'b':
                if P.verification_hash(reviewed_content) != P.verification_hash(content):
                    tasks = {'check': ('checker', lambda: P.step_check(subject, content, recent, verified=pack,
                                         previous=check, previous_content=reviewed_content, evidence=evidence())),
                             'critique': ('critic', lambda: P.step_critique(subject, content))}
                    parallel_reviews = review_batch(tasks, stages=stages, attempt=2)
                    check = parallel_reviews['check']
                    record_facts(check)
                    ledger_rows += check.get('claims') or []
                critique = parallel_reviews['critique']
            else:
                critique = timed('critique', 'critic', lambda: P.step_critique(subject, content),
                                 kind='report', sender='critic', recipient='editor')
            rec('critic', 'critique', self._critique_line(critique))

            # 6) 데이터 시각화
            chart_rel, chart_note, visual_report = '', '옵션으로 생략(--no-chart)', ''
            if profile() == 'b' and not opts['no_chart'] and check.get('verdict') == 'pass':
                plan = timed('chart_plan', 'charter', lambda: P.plan_visual(content))
                content, chart_rel, chart_note, visual_report = P.apply_visual(content, topic_key, plan, rec=rec, dry=dry)
            elif not opts['no_chart'] and profile() != 'b':
                content, chart_rel, chart_note, visual_report = timed(
                    'chart', 'charter', lambda: P.step_visual(content, topic_key, rec=rec, dry=dry))
                self._update_last(stages, {'chart': chart_rel, 'note': chart_note, 'report': visual_report})

            # 7) 편집 심사 → 8) 판정
            qa = timed('review', 'editor',
                       lambda: P.step_review(subject, content, check, chart_rel, visual_report, critique,
                                             verified=pack, genre=genre))
            rec('editor', 'qa', self._qa_line(qa))

            # 기준 미달이면 — 보류든 수정 요청이든 — 자동으로 MAX_AUTO_REVISIONS 번까지 다시 쓴다.
            # 편집장 지적·팩트체크·평론을 함께 물려 준다. 그 뒤로는 사람이 /lab/admin/ 에서 지시한다.
            max_rev = P.MAX_AUTO_REVISIONS + (1 if prepare and profile() != 'b' else 0)
            hold = P.early_hold(qa, check) if profile() == 'b' and qa['verdict'] in ('minor', 'major') else ''
            if hold:
                # 수정 1회로 수렴할 가망이 낮으면 수정·재검증에 구독 한도를 쓰지 않고 운영자 검수로 넘긴다
                max_rev = 0
                qa = {**qa, 'verdict': 'major', 'early_hold': hold}
                stages.record('early_hold', 'editor', {'reason': hold})
                rec('editor', 'qa', f'{hold} — 자동 수정 대신 운영자 검수로 넘겨요.')
            for attempt in range(1, max_rev + 1):
                if qa['verdict'] not in ('minor', 'major'):
                    break
                prev_content, prev_qa = content, qa
                live.mark('editor_revise', writer, topic_key)
                # 재작성은 '필수 수정'만 처리한다 — 제안까지 넘기면 고칠 범위가 넓어져 다른 곳이 무너졌다.
                # 먼저 고칠 곳만 바꾸는 패치를 시도하고(검증된 문장·수치를 지킨다), 원고와 맞지 않으면 전체 재작성.
                notes = R.revision_notes(qa)
                p_subject, p_content, ok, why = timed('editor_patch', writer, lambda: patch_revise(
                    writer, subject, P.strip_visual_block(content), notes, who='편집 심사에서',
                    guide=f'[팩트체크 보고]\n{P.check_text(check)}' + P.pack_block(pack),
                    pack=pack if profile() == 'b' else None), attempt=attempt)
                if ok and not P.looks_truncated(p_content):
                    subject, content = p_subject, p_content
                else:
                    if profile() == 'b':
                        rec(writer, 'revise', '부분 수정 적용 실패로 보류해요. 검증된 원고 전체를 다시 쓰지 않아요.')
                        break
                    raw = timed('editor_revise', writer, lambda: ask_agent(writer, P.EDITOR_REVISE_PROMPT.format(
                        issues='\n'.join(f'- {i}' for i in notes), notes=qa.get('notes', ''),
                        check=P.check_text(check), critique=P.critique_text(critique),
                        subject=subject, content=content, structure=G.structure(genre),
                        standard=P.writing_standard(topic_key, genre)) + P.pack_block(pack),
                        max_tokens=P.COLUMN_MAX_TOKENS), attempt=attempt, kind='memo', sender='editor', recipient=writer)
                    # 잘리거나 짧아진 재작성본은 버리고 이전 원고를 지킨다 (팩트체크 재작성과 같은 안전장치)
                    subject, content, ok, why = P.safe_rewrite(raw, subject, content)
                self._update_last(stages, {'subject': subject, 'content': content, 'ok': ok, 'why': why},
                                  text=content, status='ok' if ok else 'failed')
                if not ok:
                    rec(writer, 'revise', f'편집 심사 재작성 실패 — {why}')
                    break
                revisions += 1
                rec(writer, 'revise', f'편집 심사 지적 반영해 재작성 ({P.body_length(content)}자)')
                pack = self._code_facts(stages, rec, content, pack, attempt=attempt + 1)

                # 재작성으로 수치 문장이 바뀌었으면 팩트체크를 다시 한다 — 예전엔 옛 보고서로 재심해,
                # 새로 들어온 숫자가 검증 없이 발행될 수 있었다.
                changed = P.new_numeric_sentences(prev_content, content)
                if changed or profile() == 'b':
                    check2 = timed('reverify', 'checker', lambda: P.step_check(subject, content, recent, verified=pack,
                                        previous=check, previous_content=prev_content, evidence=evidence())
                                        if profile() == 'b' else P.step_check(subject, content, recent, verified=pack),
                                   attempt=attempt)
                    ledger_rows += check2.get('claims') or []
                    check = {'first': check.get('first', check), **check2}
                    rec('checker', 'check', f"재작성 수치 {len(changed)}문장 재검증 {check2.get('verdict')}")
                    pack = E.merge(pack, E.from_check(check2))
                # 재작성이 기억으로 들여온 새 수치는 지운다(이전 판에 있던 수치는 그대로)
                content, dropped = (P.lock_numbers(content, pack, baseline=prev_content)
                                    if profile() != 'b' else (content, []))
                if dropped:
                    check = E.prune_check(check, content)
                    rec('checker', 'check', f'재작성이 들여온 근거 없는 수치 문장 {len(dropped)}개 삭제')

                # 본문이 통째로 다시 쓰였으므로 도판도 다시 만든다. 옛 블록을 남겨 두면
                # 표의 숫자만 고쳐지고 그림은 예전 수치 그대로 남는다.
                if profile() == 'b':
                    if check.get('verdict') != 'pass':
                        qa = {**qa, 'verdict': 'major', 'fatal': ['unverified_data'],
                              'notes': '부분 수정 1회 뒤에도 독립 검증이 완료되지 않아 보류해요.'}
                        rec('editor', 'qa', '재심 ' + self._qa_line(qa))
                        break
                    content = P.strip_visual_block(content)
                    tasks = {'critique': ('critic', lambda: P.step_critique(subject, content))}
                    if check.get('verification_hash') != P.verification_hash(content):
                        tasks['check'] = ('checker', lambda: P.step_check(subject, content, recent, verified=pack,
                                                                          evidence=evidence()))
                    if not opts['no_chart']:
                        tasks['chart_plan'] = ('charter', lambda: P.plan_visual(content, feedback=P.visual_feedback(qa)))
                    parallel_reviews = review_batch(tasks, stages=stages, attempt=attempt+1)
                    critique = parallel_reviews['critique']
                    if 'check' in parallel_reviews:
                        check = parallel_reviews['check']
                        record_facts(check)
                        ledger_rows += check.get('claims') or []
                    if not opts['no_chart']:
                        content, chart_rel, chart_note, visual_report = P.apply_visual(
                            content, topic_key, parallel_reviews['chart_plan'], rec=rec, dry=dry)
                elif not opts['no_chart']:
                    content = P.strip_visual_block(content)
                    content, chart_rel, chart_note, visual_report = timed(
                        'chart', 'charter', lambda: P.step_visual(content, topic_key, rec=rec, dry=dry,
                                                                  feedback=P.visual_feedback(qa)),
                        attempt=attempt + 1)
                if profile() != 'b':
                    critique = timed('critique', 'critic', lambda: P.step_critique(subject, content),
                                     attempt=attempt + 1)
                rec('critic', 'critique', '재검토 ' + self._critique_line(critique))
                qa = timed('review', 'editor',
                           lambda: P.step_review(subject, content, check, chart_rel, visual_report, critique,
                                             verified=pack, previous=prev_qa, previous_content=prev_content,
                                             genre=genre),
                           attempt=attempt + 1)
                # 마지막 재심의 '수정 요청'은 남은 것이 제안뿐일 때만 통과로 본다(학술지의 minor revision 수리).
                # 필수 수정이 남았거나 치명 결함이 있으면 보류 → 운영자 검수(R.accept_after_revision).
                if attempt == max_rev and R.accept_after_revision(qa):
                    qa['verdict'] = 'accept'
                    qa['accepted_after_revision'] = True
                rec('editor', 'qa', '재심 ' + self._qa_line(qa))

            stages.record('final', 'editor', {'verdict': qa['verdict'], 'score': qa.get('score'),
                                              'revisions': revisions,
                                              'quality': quality.report(subject, content)}, text=content)

            if dry:
                out('=' * 60 + f'\nTITLE: {subject}\n' + content[:2000] + '\n' + '=' * 60)
                out(json.dumps({'brief': brief, 'chart': chart_note, 'qa': qa}, ensure_ascii=False, indent=1)[:2500])
                return

            draft.subject, draft.content, draft.chart_path = subject, content, chart_rel
            draft.check_report, draft.qa_report, draft.revisions = check, qa, revisions
            draft.chart_note = chart_note

            if qa['verdict'] == 'accept' and not opts['no_publish']:
                # 발행 직전 제목 실험실 — 코드 검사를 통과한 후보만 쓴다
                keywords = P.headline_keywords((brief_decision.chosen or {}) if brief_decision else {})
                new_title, why = P.step_headline(subject, content, keywords=keywords, recent=recent)
                if new_title != subject:
                    rec('editor', 'headline', f'제목 다듬기: 「{subject}」 → 「{new_title}」 — {why}'[:300])
                    subject = draft.subject = new_title
                q = S.finish_accepted(draft, P.publish_draft)
                if q is None:       # 공개 예정 시각 전 — 공개 대기
                    rec('lead', 'ready', S.ready_line(draft))
                    out(self.style.SUCCESS(f'공개 대기 [{label}] {subject} — '
                                           f'{timezone.localtime(draft.publish_at):%m.%d %H:%M} 공개 ({qa["score"]}점)'))
                else:
                    rec('lead', 'publish', f'발행: {subject} (id={q.pk}, {qa["score"]}점)')
                    out(self.style.SUCCESS(f'발행 완료 [{label}] {subject} (id={q.pk}, {qa["score"]}점)'))
            else:
                draft.status = ColumnDraft.STATUS_HOLD
                draft.save()
                why = '발행 생략(--no-publish)' if qa['verdict'] == 'accept' else '운영자 검수 대기'
                rec('lead', 'hold', f'보류({qa["verdict"]}, {qa["score"]}점): {subject} — {why}')
                out(self.style.WARNING(f'보류 [{label}] {subject} — /lab/admin/ 에서 검수'))
                if slot is not None and qa['verdict'] != 'accept':
                    S.alert_not_ready(draft, label, f'심사를 통과하지 못했습니다({qa["score"]}점)')

            # 이번에 쌓인 활동 기록을 공개용 말투로 다듬어 둔다. 연구실 페이지가 폴링하므로
            # 조회 시점에 만들 수 없고, 여기서 한 번(한 호출) 처리한다. 실패해도 본작업과
            # 무관하므로 틀 문장으로 넘어간다.
            try:
                call_command('polish_logs', limit=24, verbosity=0)
            except Exception as ex:  # noqa: BLE001
                out(self.style.WARNING(f'활동 문장 다듬기 건너뜀: {str(ex)[:120]}'))

        except Exception as ex:  # noqa: BLE001 — 실패도 기록해 연구실에 보이게
            stages.record('fail', 'lead', status='failed', error=str(ex))
            if draft:
                from common.services.cli_errors import ProviderUnavailable
                from office.research_contract import ContractIncomplete
                draft.status = ColumnDraft.STATUS_HOLD if isinstance(ex, (RunBudgetExceeded, ProviderUnavailable, ReviewIncomplete, ContractIncomplete)) else ColumnDraft.STATUS_FAILED
                draft.save(update_fields=['status'])
                log('lead', 'fail', f'{label} 제작 실패: {str(ex)[:200]}', draft=draft)
                if slot is not None:
                    S.alert_not_ready(draft, label, f'제작 중 오류로 멈췄습니다({type(ex).__name__})',
                                      rerun_args=['office_publish', '--topic', topic_key,
                                                  '--prepare' if prepare else '--if-missing'])
            raise

    @staticmethod
    def _code_facts(stages: StageRecorder, rec, content: str, pack: str, *, attempt: int = 1) -> str:
        """본문 코드 예제를 실행해(OFFICE_CODE_RUN=1) 결과를 근거 묶음의 실행 확인 블록으로 바꿔 넣는다."""
        from office import code_check as CC
        if not CC.enabled() or not CC.blocks(content):
            return pack
        started = time.monotonic()
        res = CC.run_examples(content)
        stages.record('code_run', 'checker', res, attempt=attempt, seconds=round(time.monotonic() - started, 1),
                      status='ok' if res.get('ran') else 'skipped')
        block = CC.facts(res)
        if block:
            bad = CC.failures(block)
            rec('checker', 'check', f"코드 예제 실행: 테스트 {len(res['tests'])}개 중 실패 {len(bad)}개")
        return CC.replace(pack, block)

    def _run_first(self, stages: StageRecorder, rec, timed, topic_key: str, writer: str, subject: str, content: str,
                   pack: str, genre: str) -> tuple:
        """튜토리얼: 실행할 수 없는 예제·실행에서 실패한 테스트는 사실 검증 전에 한 번 고친다.

        왜(2026-11-02 atomic·select 파일럿): 실행이 안 된 예제로 사실 관문과 심사를 돌리면 결과 주장이 모두 원장 밖이
        되고, 심사 뒤 패치로는 실행 근거를 되살리지 못했다. 근거(실행 결과)를 먼저 만들고 글을 거기에 맞춘다."""
        from office import code_check as CC
        gate = CC.format_issues(content) + [f'코드 예제 실행 실패 — {f}. 실제 값으로 고치거나 코드를 고치세요'
                                            for f in CC.failures(pack)]
        if not gate:
            return subject, content, pack
        rec('editor', 'precheck', f'실행 예제 {len(gate)}건 — 사실 검증 전에 먼저 고쳐요: {gate[0][:80]}')
        subject, content, remaining = timed('fix', writer,
                                            lambda: P.step_fix_draft(topic_key, subject, content, gate, pack, genre))
        self._update_last(stages, {'subject': subject, 'content': content, 'remaining': remaining}, text=content)
        rec(writer, 'revise', f'실행 예제 고침 ({P.body_length(content)}자)')
        return subject, content, self._code_facts(stages, rec, content, pack, attempt=2)

    @staticmethod
    def _update_last(stages: StageRecorder, output: dict, *, text: str = '', status: str = '') -> None:
        """방금 기록한 단계의 산출물을 (튜플 결과를 풀어) 다시 저장한다."""
        if not stages.stages:
            return
        row = stages.stages[-1]
        if profile() == 'b' and isinstance(output.get('content'), str):
            from office.research_contract import version_record
            parent = next((s['text_digest'] for s in reversed(stages.stages[:-1]) if s.get('text_digest')), '')
            output['artifact_version'] = version_record(output.get('subject', ''), output['content'], parent=parent)
        row['output'] = output
        if text:
            from office.recorder import digest
            row['text_digest'] = digest(text)
        if status:
            row['status'] = status
        if stages.dry:
            return
        from office.models import StageRun
        StageRun.objects.filter(run_id=stages.run_id, seq=row['seq']).update(
            output=output, text_digest=row['text_digest'], status=row['status'])

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
