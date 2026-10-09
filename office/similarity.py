"""기발행 칼럼과의 본문 대조 — 검증관의 중복 판정 근거.

검증관은 기발행 칼럼의 **제목만** 보고 중복을 판단했다. 그래서 같은 원고가 한 번은 "본문을 못 봐서
판정 불가", 다음엔 "중복"으로 흔들렸다(원고 #8, 2026-10-09). 여기서 본문 전체를 코드로 비교해
유사도와 겹치는 핵심어를 넘기고, 검증관은 그 숫자를 근거로 판단한다. 모델 호출은 없다.

방법: 마크다운·도판·참고 자료를 걷어낸 본문에서 2자 이상 어절을 뽑고, 흔한 조사·어미를 떼어
낸 뒤 (1) 어절 3-gram 자카드 유사도(문장이 겹치는지), (2) 핵심어 코사인 유사도(소재가 겹치는지)를 구한다.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# 칼럼 템플릿 섹션명·문체 어휘는 모든 글에 나오므로 소재 비교에서 뺀다
STOPWORDS = set('''
왜 지금인가 숫자로 보는 현황 현장의 변화 시사점 맺음말 참고 자료 우리가 갖춰야 할 것 그림 표 단위 출처
있습니다 합니다 됩니다 입니다 습니다 것입니다 수 있는 있는 하는 했다 한다 이 그 저 이런 그런 같은 다른
그리고 하지만 그러나 또는 또 더 가장 매우 많이 정도 경우 때문 대한 통해 위해 따라 대해 함께 다시 바로
이번 이것 그것 여기 지금 오늘 우리 여러분 필자 글 칼럼 테크창 연구팀 인천대학교 창의인재개발학과 전공심화연구모임
있습 것이 이는 하는 합니 됩니 입니 있었 없습 했습 하였
'''.split())
# 어절 끝 조사·어미 — 긴 것부터 떼어 낸다
_SUFFIXES = sorted('''
은 는 이 가 을 를 에 의 와 과 도 만 로 으로 에서 에게 께 한테 부터 까지 처럼 보다 이나 나 이며 며
입니다 합니다 됩니다 습니다 니다 하고 하며 해서 하여 하는 하던 했던 한 할 함 이다 였다 이었다 였습니다 이었습니다
들 들의 들은 들이 들을 에는 에서는 으로는 로는 와의 과의 이라는 라는 이라고 라고
'''.split(), key=len, reverse=True)

_STRIP = [
    re.compile(r'\n##\s*참고\s*자료.*', re.S),       # 참고 자료 이하
    re.compile(r'!\[[^\]]*\]\([^)]*\)'),              # 이미지
    re.compile(r'^\|.*\|\s*$', re.M),                 # 표
    re.compile(r'https?://\S+'),                      # URL
    re.compile(r'[#>*_`|\-\[\]()]'),                  # 마크다운 기호
]
_WORD = re.compile(r'[가-힣A-Za-z][가-힣A-Za-z0-9]+')

# 기준값은 운영 칼럼 61편의 모든 쌍(1,830개)으로 보정했다(2026-10-09).
# 정상 쌍의 문장 겹침 최댓값 0.051(연재 5·6편), 소재 겹침은 서로 다른 글끼리도 0.75까지 나온다
# (데이터 분야 글들이 어휘를 많이 공유). 사람이 중복 아님으로 대조한 쌍은 0.378·0.30.
DUP_SHINGLE = 0.06   # 문장 3-gram 겹침 — 이 이상이면 문장을 옮긴 수준
DUP_TOPIC = 0.80     # 소재 겹침만으로 중복이라 할 수 있는 선(관측 최댓값 위)
WATCH_TOPIC = 0.60   # 이 이상은 '논지가 같은지 확인하라'는 주의 표시만


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if len(word) > len(suf) + 1 and word.endswith(suf):
            return word[:-len(suf)]
    return word


def tokens(text: str) -> list[str]:
    for pat in _STRIP:
        text = pat.sub(' ', text)
    out = []
    for w in _WORD.findall(text):
        s = _stem(w.lower())
        if len(s) >= 2 and s not in STOPWORDS:
            out.append(s)
    return out


def _shingles(toks: list[str], n: int = 3) -> set:
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def _cosine(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    num = sum(a[k] * b[k] for k in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def compare(content_a: str, content_b: str) -> dict:
    ta, tb = tokens(content_a), tokens(content_b)
    sa, sb = _shingles(ta), _shingles(tb)
    jac = len(sa & sb) / len(sa | sb) if (sa or sb) else 0.0
    ca, cb = Counter(ta), Counter(tb)
    shared = [w for w, _ in (ca & cb).most_common(8)]
    return {'shingle': round(jac, 3), 'topic': round(_cosine(ca, cb), 3), 'shared': shared}


def similar_columns(content: str, *, limit: int = 3, exclude_question_id=None) -> list[dict]:
    """기발행 연구팀 칼럼 중 본문이 가장 비슷한 글. [{id, subject, shingle, topic, shared, duplicate}]"""
    from community.models import Question
    from office.services import BOT_USERNAME

    qs = Question.objects.filter(author__username=BOT_USERNAME, is_deleted=False).only('id', 'subject', 'content')
    if exclude_question_id:
        qs = qs.exclude(id=exclude_question_id)
    rows = []
    for q in qs:
        r = compare(content, q.content or '')
        r.update(id=q.id, subject=q.subject,
                 duplicate=r['shingle'] >= DUP_SHINGLE or r['topic'] >= DUP_TOPIC)
        rows.append(r)
    rows.sort(key=lambda r: (r['topic'] + r['shingle'] * 3), reverse=True)
    return rows[:limit]


def similarity_block(content: str, exclude_question_id=None) -> str:
    """검증관 프롬프트에 붙일 본문 대조 결과."""
    try:
        rows = similar_columns(content, exclude_question_id=exclude_question_id)
    except Exception:  # noqa: BLE001 — 대조 실패가 팩트체크를 막으면 안 된다
        return ''
    if not rows:
        return ''
    lines = ['', '', '[본문 대조 — 코드가 기발행 칼럼 본문 전체와 비교한 결과]',
             f'기준: 문장 겹침 {DUP_SHINGLE} 이상 또는 소재 겹침 {DUP_TOPIC} 이상이면 중복 후보입니다(운영 칼럼 61편으로 보정). '
             '기준 미만이면 제목이나 소재 일부가 비슷해도 duplicate 로 판정하지 마세요. '
             '기준 이상이면 핵심 논지가 실제로 같은지 확인해 판단하세요.']
    for r in rows:
        mark = ' ← 중복 후보' if r['duplicate'] else ''
        if not mark and r['topic'] >= WATCH_TOPIC:
            mark = ' ← 소재가 가까움: 핵심 논지가 같은지 확인'
        lines.append(f"- 「{r['subject']}」 문장 겹침 {r['shingle']:.2f} · 소재 겹침 {r['topic']:.2f}"
                     f" · 공통 핵심어: {', '.join(r['shared'][:6]) or '없음'}{mark}")
    return '\n'.join(lines) + '\n'
