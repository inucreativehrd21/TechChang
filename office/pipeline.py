"""
칼럼 제작 파이프라인 — 실제 연구·편집 조직의 발행 절차를 그대로 옮긴 단계 정의.

  1) 기획서(Commissioning brief)  팀장이 주제·논점·필요한 데이터·피해야 할 것을 지시
  2) 집필(Drafting)               담당 칼럼니스트
  3) 팩트체크(Fact-check)         검증관이 주장 단위로 verified / unverifiable / wrong 판정
  4) 수정(Author revision)        팩트체크 지적 반영 (필요 시 1회)
  5) 데이터 시각화(Data desk)     차트 담당이 본문 수치를 차트·표로
  6) 편집 심사(Editorial review)  팀장이 루브릭 6개 항목을 1~5점으로 채점 → 가중 100점 환산
  7) 판정(Decision)               Accept(발행) / Minor revision(자동 1회 재작성 후 재심) / Major revision(보류)

점수 공식은 파이썬에서 계산한다(모델이 총점을 임의로 매기지 못하게). 치명 결함이 하나라도 있으면
점수와 무관하게 보류한다.

office_publish(신규 제작)와 office_revise(관리자 코멘트 반영 재작성)가 이 모듈을 공유한다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from django.utils import timezone

from common.management.commands.auto_write_columns import COLUMN_STRUCTURE, TOPICS
from .agents import TOPIC_AGENT as TOPIC_AGENT_OF
from .models import ColumnDraft
from .services import ask_agent, ask_agent_json, chart_markdown, render_chart

# ───────────────────────────── 심사 기준 (편집 루브릭)
#   항목: (가중치, 설명) — 각 항목을 1~5점으로 채점해 가중합 → 100점 환산
RUBRIC = {
    'structure':  (0.15, '구조 준수 — 리드·왜 지금인가·숫자로 보는 현황·본론·현장의 변화·시사점·맺음말·참고 자료'),
    'depth':      (0.25, '심층성·독창성 — 메커니즘·반론·실행 방법까지 파고들었는지, 분량 대비 밀도'),
    'evidence':   (0.25, '데이터 근거 — 비교 가능한 수치 3~5개와 출처 명시, 팩트체크 통과 여부'),
    'logic':      (0.15, '논리·정확성 — 주장과 근거의 연결, 과장·비약 없음'),
    'readability': (0.10, '가독성·문체 — 존댓말 일관, 용어 설명, 문장 길이'),
    'visual':     (0.10, '시각자료 — 차트·표가 본문 수치와 일치하고 해석이 붙어 있는지'),
}
ACCEPT_SCORE = 80          # 이상이면 발행 (전 항목 4점 = 80점 = 발행 가능 수준)
MINOR_SCORE = 65           # 이상 80 미만이면 자동 1회 수정 후 재심, 미만이면 보류(Major)
MIN_CHARS = 2200           # 본문 하한 (목표 2,500~3,500자)
MAX_AUTO_REVISIONS = 1     # Minor revision 자동 재작성 횟수


# ───────────────────────────── 프롬프트
BRIEF_PROMPT = (
    '팀장으로서 이번 칼럼의 **집필 의뢰서**를 작성하세요. 칼럼니스트가 이것만 보고 바로 쓸 수 있어야 합니다.\n\n'
    '[분야] {topic_hint}\n[독자] {audience}\n[결정된 주제] {subject}\n[회의에서 나온 관점·근거] {detail}\n'
    '[최근 발행 칼럼 제목 — 소재가 겹치면 안 됨]\n{recent}\n\n'
    '출력 JSON: {{"angle": "이 칼럼만의 각도 한 문장 — 흔한 소개글과 어떻게 다른지", '
    '"questions": ["본문이 반드시 답해야 할 질문", ...3~4개], '
    '"data_needed": ["찾아 넣어야 할 지표·통계 (기관·보고서 수준으로 구체적으로)", ...3~5개], '
    '"cases": ["다룰 만한 국내외 사례 후보", ...2~3개], '
    '"counterpoint": "반드시 짚어야 할 반론·한계 한 문장", '
    '"avoid": ["피해야 할 서술·소재", ...2~3개]}}'
)

DRAFT_PROMPT = (
    '오늘 날짜: {today}\n담당 분야: {topic_hint}\n독자: {audience}\n\n'
    '{subject_block}'
    '[팀장 집필 의뢰서]\n'
    '- 각도: {angle}\n- 반드시 답할 질문: {questions}\n- 넣어야 할 데이터: {data_needed}\n'
    '- 사례 후보: {cases}\n- 짚어야 할 반론: {counterpoint}\n- 피할 것: {avoid}\n'
    '{avoid_titles}\n{structure}'
)

CHECK_PROMPT = (
    '팩트체크 단계입니다. 아래 칼럼 초안을 주장 단위로 검증하세요.\n\n'
    '[이미 발행한 칼럼 제목]\n{titles}\n\n[초안]\nTITLE: {subject}\n{content}\n\n'
    '판정 기준: (1) 핵심 소재가 기존 칼럼과 겹치면 중복. (2) 수치·인용·사례는 실재하고 널리 공표된 것이어야 하며, '
    '확인 불가하거나 지어낸 것으로 보이면 지목. (3) 과장·최신성 오류.\n'
    '**중요**: 수치를 문제 삼을 때는 "삭제하라"가 아니라 **어떤 공표 통계로 바꾸면 되는지**를 제시하세요. '
    '이 칼럼은 데이터 근거 섹션과 차트를 포함해야 하므로, 수치를 모두 걷어내는 방향의 지적은 하지 않습니다.\n'
    '출력 JSON: {{"verdict": "pass" 또는 "revise", "duplicate": true/false, "similar_titles": ["..."], '
    '"claims": [{{"claim": "문장 요약", "status": "verified|unverifiable|wrong", "note": "근거 또는 대체할 통계 제안"}}], '
    '"notes": "수정이 필요하면 무엇을 어떻게 고칠지 구체적으로 3~6줄"}}\n'
    'unverifiable 이나 wrong 이 2개 이상이거나 duplicate 이면 revise.'
)

REVISE_PROMPT = (
    '팩트체크에서 수정 요청을 받았습니다. 지적을 모두 반영해 칼럼 전체를 다시 쓰세요. '
    '확인 불가한 수치는 삭제하지 말고 **검증 가능한 공표 통계로 교체**하고, 중복 지적이 있으면 관점을 바꾸세요. '
    '"## 숫자로 보는 현황"의 비교 가능한 수치 3~5개는 반드시 유지합니다.\n\n'
    '[팩트체크 지적]\n{notes}\n[문제 항목]\n{claims}\n\n[원래 초안]\nTITLE: {subject}\n---\n{content}\n\n{structure}'
)

EDITOR_REVISE_PROMPT = (
    '편집 심사에서 수정 요청(Minor revision)을 받았습니다. 아래 지적을 모두 반영해 칼럼 전체를 다시 쓰세요.\n\n'
    '[편집 심사 지적]\n{issues}\n[팀장 총평]\n{notes}\n\n'
    '[현재 칼럼]\nTITLE: {subject}\n---\n{content}\n\n'
    '주의: 본문에 이미 들어간 차트·표 마크다운은 그대로 두되, 수치를 고치면 표도 함께 고치세요.\n\n{structure}'
)

ADMIN_REVISE_PROMPT = (
    '운영자(관리자)가 이 칼럼을 검수하고 수정을 지시했습니다. **운영자 지시가 최우선**입니다. '
    '지시를 하나도 빠뜨리지 말고 반영해 칼럼 전체를 다시 쓰세요.\n\n'
    '[운영자 지시]\n{admin_note}\n\n[직전 편집 심사 지적]\n{qa_issues}\n\n[팩트체크 지적]\n{check_notes}\n\n'
    '[현재 칼럼]\nTITLE: {subject}\n---\n{content}\n\n'
    '주의: 운영자가 특정 부분만 고치라고 했다면 나머지 문장은 최대한 보존합니다. '
    '본문에 이미 들어간 차트·표 마크다운은 유지하되, 수치가 바뀌면 함께 갱신하세요.\n\n{structure}'
)

CHART_PROMPT = (
    '데이터 시각화 단계입니다. 아래 칼럼 본문에서 차트·표로 만들 수 있는 수치를 찾으세요. **본문에 명시된 숫자만** 씁니다.\n'
    '이 칼럼에는 "## 숫자로 보는 현황" 섹션이 있으므로 대개 시각화할 수치가 있습니다. '
    '비교 가능한 값이 3개 이상이면 차트(mode="chart"), 2개뿐이면 표만(mode="table") 만드세요. '
    '숫자가 전혀 없을 때만 has_data=false 로 답합니다.\n\n[본문]\n{content}\n\n'
    '출력 JSON: {{"has_data": true/false, "mode": "chart" 또는 "table", "reason": "판단 근거 한 줄", '
    '"spec": {{"type": "bar|hbar|line", "title": "무엇을 비교하는지 드러나는 한글 제목", '
    '"labels": ["항목1", "항목2", ...], "series": [{{"name": "계열명", "values": [숫자, 숫자, ...]}}], '
    '"unit": "%", "source": "본문에 적힌 기관·보고서명"}}, '
    '"insert_after_heading": "삽입할 ## 헤더 텍스트(본문에 있는 그대로, 보통 \'숫자로 보는 현황\')", '
    '"caption": "차트가 보여주는 핵심 한 문장"}}\n'
    '규칙: labels 와 각 series.values 개수는 반드시 같아야 합니다. values 에는 단위·기호 없이 숫자만 넣습니다.'
)

QA_PROMPT = (
    '편집 심사 단계입니다. 편집장으로서 아래 칼럼을 **항목별로** 채점하세요. 총점은 시스템이 계산하므로 매기지 마세요.\n\n'
    '[팩트체크 보고]\n{check}\n\n[본문 글자 수] {length}자 (목표 2,500~3,500자)\n[시각자료] {visual}\n\n'
    '[칼럼]\nTITLE: {subject}\n{content}\n\n'
    '각 항목을 1~5점으로 채점합니다. 5=흠잡을 데 없음, 4=사소한 보완, 3=수정 필요, 2=상당한 결함, 1=기준 미달.\n'
    '{rubric}\n\n'
    '치명 결함(fatal)은 다음 중 해당하는 것만 배열로 적습니다: '
    '"unverified_data"(확인 불가 수치가 본문에 남아 있음), "duplicate"(기존 칼럼과 소재 중복), '
    '"too_short"(목표 분량에 크게 못 미침), "no_evidence"(비교 가능한 수치가 사실상 없음), '
    '"structure_broken"(필수 섹션 누락), "overclaim"(근거 없는 단정)\n\n'
    '출력 JSON: {{"scores": {{"structure": 1~5, "depth": 1~5, "evidence": 1~5, "logic": 1~5, '
    '"readability": 1~5, "visual": 1~5}}, "fatal": ["..."], "strengths": "한 줄", '
    '"issues": ["구체적 문제 — 어느 섹션의 무엇을 어떻게 고쳐야 하는지", ...], '
    '"notes": "운영자에게 남길 한 줄"}}'
)


# ───────────────────────────── 보조
def rubric_text() -> str:
    return '\n'.join(f'- {k}: {desc}' for k, (_, desc) in RUBRIC.items())


def body_length(content: str) -> int:
    """참고 자료·이미지·표를 뺀 본문 글자 수."""
    body = re.split(r'\n##\s*참고\s*자료', content)[0]
    body = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', body)
    body = re.sub(r'^\|.*\|$', '', body, flags=re.M)
    return len(re.sub(r'\s+', ' ', body).strip())


def strip_visual_block(content: str) -> str:
    """앞서 삽입한 차트·표 블록을 걷어낸다 (본문이 다시 쓰였을 때 수치와 맞는 시각화를 새로 만들기 위해)."""
    # 삽입 블록의 모양: [이미지] + **제목**(단위) + 표 + *출처: …* + [캡션]
    block = re.compile(
        r'(?:^!\[[^\]]*\]\([^)]*\)[ \t]*\n+)?'      # 차트 이미지 (없을 수도)
        r'(?:^\*\*[^\n]*\*\*[^\n]*\n+)?'            # 표 제목
        r'(?:^\|[^\n]*\|[ \t]*\n)+'                 # 표 본체
        r'(?:\n*^\*출처:[^\n]*\*[ \t]*\n)?',        # 출처 주석
        re.M)
    text = block.sub('', content)
    text = re.sub(r'^!\[[^\]]*\]\([^)]*\)[ \t]*\n?', '', text, flags=re.M)   # 표 없이 이미지만 남은 경우
    return re.sub(r'\n{3,}', '\n\n', text).strip() + '\n'


def has_visual(content: str) -> bool:
    return '![' in content or bool(re.search(r'^\|.*\|$', content, flags=re.M))


def compute_score(scores: dict) -> int:
    """루브릭 가중합 → 100점 환산. 항목 점수 v(1~5) → v/5*100 (5=100, 4=80, 3=60)."""
    total = 0.0
    for key, (weight, _) in RUBRIC.items():
        try:
            v = float(scores.get(key, 0))
        except (TypeError, ValueError):
            v = 0.0
        v = min(5.0, max(1.0, v))
        total += weight * v / 5 * 100
    return round(total)


def verdict_of(score: int, fatal: list) -> str:
    """accept / minor / major — 치명 결함이 있으면 점수와 무관하게 major."""
    if fatal:
        return 'major'
    if score >= ACCEPT_SCORE:
        return 'accept'
    if score >= MINOR_SCORE:
        return 'minor'
    return 'major'


def insert_after_heading(content: str, heading: str, block: str) -> str:
    """heading(## …) 섹션 끝(다음 ## 직전)에 block 삽입. 못 찾으면 '숫자로 보는' → '시사점' 순으로 폴백."""
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
            if l.startswith('## 숫자로 보는'):
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


def safe_rewrite(raw: str, prev_subject: str, prev_content: str) -> tuple:
    """재작성 결과 검증 — 비었거나 직전 원고의 60% 미만이면 **이전 원고를 유지**한다.
    (모델이 빈 응답·잘린 응답을 돌려줘도 좋은 초안을 잃지 않게 하는 안전장치.)
    반환: (subject, content, ok, reason)"""
    subject, content = parse_output(raw)
    prev_len = body_length(prev_content)
    new_len = body_length(content)
    if not content.strip():
        return prev_subject, prev_content, False, '재작성 응답이 비어 이전 원고 유지'
    if prev_len and new_len < prev_len * 0.6:
        return prev_subject, prev_content, False, f'재작성본이 너무 짧아({new_len}자 < {prev_len}자의 60%) 이전 원고 유지'
    return subject, content, True, ''


def parse_output(raw: str) -> tuple:
    """TITLE: … / --- / 본문 분리."""
    lines = raw.splitlines()
    title, body_start = '', 0
    for i, line in enumerate(lines):
        if line.startswith('TITLE:'):
            title = line[6:].strip()[:200]
        elif line.strip() == '---' and title:
            body_start = i + 1
            break
    if not title:
        for line in lines:
            stripped = line.lstrip('#').strip()
            if stripped:
                title = stripped[:200]
                break
    return title or '자동 생성 칼럼', '\n'.join(lines[body_start:]).lstrip('\n')


def recent_titles(topic_key: str, limit: int = 20) -> list:
    from community.models import Question
    from .services import BOT_USERNAME
    return list(Question.objects.filter(
        author__username=BOT_USERNAME, category__name=TOPICS[topic_key]['category_name'], is_deleted=False,
    ).order_by('-create_date').values_list('subject', flat=True)[:limit])


# ───────────────────────────── 단계
def step_brief(topic_key: str, brief_decision, recent: list) -> dict:
    """1) 기획서 — 팀장이 집필 지시를 만든다."""
    topic = TOPICS[topic_key]
    chosen = (brief_decision.chosen or {}) if brief_decision else {}
    return ask_agent_json('lead', BRIEF_PROMPT.format(
        topic_hint=topic['topic_hint'], audience=topic['audience'],
        subject=chosen.get('title', '(편집회의 결정 없음 — 칼럼니스트가 직접 선정)'),
        detail=chosen.get('detail', ''), recent='\n'.join(f'- {t}' for t in recent) or '(없음)'), max_tokens=3000)


def step_draft(topic_key: str, brief_decision, brief: dict, recent: list) -> tuple:
    """2) 집필."""
    topic = TOPICS[topic_key]
    chosen = (brief_decision.chosen or {}) if brief_decision else {}
    if chosen:
        subject_block = ('이번 칼럼 주제는 편집회의에서 결정되었습니다. 이 주제로 작성하세요.\n'
                         f"- 주제: {chosen.get('title', '')}\n- 관점·근거: {chosen.get('detail', '')}\n\n")
    else:
        subject_block = '위 분야에서 현재 가장 주목받고 있는 트렌드나 이슈 하나를 선정하여 작성하세요.\n\n'
    avoid_titles = ''
    if recent:
        avoid_titles = '\n**[이미 다룬 주제 - 반드시 피하세요]**\n' + '\n'.join(f'- {t}' for t in recent) + '\n'

    def lst(key):
        v = brief.get(key) or []
        return '; '.join(str(x) for x in v) if isinstance(v, list) else str(v)

    prompt = DRAFT_PROMPT.format(
        today=datetime.now().strftime('%Y년 %m월 %d일'), topic_hint=topic['topic_hint'], audience=topic['audience'],
        subject_block=subject_block, angle=brief.get('angle', ''), questions=lst('questions'),
        data_needed=lst('data_needed'), cases=lst('cases'), counterpoint=brief.get('counterpoint', ''),
        avoid=lst('avoid'), avoid_titles=avoid_titles, structure=COLUMN_STRUCTURE)
    return parse_output(ask_agent(TOPIC_AGENT_OF[topic_key], prompt, max_tokens=12000))


def step_check(subject: str, content: str, recent: list) -> dict:
    """3) 팩트체크."""
    return ask_agent_json('checker', CHECK_PROMPT.format(
        titles='\n'.join(f'- {t}' for t in recent) or '(없음)', subject=subject, content=content), max_tokens=4000)


def step_author_revise(topic_key: str, subject: str, content: str, check: dict) -> tuple:
    """4) 팩트체크 지적 반영. 반환: (subject, content, ok, reason)"""
    bad = [c for c in check.get('claims', []) if c.get('status') in ('unverifiable', 'wrong')]
    raw = ask_agent(TOPIC_AGENT_OF[topic_key], REVISE_PROMPT.format(
        notes=check.get('notes', ''), claims=json.dumps(bad, ensure_ascii=False),
        subject=subject, content=content, structure=COLUMN_STRUCTURE), max_tokens=12000)
    return safe_rewrite(raw, subject, content)


def step_visual(content: str, topic_key: str, *, rec, dry: bool = False) -> tuple:
    """5) 데이터 시각화. 반환: (content, chart_rel, note)"""
    res = ask_agent_json('charter', CHART_PROMPT.format(content=content), max_tokens=3000)
    spec = res.get('spec') if isinstance(res.get('spec'), dict) else None
    if not res.get('has_data') or not spec:
        note = f"수치 부족으로 생략: {res.get('reason', '')}"[:200]
        rec('charter', 'chart', note)
        return content, '', note

    chart_rel, err = '', ''
    if res.get('mode', 'chart') != 'table' and not dry:
        stem = f"{timezone.localdate():%Y%m%d}_{topic_key}_{timezone.now():%H%M%S}"
        rel, err = render_chart(spec, stem)
        chart_rel = rel or ''

    block = chart_markdown(chart_rel, spec)
    if res.get('caption'):
        block += f"\n\n{res['caption']}"
    content = insert_after_heading(content, res.get('insert_after_heading', ''), block)

    if chart_rel:
        note = f"차트+표 삽입: {spec.get('title', '')} ({spec.get('type', 'bar')}, 항목 {len(spec.get('labels') or [])}개)"
    elif err:
        note = f"차트 렌더 실패 → 표만 삽입: {err}"
    else:
        note = f"표 삽입: {spec.get('title', '')}"
    rec('charter', 'chart', note[:200])
    return content, chart_rel, note[:200]


def step_review(subject: str, content: str, check: dict, chart_rel: str) -> dict:
    """6) 편집 심사 — 항목 점수를 받아 총점·판정은 시스템이 계산."""
    visual = '차트 이미지 + 표 있음' if chart_rel else ('표 있음(차트 없음)' if has_visual(content) else '없음')
    length = body_length(content)
    qa = ask_agent_json('lead', QA_PROMPT.format(
        check=json.dumps({k: v for k, v in check.items() if k != 'first'}, ensure_ascii=False)[:2500],
        length=length, visual=visual, subject=subject, content=content, rubric=rubric_text()), max_tokens=3000)

    scores = qa.get('scores') if isinstance(qa.get('scores'), dict) else {}
    fatal = [f for f in (qa.get('fatal') or []) if isinstance(f, str)]
    # 시스템이 직접 확인하는 결함 (모델이 놓쳐도 강제)
    if length < MIN_CHARS and 'too_short' not in fatal:
        fatal.append('too_short')
        qa.setdefault('issues', []).append(f'본문 {length}자로 목표(2,500~3,500자) 미달 — 심층성 부족')
    if not has_visual(content) and 'no_evidence' not in fatal:
        fatal.append('no_evidence')
        qa.setdefault('issues', []).append('본문에 차트·표가 없음 — 데이터 근거 섹션을 보강해야 함')

    score = compute_score(scores)
    qa.update({'scores': scores, 'fatal': fatal, 'score': score, 'length': length,
               'verdict': verdict_of(score, fatal), 'rubric_version': 1})
    return qa


def publish_draft(draft: ColumnDraft, *, by=None):
    """ColumnDraft → Question 발행 + 회의 안건 소비 처리."""
    from common.management.commands.auto_write_columns import _get_or_create_bot_user
    from community.models import Category, Question

    category = Category.objects.get(name=TOPICS[draft.topic]['category_name'])
    q = Question.objects.create(author=_get_or_create_bot_user(), subject=draft.subject, content=draft.content,
                                create_date=timezone.now(), category=category)
    draft.question, draft.status = q, ColumnDraft.STATUS_PUBLISHED
    if by is not None:
        draft.decided_by, draft.decided_at = by, timezone.now()
    draft.save()
    if draft.decision and draft.decision.consumed_at is None:
        draft.decision.consumed_at = timezone.now()
        draft.decision.save(update_fields=['consumed_at'])
    return q
