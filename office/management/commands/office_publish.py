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

cron:
  0 10 * * 2  .../python manage.py office_publish --topic hrd
  0 10 * * 4  .../python manage.py office_publish --topic data
  0 10 * * 6  .../python manage.py office_publish --topic coding
"""
import json
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from common.management.commands.auto_write_columns import COLUMN_STRUCTURE, TOPICS
from common.services.claude import call_tags
from office import live
from office import pipeline as P
from office import quality
from office.agents import AGENTS, TOPIC_AGENT
from office.models import ColumnDraft
from office.recorder import StageRecorder
from office.services import ask_agent, log, take_column_brief


class Command(BaseCommand):
    help = '연구팀이 칼럼 1편을 기획·집필·검증·시각화·심사 후 발행(또는 보류)합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', choices=['hrd', 'data', 'coding'], required=True)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-chart', action='store_true')
        parser.add_argument('--no-publish', action='store_true',
                            help='심사를 통과해도 발행하지 않고 보류로 저장 (로컬 검증용)')

    def handle(self, *args, **opts):
        # 어떻게 끝나든(발행·보류·실패) 연구실 라이브 표시를 정리한다
        try:
            return self._run(*args, **opts)
        finally:
            live.finish()

    def _run(self, *args, **opts):
        topic_key = opts['topic']
        dry = opts['dry_run']
        writer = TOPIC_AGENT[topic_key]
        label = TOPICS[topic_key]['label']
        out = self.stdout.write

        brief_decision = take_column_brief(topic_key)
        draft = None if dry else ColumnDraft.objects.create(
            topic=topic_key, decision=brief_decision, status=ColumnDraft.STATUS_FAILED,
            brief=(brief_decision.chosen or {}).get('title', '') if brief_decision else '')
        stages = StageRecorder(draft=draft, dry=dry)

        def rec(agent, action, text):
            out(f'  [{AGENTS[agent]["name"]}] {text[:100]}')
            if not dry:
                log(agent, action, text, draft=draft)

        def timed(stage, agent, fn, **kw):
            """단계를 실행하고 결과·소요 시간을 기록한다. 호출에는 단계 꼬리표가 붙는다."""
            started = time.monotonic()
            with call_tags(run_id=str(stages.run_id), stage=stage):
                result = fn()
            kw.setdefault('output', result if isinstance(result, (dict, list)) else None)
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

            # 2) 집필 → 자동 점검(코드) → 필요하면 즉시 보완
            #    분량·문체·섹션·수치처럼 기계로 판별되는 결함을 여기서 잡는다. 팩트체크·평론·
            #    심사는 전부 모델 호출이라, 거기까지 끌고 가면 호출 세 번을 더 태운 뒤에야
            #    재작성에 들어간다.
            subject, content = timed('draft', writer,
                                     lambda: P.step_draft(topic_key, brief_decision, brief, recent))
            self._update_last(stages, {'subject': subject, 'content': content}, text=content)
            rec(writer, 'draft', f'초안 완성: {subject} ({P.body_length(content)}자)')
            flaws = P.precheck_draft(content)
            stages.record('precheck', 'editor', {'issues': flaws, 'quality': quality.report(subject, content)})
            if flaws:
                rec('editor', 'precheck', f'초안 자동 점검 {len(flaws)}건: {flaws[0][:90]}')
                subject, content, flaws = timed('fix', writer,
                                                lambda: P.step_fix_draft(topic_key, subject, content, flaws))
                self._update_last(stages, {'subject': subject, 'content': content, 'remaining': flaws},
                                  text=content)
                rec(writer, 'revise', f'자동 점검 지적 반영 ({P.body_length(content)}자)'
                    + (f' · 남은 지적 {len(flaws)}건' if flaws else ' · 모두 해소'))
            else:
                rec('editor', 'precheck', '초안 자동 점검 통과')

            # 3) 팩트체크 → 4) 수정
            check = timed('check', 'checker', lambda: P.step_check(subject, content, recent, verified=facts),
                          kind='report', sender='checker', recipient='editor')
            bad = [c for c in check.get('claims', []) if c.get('status') in P.BAD_CLAIMS]
            rec('checker', 'check', f"팩트체크 {check.get('verdict')}: 확인 필요 {len(bad)}건"
                + (', 기존 칼럼과 중복' if check.get('duplicate') else ''))
            revisions = 0
            if check.get('verdict') == 'revise':
                res = timed('revise', writer, lambda: P.step_author_revise(topic_key, subject, content, check))
                subject, content, ok, why = res
                self._update_last(stages, {'subject': subject, 'content': content, 'ok': ok, 'why': why},
                                  text=content, status='ok' if ok else 'failed')
                if ok:
                    revisions = 1
                    rec(writer, 'revise', f'팩트체크 {len(bad)}건 반영해 재작성 ({P.body_length(content)}자)')
                    check2 = timed('recheck', 'checker', lambda: P.step_check(subject, content, recent, verified=facts))
                    check = {'first': check, **check2}
                    rec('checker', 'check', f"재검증 {check2.get('verdict')}")
                else:
                    rec(writer, 'revise', f'재작성 실패 — {why}')

            # 5) 평론 — 읽을 이유가 있는 글인지
            critique = timed('critique', 'critic', lambda: P.step_critique(subject, content),
                             kind='report', sender='critic', recipient='editor')
            rec('critic', 'critique', self._critique_line(critique))

            # 6) 데이터 시각화
            chart_rel, chart_note, visual_report = '', '옵션으로 생략(--no-chart)', ''
            if not opts['no_chart']:
                content, chart_rel, chart_note, visual_report = timed(
                    'chart', 'charter', lambda: P.step_visual(content, topic_key, rec=rec, dry=dry))
                self._update_last(stages, {'chart': chart_rel, 'note': chart_note, 'report': visual_report})

            # 7) 편집 심사 → 8) 판정
            qa = timed('review', 'editor',
                       lambda: P.step_review(subject, content, check, chart_rel, visual_report, critique,
                                             verified=facts))
            rec('editor', 'qa', self._qa_line(qa))

            # 기준 미달이면 — 보류든 수정 요청이든 — 자동으로 MAX_AUTO_REVISIONS 번까지 다시 쓴다.
            # 편집장 지적·팩트체크·평론을 함께 물려 준다. 그 뒤로는 사람이 /lab/admin/ 에서 지시한다.
            for attempt in range(1, P.MAX_AUTO_REVISIONS + 1):
                if qa['verdict'] not in ('minor', 'major'):
                    break
                prev_content = content
                live.mark('editor_revise', writer, topic_key)
                raw = timed('editor_revise', writer, lambda: ask_agent(writer, P.EDITOR_REVISE_PROMPT.format(
                    issues='\n'.join(f'- {i}' for i in qa.get('issues', [])), notes=qa.get('notes', ''),
                    check=P.check_text(check), critique=P.critique_text(critique),
                    subject=subject, content=content, structure=COLUMN_STRUCTURE,
                    standard=P.writing_standard(topic_key)),
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

                # 재작성으로 수치 문장이 바뀌었으면 팩트체크를 다시 한다 — 예전엔 옛 보고서로 재심해,
                # 새로 들어온 숫자가 검증 없이 발행될 수 있었다.
                changed = P.new_numeric_sentences(prev_content, content)
                if changed:
                    check2 = timed('reverify', 'checker', lambda: P.step_check(subject, content, recent, verified=facts),
                                   attempt=attempt)
                    check = {'first': check.get('first', check), **check2}
                    rec('checker', 'check', f"재작성 수치 {len(changed)}문장 재검증 {check2.get('verdict')}")

                # 본문이 통째로 다시 쓰였으므로 도판도 다시 만든다. 옛 블록을 남겨 두면
                # 표의 숫자만 고쳐지고 그림은 예전 수치 그대로 남는다.
                if not opts['no_chart']:
                    content = P.strip_visual_block(content)
                    content, chart_rel, chart_note, visual_report = timed(
                        'chart', 'charter', lambda: P.step_visual(content, topic_key, rec=rec, dry=dry),
                        attempt=attempt + 1)
                critique = timed('critique', 'critic', lambda: P.step_critique(subject, content),
                                 attempt=attempt + 1)
                rec('critic', 'critique', '재검토 ' + self._critique_line(critique))
                qa = timed('review', 'editor',
                           lambda: P.step_review(subject, content, check, chart_rel, visual_report, critique,
                                             verified=facts),
                           attempt=attempt + 1)
                # 마지막 재심에서는 '수정 요청'을 통과로 본다 (학술지의 minor revision 수리와 같은 처리).
                # 치명 결함이 남아 있으면 verdict 가 major 라 그대로 보류된다.
                if attempt == P.MAX_AUTO_REVISIONS and qa['verdict'] == 'minor':
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
                keywords = list(((brief_decision.chosen or {}) if brief_decision else {}).get('keywords') or [])
                new_title, why = P.step_headline(subject, content, keywords=keywords, recent=recent)
                if new_title != subject:
                    rec('editor', 'headline', f'제목 다듬기: 「{subject}」 → 「{new_title}」 — {why}'[:300])
                    subject = draft.subject = new_title
                q = P.publish_draft(draft)
                rec('lead', 'publish', f'발행: {subject} (id={q.pk}, {qa["score"]}점)')
                out(self.style.SUCCESS(f'발행 완료 [{label}] {subject} (id={q.pk}, {qa["score"]}점)'))
            else:
                draft.status = ColumnDraft.STATUS_HOLD
                draft.save()
                why = '발행 생략(--no-publish)' if qa['verdict'] == 'accept' else '운영자 검수 대기'
                rec('lead', 'hold', f'보류({qa["verdict"]}, {qa["score"]}점): {subject} — {why}')
                out(self.style.WARNING(f'보류 [{label}] {subject} — /lab/admin/ 에서 검수'))

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
                draft.status = ColumnDraft.STATUS_FAILED
                draft.save(update_fields=['status'])
                log('lead', 'fail', f'{label} 제작 실패: {str(ex)[:200]}', draft=draft)
            raise

    @staticmethod
    def _update_last(stages: StageRecorder, output: dict, *, text: str = '', status: str = '') -> None:
        """방금 기록한 단계의 산출물을 (튜플 결과를 풀어) 다시 저장한다."""
        if not stages.stages:
            return
        row = stages.stages[-1]
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
