"""
연구팀 칼럼 제작 파이프라인 (auto_write_columns 의 팀 버전).

  칼럼니스트 초안 → 검증관(사실·출처·중복; 수정 요청 시 1회 재작성) → 차트 담당(표·차트 삽입)
  → 팀장 QA(점수 ≥ 7 이면 발행, 아니면 '검수 대기'로 보류 → 관리자가 /lab/admin/ 에서 발행/반려)

주제는 주간 회의에서 관리자가 고른 안건(Decision)을 우선 사용하고, 없으면 칼럼니스트가 직접 고른다.

사용법:
  python manage.py office_publish --topic hrd
  python manage.py office_publish --topic data --dry-run      # DB 저장 없이 콘솔 출력
  python manage.py office_publish --topic coding --no-chart

cron (auto_write_columns 자리를 대체):
  0 10 * * 2  .../python manage.py office_publish --topic hrd
  0 10 * * 4  .../python manage.py office_publish --topic data
  0 10 * * 6  .../python manage.py office_publish --topic coding
"""
import json
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from common.management.commands.auto_write_columns import (
    COLUMN_STRUCTURE, TOPICS, _get_or_create_bot_user, _parse_output, _recent_subjects,
)
from office.agents import AGENTS, TOPIC_AGENT
from office.models import ColumnDraft
from office.services import ask_agent, ask_agent_json, chart_markdown, log, render_chart, take_column_brief

QA_PASS_SCORE = 7

CHECK_PROMPT = (
    '아래 칼럼 초안을 검증하세요.\n\n[이미 발행한 칼럼 제목]\n{titles}\n\n[초안]\nTITLE: {subject}\n{content}\n\n'
    '판정 기준: (1) 핵심 소재가 기존 칼럼과 겹치면 중복. (2) 수치·인용·사례는 실재하고 널리 알려진 것이어야 하며, '
    '확인 불가하거나 지어낸 것으로 보이면 지목. (3) 과장·최신성 오류.\n'
    '출력 JSON: {{"verdict": "pass" 또는 "revise", "duplicate": true/false, "similar_titles": ["..."], '
    '"claims": [{{"claim": "문장 요약", "status": "verified|unverifiable|wrong", "note": "근거 또는 문제"}}], '
    '"notes": "수정이 필요하면 무엇을 어떻게 고칠지 구체적으로 3~6줄"}}\n'
    'unverifiable 이나 wrong 이 2개 이상이거나 duplicate 이면 revise.'
)

REVISE_PROMPT = (
    '검증관이 아래 초안에 수정을 요청했습니다. 지적을 모두 반영해 칼럼 전체를 다시 쓰세요. '
    '확인 불가한 수치·출처는 삭제하거나 일반적 표현으로 바꾸고, 중복 지적이 있으면 관점을 바꾸세요.\n\n'
    '[검증관 지적]\n{notes}\n[문제 항목]\n{claims}\n\n[원래 초안]\nTITLE: {subject}\n---\n{content}\n\n'
    '{structure}'
)

CHART_PROMPT = (
    '아래 칼럼 본문에서 표·차트로 만들 수 있는 수치를 찾으세요. 본문에 명시된 숫자만 사용하고, '
    '비교 가능한 수치가 3개 미만이면 만들지 않습니다.\n\n[본문]\n{content}\n\n'
    '출력 JSON: {{"has_data": true/false, "reason": "판단 근거 한 줄", '
    '"spec": {{"type": "bar|hbar|line", "title": "차트 제목(한글)", "labels": ["항목1", ...], '
    '"series": [{{"name": "계열명", "values": [숫자, ...]}}], "unit": "%", "source": "본문에 적힌 출처"}}, '
    '"insert_after_heading": "차트를 넣을 ## 헤더 텍스트(본문에 있는 그대로)", '
    '"caption": "차트가 보여주는 핵심 한 문장"}}'
)

QA_PROMPT = (
    '발행 전 최종 품질검사입니다. 팀장으로서 아래 칼럼을 채점하세요.\n\n[검증관 보고]\n{check}\n\n[칼럼]\nTITLE: {subject}\n{content}\n\n'
    '기준: 구조(리드·왜 지금인가·본론·현장의 변화·시사점·맺음말·참고 자료) 준수, 논리 일관성, 독자 적합성, '
    '과장·모호함, 표/차트가 본문과 맞는지, 분량(1,200~1,600자).\n'
    '출력 JSON: {{"score": 1~10 정수, "decision": "publish" 또는 "hold", "strengths": "한 줄", '
    '"issues": ["구체적 문제", ...], "notes": "관리자에게 남길 한 줄"}}\n'
    f'score 가 {QA_PASS_SCORE} 이상이면 publish.'
)


def _draft_prompt(topic_key: str, brief, recent_titles: list) -> str:
    topic = TOPICS[topic_key]
    today_str = datetime.now().strftime('%Y년 %m월 %d일')
    avoid = ''
    if recent_titles:
        avoid = '\n\n**[이미 다룬 주제 - 반드시 피하세요]**\n' + '\n'.join(f'- {t}' for t in recent_titles) + '\n'
    if brief is not None:
        chosen = brief.chosen or {}
        subject_block = (
            f"이번 칼럼 주제는 편집회의에서 결정되었습니다. 이 주제로 작성하세요.\n"
            f"- 주제: {chosen.get('title', '')}\n- 관점·근거: {chosen.get('detail', '')}\n"
        )
    else:
        subject_block = '위 분야에서 현재 가장 주목받고 있는 트렌드나 이슈 하나를 선정하여 작성하세요.\n'
    return (
        f'오늘 날짜: {today_str}\n담당 분야: {topic["topic_hint"]}\n독자: {topic["audience"]}\n\n'
        f'{subject_block}{avoid}\n{COLUMN_STRUCTURE}'
    )


def _insert_after_heading(content: str, heading: str, block: str) -> str:
    """heading(## …) 섹션의 끝(다음 ## 직전)에 block 삽입. 못 찾으면 '## 시사점' 앞, 그것도 없으면 끝."""
    lines = content.split('\n')
    target = None
    if heading:
        h = heading.strip().lstrip('#').strip()
        for i, l in enumerate(lines):
            if l.startswith('## ') and h and h in l:
                target = i
                break
    if target is None:
        for i, l in enumerate(lines):
            if l.startswith('## 시사점'):
                return '\n'.join(lines[:i] + [block, ''] + lines[i:])
        return content.rstrip() + '\n\n' + block
    end = len(lines)
    for j in range(target + 1, len(lines)):
        if lines[j].startswith('## '):
            end = j
            break
    return '\n'.join(lines[:end] + ['', block, ''] + lines[end:])


class Command(BaseCommand):
    help = '연구팀이 칼럼 1편을 제작·검증·QA 후 발행(또는 보류)합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', choices=['hrd', 'data', 'coding'], required=True)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-chart', action='store_true')

    def handle(self, *args, **opts):
        from community.models import Category, Question

        topic_key = opts['topic']
        dry = opts['dry_run']
        writer = TOPIC_AGENT[topic_key]
        wname = AGENTS[writer]['name']
        label = TOPICS[topic_key]['label']
        out = self.stdout.write

        brief = take_column_brief(topic_key)
        draft = None if dry else ColumnDraft.objects.create(
            topic=topic_key, decision=brief, status=ColumnDraft.STATUS_FAILED,
            brief=(brief.chosen or {}).get('title', '') if brief else '')

        def rec(agent, action, text):
            out(f'  [{AGENTS[agent]["name"]}] {text[:90]}')
            if not dry:
                log(agent, action, text, draft=draft)

        try:
            # 1) 초안
            recent = _recent_subjects(topic_key)
            out(f'[{timezone.localtime():%H:%M:%S}] {label} — {wname} 초안 작성' + (f' (회의 주제: {draft.brief})' if draft and draft.brief else ''))
            raw = ask_agent(writer, _draft_prompt(topic_key, brief, recent), max_tokens=6000)
            subject, content = _parse_output(raw)
            rec(writer, 'draft', f'초안 완성: {subject}')

            # 2) 검증 (최대 1회 재작성)
            check = ask_agent_json('checker', CHECK_PROMPT.format(
                titles='\n'.join(f'- {t}' for t in recent) or '(없음)', subject=subject, content=content), max_tokens=4000)
            bad = [c for c in check.get('claims', []) if c.get('status') in ('unverifiable', 'wrong')]
            rec('checker', 'check', f"검증 {check.get('verdict')}: 문제 항목 {len(bad)}건" + (', 기존 칼럼과 중복' if check.get('duplicate') else ''))
            revisions = 0
            if check.get('verdict') == 'revise':
                raw = ask_agent(writer, REVISE_PROMPT.format(
                    notes=check.get('notes', ''), claims=json.dumps(bad, ensure_ascii=False),
                    subject=subject, content=content, structure=COLUMN_STRUCTURE), max_tokens=6000)
                subject, content = _parse_output(raw)
                revisions = 1
                rec(writer, 'revise', f'지적 {len(bad)}건 반영해 재작성: {subject}')
                check2 = ask_agent_json('checker', CHECK_PROMPT.format(
                    titles='\n'.join(f'- {t}' for t in recent) or '(없음)', subject=subject, content=content), max_tokens=4000)
                check = {'first': check, **check2}
                rec('checker', 'check', f"재검증 {check2.get('verdict')}")

            # 3) 차트
            chart_rel = ''
            if not opts['no_chart']:
                spec = ask_agent_json('charter', CHART_PROMPT.format(content=content), max_tokens=3000)
                if spec.get('has_data') and isinstance(spec.get('spec'), dict):
                    stem = f"{timezone.localdate():%Y%m%d}_{topic_key}_{timezone.now():%H%M%S}"
                    chart_rel = (render_chart(spec['spec'], stem) or '') if not dry else ''
                    if chart_rel or dry:
                        block = chart_markdown(chart_rel or 'columns/preview.png', spec['spec'])
                        if spec.get('caption'):
                            block += f"\n\n{spec['caption']}"
                        content = _insert_after_heading(content, spec.get('insert_after_heading', ''), block)
                        rec('charter', 'chart', f"차트 삽입: {spec['spec'].get('title', '')} ({spec['spec'].get('type', 'bar')})")
                    else:
                        rec('charter', 'chart', '차트 렌더 실패(matplotlib 미설치 또는 데이터 형식) — 표 없이 진행')
                else:
                    rec('charter', 'chart', f"차트 생략: {spec.get('reason', '수치 부족')}")

            # 4) 팀장 QA
            qa = ask_agent_json('lead', QA_PROMPT.format(
                check=json.dumps({k: v for k, v in check.items() if k != 'first'}, ensure_ascii=False)[:2500],
                subject=subject, content=content), max_tokens=3000)
            try:
                score = int(qa.get('score', 0))
            except (TypeError, ValueError):
                score = 0
            publish = qa.get('decision') == 'publish' and score >= QA_PASS_SCORE
            rec('lead', 'qa', f"QA {score}/10 → {'발행' if publish else '보류(관리자 검수)'}: {qa.get('notes', '')}")

            if dry:
                out('=' * 60 + f'\nTITLE: {subject}\n' + content[:1500] + '\n' + '=' * 60)
                out(json.dumps({'check': check, 'qa': qa}, ensure_ascii=False, indent=1)[:2000])
                return

            draft.subject, draft.content, draft.chart_path = subject, content, chart_rel
            draft.check_report, draft.qa_report, draft.revisions = check, qa, revisions

            if publish:
                category = Category.objects.get(name=TOPICS[topic_key]['category_name'])
                q = Question.objects.create(author=_get_or_create_bot_user(), subject=subject, content=content,
                                            create_date=timezone.now(), category=category)
                draft.question, draft.status = q, ColumnDraft.STATUS_PUBLISHED
                if brief:
                    brief.consumed_at = timezone.now()
                    brief.save(update_fields=['consumed_at'])
                rec('lead', 'publish', f'발행: {subject} (id={q.pk})')
                out(self.style.SUCCESS(f'발행 완료 [{label}] {subject} (id={q.pk})'))
            else:
                draft.status = ColumnDraft.STATUS_HOLD
                rec('lead', 'hold', f'보류: {subject} — 관리자 검수 대기')
                out(self.style.WARNING(f'보류 [{label}] {subject} — /lab/admin/ 에서 검수'))
            draft.save()

        except Exception as ex:  # noqa: BLE001 — 실패도 기록해 연구실에 보이게
            if draft:
                draft.status = ColumnDraft.STATUS_FAILED
                draft.save(update_fields=['status'])
                log('lead', 'fail', f'{label} 제작 실패: {str(ex)[:200]}', draft=draft)
            raise
