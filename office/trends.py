"""편집회의 트렌드 정찰 — 지금 뜨는 소재와 실제 검색 수요를 회의 '전에' 쥐여 준다(2026-10-16 운영자 요청).

요청: "지금 트렌드에 맞고 검색(인기)량이 많은 주제를 겨냥해 유입을 공격적으로 늘리자."
그전 회의는 사이트 지표·GSC 검색 기회(이미 우리 사이트가 걸리는 검색어)·지난 칼럼만 보고 주제를 냈고,
검색 수요는 후보가 다 정해진 뒤 후보끼리 상대 비교만 했다(데이터랩은 요청 안 최고=100) — '사람들이
실제로 얼마나 찾는가'가 판단에 들어가지 않았다.

흐름: 원천 수집(코드) → 팀장 은혜가 웹 검색까지 더해 분야별 후보 3개씩 정리(scout) → 후보 검색어 수요를
같은 잣대로 측정(measure) → 수요 높은 순 [이번 주 트렌드·검색 수요] 브리핑 → 회의 → 결론 선택지도
수요 순으로 다시 세우고 1위에 '추천'(rank_options).

원천(키 없이 코드가 직접 받는다. 실패하면 빈 값 — 회의를 막지 않는다):
- GeekNews(news.hada.io) 최신 글: 국내 개발·AI 커뮤니티에서 지금 도는 소재
- Google 트렌드 한국 일간 급상승 검색어(어림 검색량): 대부분 시사지만 기술·일 이야기가 섞이면 잡는다
검색 수요 잣대:
- 네이버 검색광고 키워드 도구 월간 검색수(PC+모바일, 절대값) — 서버 .env 에 NAVER_SEARCHAD_API_KEY,
  NAVER_SEARCHAD_SECRET_KEY, NAVER_SEARCHAD_CUSTOMER_ID 가 있을 때(searchad.naver.com → 도구 → API 사용 관리)
- 없으면 네이버 데이터랩 검색어트렌드를 기준어(파이썬)=100 지수로 환산 — 요청마다 같은 기준어를 끼우므로
  안건끼리·주차끼리 비교가 된다(절대량은 아니다)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

GEEKNEWS = 'https://news.hada.io/rss/news'
GTRENDS = 'https://trends.google.com/trending/rss?geo=KR'
SEARCHAD = 'https://api.searchad.naver.com'
DATALAB = 'https://naverapihub.apigw.ntruss.com/search-trend/v1/search'
ANCHOR = '파이썬'
UA = 'Mozilla/5.0 (compatible; TechChangLab/1.0; +https://techchang.com)'
FIELDS = (('hrd', 'HRD'), ('data', '데이터분석'), ('coding', '프로그래밍'))
UNIT_LABEL = {'volume': '네이버 월간 검색수(PC+모바일)', 'index': f'검색 수요 지수({ANCHOR}=100, 최근 90일)'}


def _env(name: str) -> str:
    return os.environ.get(name, '').strip()


def _ck(*parts) -> str:
    return 'tr:' + hashlib.md5('|'.join(map(str, parts)).encode('utf-8')).hexdigest()


def _fetch(url: str, timeout: int = 15) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=timeout).read()


# ───────────────────────────── 원천
def geeknews(limit: int = 20) -> list:
    """GeekNews 최신 글 [{title, url}]."""
    try:
        root = ET.fromstring(_fetch(GEEKNEWS))
    except Exception:  # noqa: BLE001
        logger.warning('GeekNews 수집 실패', exc_info=True)
        return []
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    out = []
    for e in root.findall('a:entry', ns):
        title = (e.findtext('a:title', '', ns) or '').strip()
        link = e.find('a:link', ns)
        if title:
            out.append({'title': title, 'url': link.get('href', '') if link is not None else ''})
        if len(out) >= limit:
            break
    return out


def google_trends(limit: int = 20) -> list:
    """구글 트렌드 한국 급상승 검색어 [{title, traffic, news}]."""
    try:
        root = ET.fromstring(_fetch(GTRENDS))
    except Exception:  # noqa: BLE001
        logger.warning('구글 트렌드 수집 실패', exc_info=True)
        return []
    ns = {'ht': 'https://trends.google.com/trending/rss'}
    out = []
    for item in root.iter('item'):
        title = (item.findtext('title') or '').strip()
        if not title:
            continue
        news = item.find('ht:news_item', ns)
        out.append({'title': title, 'traffic': (item.findtext('ht:approx_traffic', '', ns) or '').strip(),
                    'news': (news.findtext('ht:news_item_title', '', ns) or '').strip() if news is not None else ''})
        if len(out) >= limit:
            break
    return out


# ───────────────────────────── 검색 수요
def _plain(k: str) -> str:
    return ''.join(str(k).split())


def _count(v) -> int:
    """검색광고 도구는 적은 값을 '< 10' 문자열로 준다."""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v or '').strip()
    return 5 if s.startswith('<') else int(s or 0) if s.isdigit() else 0


def searchad_ready() -> bool:
    return all(_env(n) for n in ('NAVER_SEARCHAD_API_KEY', 'NAVER_SEARCHAD_SECRET_KEY', 'NAVER_SEARCHAD_CUSTOMER_ID'))


def searchad_volumes(keywords: list) -> dict:
    """{검색어: 월간 검색수(PC+모바일)}. 키가 없거나 실패하면 {}. 도구는 띄어쓰기 없는 검색어만 받는다."""
    if not searchad_ready():
        return {}
    key, secret, customer = (_env('NAVER_SEARCHAD_API_KEY'), _env('NAVER_SEARCHAD_SECRET_KEY'),
                             _env('NAVER_SEARCHAD_CUSTOMER_ID'))
    by_plain = {}
    for k in keywords:
        if _plain(k):
            by_plain.setdefault(_plain(k).lower(), []).append(k)
    plains = list(by_plain)
    out = {}
    for i in range(0, len(plains), 5):
        batch = plains[i:i + 5]
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(hmac.new(secret.encode(), f'{ts}.GET./keywordstool'.encode(),
                                        hashlib.sha256).digest()).decode()
        url = SEARCHAD + '/keywordstool?' + urllib.parse.urlencode({'hintKeywords': ','.join(batch), 'showDetail': 1})
        req = urllib.request.Request(url, headers={'X-Timestamp': ts, 'X-API-KEY': key, 'X-Customer': customer,
                                                   'X-Signature': sig})
        try:
            rows = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8')).get('keywordList') or []
        except Exception:  # noqa: BLE001
            logger.warning('네이버 검색광고 키워드 도구 조회 실패', exc_info=True)
            continue
        for r in rows:
            p = _plain(r.get('relKeyword', '')).lower()
            if p in batch:
                for original in by_plain[p]:
                    out[original] = _count(r.get('monthlyPcQcCnt')) + _count(r.get('monthlyMobileQcCnt'))
    return out


def datalab_index(keywords: list) -> dict:
    """{검색어: 수요 지수} — 최근 90일 주간 검색 비율 평균을 기준어(파이썬)=100 으로 환산.

    데이터랩은 한 요청 안 최고값=100 인 상대값이라, 요청마다 기준어를 끼워 그 비율로 바꾼다.
    검색이 거의 없는 주는 응답에서 빠지므로 빠진 주는 0으로 본다(기준어의 주 수로 나눈다)."""
    cid, sec = _env('NAVER_API_HUB_CLIENT_ID'), _env('NAVER_API_HUB_CLIENT_SECRET')
    uniq = list(dict.fromkeys(k.strip()[:30] for k in keywords if str(k).strip()))
    if not (cid and sec and uniq):
        return {}
    end = timezone.localdate() - timedelta(days=1)
    start = end - timedelta(days=90)
    out = {}
    for i in range(0, len(uniq), 4):
        batch = [k for k in uniq[i:i + 4] if k != ANCHOR]
        groups = [{'groupName': ANCHOR, 'keywords': [ANCHOR]}] + [{'groupName': k, 'keywords': [k]} for k in batch]
        body = {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'timeUnit': 'week', 'keywordGroups': groups}
        req = urllib.request.Request(DATALAB, data=json.dumps(body).encode('utf-8'), method='POST', headers={
            'X-NCP-APIGW-API-KEY-ID': cid, 'X-NCP-APIGW-API-KEY': sec, 'Content-Type': 'application/json'})
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            logger.warning('네이버 데이터랩 수요 지수 조회 실패', exc_info=True)
            continue
        series = {g.get('title', ''): [float(d.get('ratio') or 0) for d in g.get('data') or []]
                  for g in res.get('results') or []}
        weeks = len(series.get(ANCHOR) or [])
        base = sum(series.get(ANCHOR) or []) / weeks if weeks else 0
        if not base:
            continue
        for k in batch:
            out[k] = round(sum(series.get(k) or []) / weeks / base * 100, 2)
        if ANCHOR in uniq[i:i + 4]:
            out[ANCHOR] = 100.0
    return out


def measure(keywords: list) -> tuple[dict, str]:
    """후보 검색어 수요 → ({검색어: 값}, 'volume'|'index'). 같은 검색어는 6시간 캐시."""
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    unit = 'volume' if searchad_ready() else 'index'
    found, todo = {}, []
    for k in dict.fromkeys(keywords):
        hit = cache.get(_ck(unit, k))
        if hit is None:
            todo.append(k)
        else:
            found[k] = hit
    if todo:
        fresh = searchad_volumes(todo) if unit == 'volume' else datalab_index(todo)
        for k, v in fresh.items():
            cache.set(_ck(unit, k), v, 60 * 60 * 6)
        found.update(fresh)
    return found, unit


def demand_label(value, unit: str) -> str:
    if value is None:
        return ''
    if unit == 'volume':
        return f'월 {int(value):,}회 검색'
    return f'수요 지수 {value:g}'


def best_keyword(keywords: list, values: dict) -> tuple[str, float | None]:
    scored = [(values[k], k) for k in keywords if values.get(k) is not None]
    if not scored:
        return '', None
    v, k = max(scored)
    return k, v


# ───────────────────────────── 정찰(회의 전)
SCOUT = (
    '{who} — 오늘 저녁 편집회의 전에 "이번 주 트렌드"를 정리해 주세요. 이번 분기 목표는 유입입니다: '
    '지금 사람들이 실제로 많이 찾는 주제를 우리 세 분야(HRD·데이터분석·프로그래밍) 칼럼으로 먼저 잡는 것.\n\n'
    '[국내 개발 커뮤니티 최신 글 — GeekNews]\n{geek}\n\n'
    '[구글 한국 급상승 검색어(어림 검색량) — 대부분 시사라 우리 분야와 이어지는 것만 쓰세요]\n{gt}\n\n'
    '[우리가 이미 쓴 칼럼 제목(최근)]\n{titles}\n\n'
    'WebSearch 로 최근 2주 국내외 뉴스·커뮤니티에서 세 분야와 이어지는 화제를 더 찾아보세요 '
    '(예: 새 AI 도구·모델 출시와 사용법, 채용·HR 제도 변화, 정부 직업훈련·국민내일배움카드 정책, 자격증 시험 일정, '
    '개발 도구 업데이트, 직장인 업무 자동화).\n'
    '분야별로 후보 3개씩 고르세요. 기준: (1) 지금 화제다 (2) 일반 독자가 검색창에 실제로 칠 한국어 검색어가 있다 '
    '(3) 우리가 이미 쓴 소재와 겹치지 않는다(겹치면 새 각도가 분명할 때만).\n'
    '검색어는 후보마다 2~3개 — 사람들이 실제로 치는 표기·띄어쓰기 그대로(영어 제품명은 한국 사람이 치는 표기도 함께, '
    '예: "클로드 코드", "제미나이"). 문장형 말고 검색창에 넣는 짧은 말로.\n'
    'JSON 으로만 답하세요:\n'
    '{{"hrd": [{{"topic": "주제 한 줄", "why": "왜 지금 뜨는지 한 문장", "url": "근거 URL", '
    '"keywords": ["검색어", "검색어"]}}, ...3개], "data": [...3개], "coding": [...3개]}}'
)


def scout(recent_titles: list, *, ask_json, who: str = '', tools: tuple = ()) -> dict:
    """원천 수집 + 팀장 정리 + 수요 측정 → {'unit', 'fields': {topic: [후보...]}, 'sources': {...}}.

    후보마다 demand(최고 검색어의 값)·demand_kw·demand_note 를 달고 분야 안에서 수요 높은 순으로 세운다.
    어느 단계가 실패해도 회의는 계속된다 — 실패하면 빈 fields 와 note 를 돌려준다."""
    geek, gt = geeknews(), google_trends()
    prompt = SCOUT.format(
        who=who or '은혜(분석관·팀장)',
        geek='\n'.join(f"- {g['title']}" for g in geek) or '(수집 실패 — 웹 검색으로 대신하세요)',
        gt='\n'.join(f"- {g['title']} ({g['traffic']}){' — ' + g['news'] if g['news'] else ''}" for g in gt)
        or '(수집 실패)',
        titles='\n'.join(f'- {t}' for t in recent_titles[:40]) or '(없음)')
    result = {'unit': '', 'fields': {}, 'sources': {'geeknews': len(geek), 'google_trends': len(gt)}, 'note': ''}
    try:
        raw = ask_json(prompt, tools=tools)
    except Exception as ex:  # noqa: BLE001 — 정찰 실패는 회의를 막지 않는다
        logger.warning('트렌드 정찰 실패', exc_info=True)
        result['note'] = f'정찰 실패: {type(ex).__name__}'
        return result

    fields = {}
    for key, _label in FIELDS:
        items = []
        for it in (raw.get(key) or [])[:4]:
            if not isinstance(it, dict) or not str(it.get('topic', '')).strip():
                continue
            kws = [str(k).strip()[:30] for k in (it.get('keywords') or []) if str(k).strip()][:3]
            items.append({'topic': str(it['topic']).strip()[:120], 'why': str(it.get('why', '')).strip()[:240],
                          'url': str(it.get('url', '')).strip()[:300], 'keywords': kws})
        fields[key] = items
    values, unit = measure([k for items in fields.values() for it in items for k in it['keywords']])
    for items in fields.values():
        for it in items:
            it['demand_kw'], it['demand'] = best_keyword(it['keywords'], values)
            it['demand_note'] = demand_label(it['demand'], unit)
        items.sort(key=lambda it: -1 if it['demand'] is None else it['demand'], reverse=True)
    result.update(unit=unit if values else '', fields=fields)
    if not values:
        result['note'] = '검색 수요 측정 실패(키 없음 또는 호출 실패) — 후보는 수요 없이 정리'
    return result


def brief_lines(tr: dict) -> list:
    """회의 브리핑에 넣을 [이번 주 트렌드·검색 수요] 블록."""
    fields = (tr or {}).get('fields') or {}
    if not any(fields.values()):
        return []
    unit = tr.get('unit')
    head = ('[이번 주 트렌드·검색 수요] 팀장이 회의 전에 정리한 지금 뜨는 후보 — 분야마다 검색 수요 높은 순'
            + (f' (기준: {UNIT_LABEL[unit]})' if unit else ' (검색 수요 측정 실패 — 순서는 의미 없음)') + ':')
    lines = [head]
    for key, label in FIELDS:
        items = fields.get(key) or []
        if not items:
            continue
        lines.append(f'  {label}:')
        for it in items:
            kw = f" | 검색어 '{it['demand_kw']}' {it['demand_note']}" if it.get('demand_note') else (
                f" | 검색어 {', '.join(it['keywords'])}" if it['keywords'] else '')
            lines.append(f"    - {it['topic']} — {it['why']}{kw}")
    return lines


# ───────────────────────────── 결론 선택지 줄 세우기
def rank_options(decisions: list) -> dict:
    """칼럼 안건 선택지를 검색 수요 높은 순으로 다시 세우고(key 도 a,b,c 로 다시 매김) 1위에 recommended.

    수요는 선택지 keywords 중 최고값. 측정이 안 된 선택지는 뒤로. 측정값이 하나도 없으면 순서는 그대로 둔다.
    반환: {'unit', 'measured': 측정된 선택지 수}."""
    cols = [d for d in decisions if isinstance(d, dict) and d.get('kind') in ('column', 'series')]
    kws = [k for d in cols for o in d.get('options') or [] if isinstance(o, dict)
           for k in (o.get('keywords') or []) if isinstance(k, str)]
    values, unit = measure(kws) if kws else ({}, '')
    measured = 0
    for d in cols:
        opts = [o for o in d.get('options') or [] if isinstance(o, dict)]
        for o in opts:
            kw, v = best_keyword([k for k in (o.get('keywords') or []) if isinstance(k, str)], values)
            o['demand'], o['demand_kw'] = v, kw
            o['demand_note'] = f"네이버 검색어 '{kw}' {demand_label(v, unit)}" if v is not None else ''
            measured += v is not None
        if d.get('kind') != 'column' or not any(o['demand'] is not None for o in opts):
            continue
        opts.sort(key=lambda o: -1 if o['demand'] is None else o['demand'], reverse=True)
        for i, o in enumerate(opts):
            o['key'] = 'abc'[i] if i < 3 else o.get('key', '')
            o['recommended'] = i == 0 and (o['demand'] or 0) > 0
        d['options'] = opts
    return {'unit': unit, 'measured': measured}
