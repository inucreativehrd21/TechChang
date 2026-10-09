"""모델 호출 없이 코드로 재는 칼럼 품질 지표.

운영 칼럼 심사에서 반복된 지적을 하나씩 겨냥한다 (2026-10 기준 8편):
- 같은 수치를 본문·캡션에서 세 번 이상 되풀이 (figure_repetition)
- 없는 표·그림을 '아래 표'처럼 가리킴 (orphan_refs)
- 제목은 단정하는데 본문은 계속 물러섬 (title_overclaim)
- 근거가 출처 한두 개에 기댐 (source_count)
- 현황 수치·참고 자료가 낡음 (recency, 최근 RECENT_YEARS 년 기준)
반복·없는 표 언급·낡은 자료는 초안 자동 점검(precheck)의 '고칠 지적'으로 쓰고, 모두 단계 기록에 남겨 비교한다.
"""
from __future__ import annotations

import re

UNITS = r'(?:%p|%|명|건|배|억|만|점|위|달러|원|시간|개국|개|곳|회|퍼센트|포인트)'
# 단위 뒤에 '월·년'이 붙으면 기간 표현(6개월·3개년)이지 수치가 아니다 — '6개월' 점검표를 '6개' 12회 반복으로 오탐했다
_NUM = re.compile(r'(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(' + UNITS + r')(?![월년])')
_REF_SPLIT = re.compile(r'\n##\s*참고\s*자료')
_TABLE_ROW = re.compile(r'^\|.*\|\s*$', re.M)
_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_HAS_TABLE = re.compile(r'^\|.*\|\s*$\n^\|\s*:?-{2,}', re.M)

# 가리키는 말 (표 / 그림·차트·그래프)
_TABLE_REF = re.compile(r'(아래|다음|위의?|앞의?)\s*표|표\s*\d+')
_FIG_REF = re.compile(r'(아래|다음|위의?|앞의?)\s*(그림|차트|그래프|도표)|(그림|도표)\s*\d+')

# 단정형 제목 표지와 본문 유보 표현
_ASSERT = re.compile(r'해야\s*한다|해야한다|반드시|무조건|틀렸다|끝났다|사라진다|망한다|유일한|결정적|정답')
_HEDGE = re.compile(r'(수\s*있습니다|수도\s*있습니다|지도\s*모릅니다|가능성이\s*있습니다|추정|단정하기\s*어렵|'
                    r'알\s*수\s*없|확인되지\s*않|직접\s*지지하지\s*못)')
_SENT_END = re.compile(r'(?<=[.?!])\s+|(?<=니다)\s+|(?<=세요)\s+')


def prose(content: str) -> str:
    """참고 자료·표·이미지를 뺀 문장 부분 (캡션은 문장이므로 남긴다)."""
    body = _REF_SPLIT.split(content or '')[0]
    body = _IMAGE.sub('', body)
    return _TABLE_ROW.sub('', body)


def _norm(num: str, unit: str) -> str:
    return num.replace(',', '') + unit


def figure_repetition(content: str, threshold: int = 3) -> list[tuple[str, int]]:
    """문장 부분에서 threshold 번 이상 나온 '수치+단위' 목록 [(값, 횟수)]."""
    counts: dict[str, int] = {}
    for num, unit in _NUM.findall(prose(content)):
        if unit == '년':
            continue
        key = _norm(num, unit)
        counts[key] = counts.get(key, 0) + 1
    return sorted([(k, n) for k, n in counts.items() if n >= threshold], key=lambda kv: -kv[1])


def orphan_refs(content: str) -> list[str]:
    """가리키는 표·그림이 원고에 없으면 그 표현 목록."""
    body = _REF_SPLIT.split(content or '')[0]
    out = []
    if not _HAS_TABLE.search(body):
        out += [m.group(0) for m in _TABLE_REF.finditer(body)]
    if not _IMAGE.search(body):
        out += [m.group(0) for m in _FIG_REF.finditer(body)]
    return list(dict.fromkeys(out))


def hedge_ratio(content: str) -> float:
    sents = [s for s in _SENT_END.split(prose(content)) if len(s.strip()) > 8]
    if not sents:
        return 0.0
    return sum(1 for s in sents if _HEDGE.search(s)) / len(sents)


def title_overclaim(subject: str, content: str, limit: float = 0.25) -> dict | None:
    """제목이 단정형인데 본문 유보 문장 비율이 limit 이상이면 근거를 돌려준다."""
    m = _ASSERT.search(subject or '')
    if not m:
        return None
    ratio = hedge_ratio(content)
    return {'marker': m.group(0), 'hedge_ratio': round(ratio, 2)} if ratio >= limit else None


def source_count(content: str) -> int:
    """참고 자료 목록의 항목 수."""
    parts = _REF_SPLIT.split(content or '', maxsplit=1)
    if len(parts) < 2:
        return 0
    refs = re.split(r'\n##\s', parts[1])[0]
    return len(re.findall(r'^\s*(?:[-*]|\d+[.)])\s+\S', refs, flags=re.M))


# ── 자료 최신성
# 급변하는 분야라 몇 년 전 자료도 이미 낡았을 수 있다. 현황 수치는 최근 RECENT_YEARS 년 안의 자료를,
# 같은 조사는 최신판을 쓴다. 고전·원전(예: 굿하트 1975)은 개념의 출처로만 인용한다.
RECENT_YEARS = 3
_YEAR = re.compile(r'(?<!\d)(19[5-9]\d|20\d\d)(?!\d)')


def _this_year() -> int:
    from django.utils import timezone
    return timezone.localdate().year


def _section(content: str, name: str) -> str:
    for s in re.split(r'\n##\s', content or ''):
        if s.startswith(name):
            return s
    return ''


def _past_years(text: str, now: int) -> list[int]:
    """연도 표기 중 올해 이하만 (2030년 목표 같은 전망치의 연도는 자료 시점이 아니다)."""
    return [int(y) for y in _YEAR.findall(text) if int(y) <= now]


def recency(content: str, now: int | None = None) -> dict:
    """현황 섹션의 가장 최근 자료 연도와, 참고 자료 중 최근 자료 수."""
    now = now or _this_year()
    data = _past_years(_section(content, '숫자로 보는 현황'), now)
    ref_years = [max(ys) for line in _section(content, '참고 자료').splitlines()
                 if (ys := _past_years(line, now))]
    cutoff = now - RECENT_YEARS
    return {
        'cutoff': cutoff,
        'data_latest': max(data) if data else None,
        'refs_dated': len(ref_years),
        'refs_recent': sum(1 for y in ref_years if y >= cutoff),
        'refs_latest': max(ref_years) if ref_years else None,
    }


def recency_issues(content: str, now: int | None = None) -> list[str]:
    r = recency(content, now)
    issues = []
    if r['data_latest'] is not None and r['data_latest'] < r['cutoff']:
        issues.append(f"'숫자로 보는 현황'의 가장 최근 자료가 {r['data_latest']}년입니다. 현황 수치는 "
                      f"{r['cutoff']}년 이후 자료로 바꾸세요. 같은 조사라면 최신판 값을 쓰고, 옛 값은 "
                      '장기 추이의 시작점으로 꼭 필요할 때만 함께 둡니다.')
    if r['refs_dated'] and not r['refs_recent']:
        issues.append(f"참고 자료에 {r['cutoff']}년 이후 자료가 하나도 없습니다(가장 최근 {r['refs_latest']}년). "
                      '고전·원전은 개념의 출처로만 두고, 현황의 근거는 최근 자료로 보강하세요.')
    return issues


def report(subject: str, content: str) -> dict:
    """단계 기록용 요약."""
    return {
        'figure_repetition': figure_repetition(content),
        'orphan_refs': orphan_refs(content),
        'title_overclaim': title_overclaim(subject, content),
        'hedge_ratio': round(hedge_ratio(content), 2),
        'source_count': source_count(content),
        'recency': recency(content),
    }


# 고칠 지적으로 거는 반복 기준. 3회는 '현황에서 제시 → 시사점·맺음말에서 한 번씩 짚기'라는 정상 흐름도
# 걸려(운영 59편 중 22편) 기록용 지표로만 남기고, 4회 이상(13편)만 고치게 한다.
PRECHECK_REPEAT = 4


def precheck_issues(content: str) -> list[str]:
    """초안 자동 점검에 넣을 '고칠 지적' (반복 수치·없는 표 언급)."""
    issues = []
    rep = figure_repetition(content, threshold=PRECHECK_REPEAT)
    if rep:
        shown = ', '.join(f'{v}({n}회)' for v, n in rep[:3])
        issues.append(f'같은 수치를 문장에서 {PRECHECK_REPEAT}번 이상 되풀이했습니다: {shown}. '
                      '수치는 본문에서 한 번만 제시하고, 이후에는 해석·비교로 이어 가세요.')
    orphans = orphan_refs(content)
    if orphans:
        issues.append(f'원고에 없는 표·그림을 가리킵니다: {", ".join(orphans[:3])}. '
                      '도판은 차트 담당이 따로 넣으니, 본문은 표·그림 없이도 읽히게 쓰세요.')
    return issues + recency_issues(content)
