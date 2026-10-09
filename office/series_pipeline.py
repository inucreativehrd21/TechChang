"""연재 회차를 연구실 검증을 거쳐 만든다 — 새 회차 발행과 기존 회차 리메이크 공용.

칼럼(office_publish)과 같은 연구원·같은 기록(ColumnDraft·WorkLog·StageRun)을 쓰므로 연구실 화면과
'제작 과정(메이킹 오브)'에 그대로 보인다. 흐름:

  집필(윤성) → 자동 점검(코드) → 팩트체크(하경: 코드·명령·API 를 웹에서 공식 문서와 대조)
  → 지적 반영 → 평론(예원) → 편집 심사(승현, 100점·80점 이상 발행) → 미달이면 1회 보완·재심
  → 통과: 발행(새 회차) 또는 제자리 갱신(리메이크) / 미달: 보류 — 운영자가 /lab/admin/ 에서 판단

심사 기준표만 연재용(SERIES_RUBRIC)이다. 칼럼 기준(필수 섹션·공표 통계·차트)으로 재면 연재 회차는
부당하게 감점된다. 연재는 '따라 하면 실제로 되는가'와 '구체적인가'가 핵심이다.
리메이크는 심사를 통과했을 때만 덮어쓴다 — 발행된 글을 더 나쁜 판본으로 바꾸지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
import textwrap

from django.utils import timezone

from community.series_catalog import (DEFAULT_OUTLINE_LABELS, OUTLINES, REQUIRED_HEADINGS, SERIES, STRUCTURES,
                                      source_block)

from . import live
from . import pipeline as P
from .agents import AGENTS, TOPIC_AGENT
from .models import ColumnDraft
from .recorder import StageRecorder
from .services import WEB_TOOLS, ask_agent, ask_agent_json, audit_style, log

logger = logging.getLogger(__name__)

TOPIC_KEY = 'coding'          # 두 연재 모두 프로그래밍 — 집필은 프로그래밍 칼럼니스트(윤성)
SERIES_RUBRIC = {
    'accuracy':     (0.30, '정확성 — 코드·명령·API가 실제 현재 버전과 맞고 그대로 따라 하면 동작하는지, 사실 주장의 근거'),
    'concreteness': (0.25, '구체성 — 실제 코드·실행 결과·에러 메시지·예시로 보여 주는지, 추상 설명으로 분량만 채우지 않았는지'),
    'clarity':      (0.20, '이해 쉬움 — 입문자 눈높이, 용어를 비유와 정의로 풀었는지, 단계 사이에 비약이 없는지'),
    'practice':     (0.15, '실습 가능성 — 직접 해보기·미션을 독자가 실제로 따라 할 수 있는 크기와 안내로 줬는지'),
    'continuity':   (0.10, '연속성 — 지난 회차를 잇고 다음 회차로 넘기는지, 이미 설명한 것을 되풀이하지 않는지'),
}
MIN_CHARS = {'django': 2200, 'agent': 1600}
TARGET = {'django': '2,600~3,600자', 'agent': '1,800~2,600자'}
MAX_TOKENS = 16000

CHECK_PROMPT = (
    '연재 회차 팩트체크입니다. 문체·구성은 평가하지 말고 아래만 확인하세요.\n'
    '(1) 코드·설치 명령·라이브러리·API 이름과 사용법이 실제로 존재하고 현재 버전과 맞는가 — 웹 검색으로 공식 문서를 확인\n'
    '(2) 코드를 그대로 따라 하면 동작하는가(빠진 import·설정, 오타, 존재하지 않는 옵션)\n'
    '(3) 수치·사실 주장에 근거가 있는가\n'
    '(4) 테크창 코드·연구실에 대한 서술이 아래 자료(발췌·사실 자료)와 맞는가\n\n'
    '{context}{sources}\n[원고]\nTITLE: {subject}\n{content}\n\n'
    '출력 JSON: {{"verdict": "pass" 또는 "revise", '
    '"claims": [{{"claim": "확인한 주장·코드 요약", "status": "verified|unverifiable|wrong|outdated", '
    '"note": "근거(공식 문서 URL) 또는 정확한 수정안"}}], '
    '"critical": ["그대로 따라 하면 실행이 안 되거나 사실이 틀린 항목 요약 — 없으면 빈 배열"]}}\n'
    '확인한 주요 주장 4~10개를 claims 에 넣고, wrong·outdated·unverifiable 이 하나라도 있으면 revise.'
)

FIX_PROMPT = (
    '{who} 아래 지적이 나왔습니다. **지적된 곳만** 고쳐 회차 전체를 다시 내보내세요. '
    '통과한 부분과 회차 구조는 그대로 두고, 분량을 줄이지 마세요.\n\n[지적]\n{issues}\n\n'
    '[현재 원고]\nTITLE: {subject}\n---\n{content}\n\n{structure}'
)

QA_PROMPT = (
    '연재 회차 편집 심사입니다. 기준표의 항목마다 1~5점(5=탁월, 4=발행 가능, 3=보완 필요, 2 이하=미흡)을 매기세요.\n'
    '총점과 발행 여부는 시스템이 계산합니다.\n\n'
    '[시리즈] {series} — 독자: {audience}\n[이 회차의 목표]\n{plan}\n\n'
    '[팩트체크 보고]\n{check}\n\n[평론가 의견]\n{critique}\n\n'
    '[분량] {length}자 (권장 {target}) · [문체] {style}\n\n[기준표]\n{rubric}\n\n'
    '[원고]\nTITLE: {subject}\n{content}\n\n'
    '치명 결함 코드(해당할 때만): code_wrong(따라 하면 동작하지 않는 코드), fabricated(지어낸 API·사실), '
    'off_plan(이 회차의 목표와 다른 내용).\n'
    '출력 JSON: {{"scores": {{"accuracy": 1-5, "concreteness": 1-5, "clarity": 1-5, "practice": 1-5, '
    '"continuity": 1-5}}, "fatal": [], "issues": ["어디를 어떻게 고칠지 구체적 지시"], '
    '"strengths": "잘한 점 한두 문장", "notes": "총평 한 문장"}}'
)

REMAKE_RULE = (
    '\n[리메이크 — 이미 발행된 회차를 더 구체적이고 자세하게 다시 씁니다]\n'
    '- 흐름과 핵심 비유는 살리되, 추상적인 설명을 실제 코드·실행 결과·화면·에러 메시지로 바꾸세요.\n'
    '- 테크창 실제 코드 발췌가 있으면 예제를 그 코드로 바꾸고 파일 경로를 밝히세요.\n'
    '- 각 단계에서 "왜 이렇게 되는지"를 한 번 더 파고들고, 직접 해보기를 단계별 체크리스트로 만드세요.\n'
    '- 분량은 {target}. 같은 말을 늘려 분량을 채우지 마세요.\n\n'
    '[기존 회차]\nTITLE: {subject}\n---\n{content}\n'
)


# ───────────────────────────── 점수
def series_rubric_text() -> str:
    return '\n'.join(f'- {k} ({int(w * 100)}%): {desc}' for k, (w, desc) in SERIES_RUBRIC.items())


def compute_series_score(scores: dict) -> int:
    total = 0.0
    for key, (weight, _) in SERIES_RUBRIC.items():
        try:
            v = float(scores.get(key, 0))
        except (TypeError, ValueError):
            v = 0.0
        total += weight * min(5.0, max(1.0, v)) / 5 * 100
    return round(total)


def _median_scores(panel: list) -> dict:
    out = {}
    for key in SERIES_RUBRIC:
        vals = [float(qa['scores'][key]) for qa in panel
                if isinstance(qa.get('scores'), dict) and str(qa['scores'].get(key, '')).replace('.', '', 1).isdigit()]
        if vals:
            out[key] = statistics.median(vals)
    return out


# ───────────────────────────── 도우미
def episode_label(key: str, no: int) -> str:
    total = len(OUTLINES[key]) - 1
    return '0편 · 오리엔테이션' if no == 0 else f'{no}편 (총 {total}편 중)'


def structure(key: str, no: int) -> str:
    return STRUCTURES[key].format(series_title=SERIES[key]['title'], episode_label=episode_label(key, no))


def outline_of(key: str, no: int) -> dict | None:
    return next((o for o in OUTLINES[key] if o['no'] == no), None)


def plan_text(key: str, outline: dict) -> str:
    labels = SERIES[key].get('outline_labels') or DEFAULT_OUTLINE_LABELS
    lines = [f'{no_title(outline)}'] + [f'{label}: {outline[k]}' for k, label in labels.items() if outline.get(k)]
    return '\n'.join(lines)


def no_title(outline: dict) -> str:
    return f"{outline['no']}편 「{outline['title']}」"


def normalize_title(no: int, title: str) -> str:
    """'N편 — 제목' 형식으로 맞춘다(목록·검색에서 몇 번째 회차인지 바로 보이게). 0편은 그대로."""
    title = re.sub(r'^\s*\d+\s*편\s*[—\-:·]?\s*', '', title or '').strip()
    return title if no == 0 else f'{no}편 — {title}'


def previous_summaries(series_obj, before_no: int, limit: int = 4) -> str:
    if series_obj is None or not series_obj.pk:
        return ''
    eps = [e for e in series_obj.published_episodes if e.episode_number < before_no][-limit:]
    if not eps:
        return ''
    parts = [f'- {e.episode_number}편 「{e.subject}」: '
             + textwrap.shorten(e.content.replace('\n', ' '), width=220, placeholder=' …') for e in eps]
    return ('\n[이전 회차 요약 — "지난 이야기"에서 이어받고, 이미 설명한 개념은 전제로 쓰세요]\n'
            + '\n'.join(parts) + '\n')


def precheck(key: str, content: str) -> list:
    """기계로 판별되는 결함 — 분량·필수 소제목·H1·코드 블록·문체·서명."""
    issues = []
    length = P.body_length(content)
    if length < MIN_CHARS[key]:
        issues.append(f'분량 {length}자 — 하한 {MIN_CHARS[key]:,}자 미달(권장 {TARGET[key]})')
    missing = [h for h in REQUIRED_HEADINGS.get(key, []) if h not in content]
    if missing:
        issues.append('필수 소제목 누락: ' + ', '.join(missing))
    if re.search(r'^# ', content, re.M):
        issues.append('본문에 H1(#) 머리말 — 제목은 TITLE 줄에만')
    if key == 'django' and '```' not in content:
        issues.append('코드 블록 없음 — 이 연재는 실제 코드를 보여 줘야 함')
    offenders, st = audit_style(content)
    if st['total'] >= 5 and st['plain_ratio'] > P.PLAIN_STYLE_LIMIT:
        issues.append(f"평서체 {st['plain']}문장 — 존댓말로 통일. 예: {offenders[0][:50] if offenders else ''}")
    if '테크창 연구팀' not in content[-400:]:
        issues.append('마지막 서명(시리즈·회차·테크창 연구팀) 누락')
    return issues


def _fix(writer, key, no, subject, content, who, issues) -> tuple:
    raw = ask_agent(writer, FIX_PROMPT.format(who=who, issues='\n'.join(f'- {i}' for i in issues),
                                              subject=subject, content=content, structure=structure(key, no)),
                    max_tokens=MAX_TOKENS, tools=tuple(SERIES[key].get('tools', ())))
    return P.safe_rewrite(raw, subject, content)


def check_episode(key: str, no: int, subject: str, content: str) -> dict:
    res = ask_agent_json('checker', CHECK_PROMPT.format(
        context=SERIES[key].get('context', ''), sources=source_block(key, no), subject=subject, content=content),
        max_tokens=6000, tools=WEB_TOOLS)
    claims = [c for c in (res.get('claims') or []) if isinstance(c, dict) and c.get('claim')]
    bad = [c for c in claims if c.get('status') in P.BAD_CLAIMS]
    critical = [str(c) for c in (res.get('critical') or []) if str(c).strip()]
    verdict = 'revise' if (bad or critical) else 'pass'
    return {'verdict': verdict, 'claims': claims, 'bad': bad, 'critical': critical}


def review_episode(key: str, no: int, subject: str, content: str, check: dict, critique: dict) -> dict:
    cfg, outline = SERIES[key], outline_of(key, no) or {'no': no, 'title': subject}
    length = P.body_length(content)
    offenders, st = audit_style(content)
    style = (f"평서체 {st['plain']}/{st['total']}문장" if st['plain_ratio'] > P.PLAIN_STYLE_LIMIT
             else f"존댓말 통일 ({st['polite']}문장)")
    prompt = QA_PROMPT.format(
        series=cfg['title'], audience=cfg['audience'], plan=plan_text(key, outline),
        check=json.dumps({k: check.get(k) for k in ('verdict', 'bad', 'critical')}, ensure_ascii=False)[:2500],
        critique=P.critique_text(critique), length=length, target=TARGET[key], style=style,
        rubric=series_rubric_text(), subject=subject, content=content)
    qa = ask_agent_json('editor', prompt, max_tokens=3000)
    first = compute_series_score(qa.get('scores') if isinstance(qa.get('scores'), dict) else {})
    if abs(first - P.ACCEPT_SCORE) <= P.REVIEW_PANEL_BAND:      # 경계 점수면 세 번 심사해 항목별 중앙값
        panel = [qa] + [ask_agent_json('editor', prompt, max_tokens=3000) for _ in range(2)]
        qa = dict(qa, scores=_median_scores(panel))
    scores = qa.get('scores') if isinstance(qa.get('scores'), dict) else {}
    fatal = [f for f in (qa.get('fatal') or []) if isinstance(f, str)]
    issues = [i for i in (qa.get('issues') or []) if isinstance(i, str)]
    # 시스템이 직접 확인하는 결함 — 모델이 놓쳐도 강제
    if length < MIN_CHARS[key] and 'too_short' not in fatal:
        fatal.append('too_short')
        issues.append(f'본문 {length}자 — 하한 {MIN_CHARS[key]:,}자 미달')
    missing = [h for h in REQUIRED_HEADINGS.get(key, []) if h not in content]
    if missing and 'structure_broken' not in fatal:
        fatal.append('structure_broken')
        issues.append('필수 소제목 누락: ' + ', '.join(missing))
    if st['total'] >= 5 and st['plain_ratio'] > P.PLAIN_STYLE_LIMIT and 'style_broken' not in fatal:
        fatal.append('style_broken')
    if check.get('critical') and 'code_wrong' not in fatal:
        fatal.append('code_wrong')
        issues.append('팩트체크 치명 지적 미해결: ' + '; '.join(check['critical'])[:200])
    if critique and critique.get('verdict') == 'reject' and 'unreadable' not in fatal:
        fatal.append('unreadable')
    score = compute_series_score(scores)
    return {**qa, 'scores': scores, 'fatal': fatal, 'issues': issues, 'score': score, 'length': length,
            'verdict': P.verdict_of(score, fatal), 'rubric': 'series'}


def qa_line(qa: dict) -> str:
    v = {'accept': '발행', 'minor': '수정 요청', 'major': '보류(운영자 검수)'}.get(qa['verdict'], qa['verdict'])
    fatal = f" · 치명결함 {','.join(qa['fatal'])}" if qa.get('fatal') else ''
    return f"편집 심사 {qa['score']}/100 ({qa['length']}자){fatal} → {v}: {qa.get('notes', '')}"


def critique_line(cr: dict) -> str:
    ko = {'recommend': '추천', 'revise': '수정 후 재검토', 'reject': '반대'}
    head = f"평론 {ko.get(cr.get('verdict'), cr.get('verdict', ''))}"
    issues = cr.get('issues') or []
    if issues:
        head += f" · 지적 {len(issues)}건 — 「{issues[0].get('quote', '')[:32]}」 {issues[0].get('why', '')[:60]}"
    return f"{head}: {cr.get('reason', '')[:100]}"


# ───────────────────────────── 발행
def publish(draft: ColumnDraft, *, by=None):
    """연재 원고 발행 — 리메이크면 대상 글을 제자리 갱신(URL·조회수 유지), 아니면 새 회차로 만든다."""
    from common.management.commands.auto_write_columns import _get_or_create_bot_user
    from community.models import Category, ColumnSeries, Question

    key, cfg = draft.series_key, SERIES[draft.series_key]
    if draft.target_question_id:
        q = draft.target_question
        q.subject, q.content, q.modify_date = draft.subject, draft.content, timezone.now()
        q.save()
    else:
        series = ColumnSeries.objects.get(slug=cfg['slug'])
        q = Question.objects.create(author=_get_or_create_bot_user(), subject=draft.subject, content=draft.content,
                                    create_date=timezone.now(), category=Category.objects.get(name=cfg['category_name']),
                                    series=series, episode_number=draft.episode_number)
    # 한 글에는 메이킹 오브 하나 — 이전 리메이크 원고가 붙어 있으면 떼어 낸다
    ColumnDraft.objects.filter(question=q).exclude(pk=draft.pk).update(question=None)
    draft.question, draft.status = q, ColumnDraft.STATUS_PUBLISHED
    if by is not None:
        draft.decided_by, draft.decided_at = by, timezone.now()
    draft.save()
    return q


# ───────────────────────────── 제작
def _recorder(draft, dry, out):
    def rec(agent, action, text):
        out(f'  [{AGENTS[agent]["name"] if agent in AGENTS else agent}] {text[:110]}')
        if not dry and draft is not None:
            log(agent, action, text, draft=draft)
    return rec


def produce_episode(key: str, no: int, *, target=None, dry: bool = False, out=print) -> dict:
    """회차 1편을 연구실 검증을 거쳐 만든다. target(Question)이 있으면 리메이크.

    반환: {'status': 'published'|'updated'|'hold'|'failed'|'dry', 'score', 'question', 'draft'}
    """
    from community.models import ColumnSeries

    cfg, outline = SERIES[key], outline_of(key, no)
    if outline is None:
        return {'status': 'failed', 'reason': f'목차에 {no}편 없음'}
    writer = TOPIC_AGENT[TOPIC_KEY]
    series_obj = ColumnSeries.objects.filter(slug=cfg['slug']).first()
    mode = '리메이크' if target is not None else '새 회차'
    draft = None if dry else ColumnDraft.objects.create(
        topic=TOPIC_KEY, status=ColumnDraft.STATUS_FAILED, series_key=key, episode_number=no,
        target_question=target, brief=f"[연재·{mode}] {cfg['title']} · {no_title(outline)}"[:300])
    rec = _recorder(draft, dry, out)
    try:
        live.mark('draft', writer, TOPIC_KEY)
        prompt = (f"[연재 지침]\n{cfg['system_prompt']}\n\n시리즈: {cfg['title']} — {cfg['subtitle']}\n"
                  f"독자: {cfg['audience']}\n\n이번 회차:\n{plan_text(key, outline)}\n{cfg.get('context', '')}"
                  f'{source_block(key, no)}{previous_summaries(series_obj, no)}')
        if target is not None:
            prompt += REMAKE_RULE.format(target=TARGET[key], subject=target.subject, content=target.content)
        prompt += f'\n위 내용으로 아래 형식에 맞춰 회차를 작성하세요.\n{structure(key, no)}'
        subject, content = P.parse_output(ask_agent(writer, prompt, max_tokens=MAX_TOKENS,
                                                    tools=tuple(cfg.get('tools', ()))))
        if not content.strip():
            raise RuntimeError('집필 응답이 비었습니다')
        subject = normalize_title(no, subject)
        rec(writer, 'draft', f'초안 완성: {subject} ({P.body_length(content)}자)')
        return gate(draft, key, no, subject, content, target=target, dry=dry, out=out)
    except Exception as exc:
        return _failed(draft, key, no, exc)


def revise_draft(draft: ColumnDraft, note: str, *, by=None, out=print) -> dict:
    """보류된 연재 원고를 운영자 지시대로 고쳐 다시 검증한다(관리 화면 '수정 지시')."""
    key, no = draft.series_key, draft.episode_number
    writer = TOPIC_AGENT[TOPIC_KEY]
    rec = _recorder(draft, False, out)
    try:
        log('lead', 'admin_note', f'운영자 지시: {note}'[:300], draft=draft)
        live.mark('revise', writer, TOPIC_KEY)
        subject, content, ok, why = _fix(writer, key, no, draft.subject, draft.content, '운영자 검토에서', [note])
        if not ok:
            rec(writer, 'revise', f'운영자 지시 재작성 실패 — {why}')
            draft.status = ColumnDraft.STATUS_HOLD
            draft.save(update_fields=['status'])
            return {'status': 'hold', 'draft': draft}
        subject = normalize_title(no, subject)
        rec(writer, 'revise', f'운영자 지시 반영해 재작성: {subject} ({P.body_length(content)}자)')
        return gate(draft, key, no, subject, content, target=draft.target_question, by=by, out=out)
    except Exception as exc:
        return _failed(draft, key, no, exc)


def _failed(draft, key, no, exc) -> dict:
    logger.exception('연재 회차 제작 실패: %s %s편', key, no)
    if draft is not None:
        draft.status = ColumnDraft.STATUS_FAILED
        draft.save(update_fields=['status'])
    return {'status': 'failed', 'reason': str(exc)[:200], 'draft': draft}


def gate(draft, key: str, no: int, subject: str, content: str, *, target=None, by=None, dry: bool = False,
         out=print) -> dict:
    """연구실 검증과 판정 — 자동 점검 → 팩트체크 → 평론 → 편집 심사(→ 1회 보완·재심) → 발행·갱신·보류."""
    writer = TOPIC_AGENT[TOPIC_KEY]
    rec = _recorder(draft, dry, out)
    stages = StageRecorder(draft=draft, dry=dry)

    # 1) 자동 점검(코드)
    flaws = precheck(key, content)
    stages.record('precheck', 'editor', {'issues': flaws}, text=content)
    if flaws:
        rec('editor', 'precheck', f'초안 자동 점검 {len(flaws)}건: {flaws[0][:90]}')
        subject, content, ok, why = _fix(writer, key, no, subject, content, '자동 점검에서', flaws)
        rec(writer, 'revise', f'자동 점검 지적 반영해 재작성 ({P.body_length(content)}자)' if ok
            else f'재작성 실패 — {why}')
    else:
        rec('editor', 'precheck', '초안 자동 점검 통과')

    # 2) 팩트체크 → 지적 반영 → 재검증
    live.mark('check', 'checker', TOPIC_KEY)
    check = check_episode(key, no, subject, content)
    stages.record('check', 'checker', check, kind='report', sender='checker', recipient='editor')
    rec('checker', 'check', f"팩트체크 {check['verdict']}: 확인 필요 {len(check['bad'])}건"
        + (f", 치명 {len(check['critical'])}건" if check['critical'] else ''))
    if check['verdict'] == 'revise':
        notes = [f"{c.get('claim', '')}: {c.get('note', '')}" for c in check['bad']] + check['critical']
        subject, content, ok, why = _fix(writer, key, no, subject, content, '팩트체크(검증관)에서', notes)
        if ok:
            rec(writer, 'revise', f"팩트체크 {len(notes)}건 반영해 재작성 ({P.body_length(content)}자)")
            live.mark('check', 'checker', TOPIC_KEY)
            again = check_episode(key, no, subject, content)
            check = {**again, 'first': {k: check[k] for k in ('verdict', 'bad', 'critical')}}
            rec('checker', 'check', f"재검증 {again['verdict']}"
                + (f": 치명 {len(again['critical'])}건" if again['critical'] else ''))
        else:
            rec(writer, 'revise', f'재작성 실패 — {why}')

    # 3) 평론 → 4) 편집 심사 → 미달이면 1회 보완·재심
    critique = P.step_critique(subject, content)
    rec('critic', 'critique', critique_line(critique))
    live.mark('review', 'editor', TOPIC_KEY)
    qa = review_episode(key, no, subject, content, check, critique)
    stages.record('review', 'editor', qa)
    rec('editor', 'qa', qa_line(qa))
    reviews = 1
    if qa['verdict'] != 'accept':
        notes = qa['issues'] + [f"평론: 「{i.get('quote', '')[:40]}」 — {i.get('fix', '')}"
                                for i in (critique.get('issues') or [])[:3] if isinstance(i, dict)]
        subject, content, ok, why = _fix(writer, key, no, subject, content, '편집 심사에서', notes)
        if ok:
            rec(writer, 'revise', f'편집 심사 지적 반영해 재작성 ({P.body_length(content)}자)')
            if check.get('critical'):
                live.mark('check', 'checker', TOPIC_KEY)
                check = check_episode(key, no, subject, content)
                rec('checker', 'check', f"재검증 {check['verdict']}")
            live.mark('review', 'editor', TOPIC_KEY)
            qa = review_episode(key, no, subject, content, check, critique)
            stages.record('review', 'editor', qa, attempt=2)
            rec('editor', 'qa', '재심 ' + qa_line(qa))
            reviews += 1
        else:
            rec(writer, 'revise', f'편집 심사 재작성 실패 — {why}')

    subject = normalize_title(no, subject)
    result = {'score': qa['score'], 'verdict': qa['verdict'], 'subject': subject}
    if dry:
        out(f'\n[dry-run] {qa["score"]}점 · {qa["verdict"]}\nTITLE: {subject}\n{content}')
        return {**result, 'status': 'dry', 'content': content}

    draft.subject, draft.content = subject, content
    draft.check_report, draft.qa_report = check, qa
    draft.revisions = (draft.revisions or 0) + reviews - 1
    if qa['verdict'] == 'accept':
        live.mark('publish', 'lead', TOPIC_KEY)
        q = publish(draft, by=by)
        rec('lead', 'publish', (f'리메이크 반영(제자리 갱신): {subject} (id={q.pk}, {qa["score"]}점)' if target
                                else f'발행: {subject} (id={q.pk}, {qa["score"]}점)'))
        return {**result, 'status': 'updated' if target else 'published', 'question': q, 'draft': draft}
    draft.status = ColumnDraft.STATUS_HOLD
    draft.save()
    why = '; '.join(qa['issues'][:2])[:150]
    rec('lead', 'hold', f'보류({qa["verdict"]}, {qa["score"]}점): {subject} — {why}')
    return {**result, 'status': 'hold', 'draft': draft}
