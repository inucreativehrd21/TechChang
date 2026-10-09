"""연구원에게 쥐여 주는 공식 데이터 도구 — 모델이 아니라 **코드**가 가져온다.

- KOSIS(국가통계포털) OpenAPI: 재원이 고른 검색어로 공식 통계표를 찾고 최신 값을 받는다.
  코드가 공식 API 로 받은 값이므로 검증관·편집장에게 '확인된 사실'로 넘긴다(KOSIS 화면은 자바스크립트로
  그려져 웹 도구로 열면 확인 불가가 나기 쉽다).
- 네이버 검색어트렌드(NAVER API HUB): 편집회의 후보 주제들의 검색 수요를 같은 기준(최고=100)으로 비교.
- GSC 기회 검색어: 우리 사이트가 노출은 되는데 클릭이 적은 검색어 — 새 글·보강 후보.

키가 없거나 호출이 실패해도 제작을 멈추지 않는다 — 모든 함수는 실패하면 빈 값을 돌려준다.
키: 서버 .env 의 KOSIS_API_KEY, NAVER_API_HUB_CLIENT_ID, NAVER_API_HUB_CLIENT_SECRET.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

KOSIS_SEARCH = 'https://kosis.kr/openapi/statisticsSearch.do'
KOSIS_DATA = 'https://kosis.kr/openapi/Param/statisticsParameterData.do'
NAVER_TREND = 'https://naverapihub.apigw.ntruss.com/search-trend/v1/search'
TOTAL_WORDS = ('전체', '계', '합계', '소계', '전국')
_last_call = [0.0]


def _ck(*parts) -> str:
    """캐시 키 — 한글 검색어가 그대로 들어가면 memcached 호환 경고가 난다."""
    return 'ds:' + hashlib.md5('|'.join(map(str, parts)).encode('utf-8')).hexdigest()


def _key(name: str) -> str:
    return os.environ.get(name, '').strip()


def _get_json(url: str, params: dict, timeout: int = 25):
    # KOSIS 는 분당 호출 수를 제한한다 — 연속 호출 사이에 간격을 둔다
    wait = 0.6 - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    raw = urllib.request.urlopen(url + '?' + urllib.parse.urlencode(params), timeout=timeout).read()
    return json.loads(raw.decode('utf-8'))


# ───────────────────────────── KOSIS
def kosis_search(term: str, limit: int = 3) -> list:
    """통계표 검색 → [{org, org_id, tbl_id, title, start, end, url}] (최근 자료가 있는 표 우선)."""
    key = _key('KOSIS_API_KEY')
    if not key or not term.strip():
        return []
    ck = _ck('kosis-search', term, limit)
    hit = cache.get(ck)
    if hit is not None:
        return hit
    try:
        rows = _get_json(KOSIS_SEARCH, {'method': 'getList', 'apiKey': key, 'searchNm': term.strip(),
                                        'format': 'json', 'jsonVD': 'Y', 'resultCount': 10})
    except Exception:  # noqa: BLE001
        logger.warning('KOSIS 검색 실패: %s', term, exc_info=True)
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not r.get('TBL_ID'):
            continue
        out.append({'org': r.get('ORG_NM', ''), 'org_id': r.get('ORG_ID', ''), 'tbl_id': r['TBL_ID'],
                    'title': r.get('TBL_NM', ''), 'start': r.get('STRT_PRD_DE', ''), 'end': r.get('END_PRD_DE', ''),
                    'url': f"https://kosis.kr/statHtml/statHtml.do?orgId={r.get('ORG_ID', '')}&tblId={r['TBL_ID']}"})
    out.sort(key=lambda t: str(t['end']), reverse=True)
    out = out[:limit]
    cache.set(ck, out, 60 * 60 * 6)
    return out


def kosis_latest(org_id: str, tbl_id: str, max_rows: int = 10) -> dict:
    """통계표 최신 시점 값 → {period, rows: [{label, value, unit}]} (전체·합계 행 우선)."""
    key = _key('KOSIS_API_KEY')
    if not key:
        return {}
    ck = _ck('kosis-latest', org_id, tbl_id)
    hit = cache.get(ck)
    if hit is not None:
        return hit
    base = {'method': 'getList', 'apiKey': key, 'orgId': org_id, 'tblId': tbl_id, 'itmId': 'ALL',
            'format': 'json', 'jsonVD': 'Y', 'newEstPrdCnt': '1'}
    data = None
    # 통계표마다 분류 단계 수가 달라 맞는 단계를 찾을 때까지 늘려 본다(objL 누락 오류 = 단계 부족)
    for prd in ('Y', 'H', 'Q', 'M'):
        for levels in range(1, 7):
            p = dict(base, prdSe=prd, **{f'objL{i}': 'ALL' for i in range(1, levels + 1)})
            try:
                res = _get_json(KOSIS_DATA, p)
            except Exception:  # noqa: BLE001
                logger.warning('KOSIS 자료 조회 실패: %s/%s', org_id, tbl_id, exc_info=True)
                return {}
            if isinstance(res, list) and res:
                data = res
                break
            if isinstance(res, dict) and 'objL' not in str(res.get('errMsg', '')):
                break            # 단계 문제가 아닌 오류(주기 불일치 등) → 다음 주기로
        if data:
            break
    if not data:
        return {}

    # 통계표마다 '사례수·비율' 같은 측정값이 항목(ITM)에 있기도, 분류(C2 등)에 있기도 하다.
    # 그래서 칸 이름에 기대지 않는다: 각 행의 라벨 조각(분류들 + 항목)을 모으고,
    #  - 응답자 수(사례수)를 뜻하는 행은 다른 값이 있으면 빼고
    #  - 모든 행에서 똑같은 조각(표 이름을 되풀이하는 항목명 등)은 정보가 없으니 뺀다
    COUNT_WORDS = ('사례수', '응답자수', '응답자 수')

    def pieces(r):
        return [r.get(f'C{i}_NM', '') for i in range(1, 9) if r.get(f'C{i}_NM')] + [r.get('ITM_NM', '')]

    non_count = [r for r in data if not any(p in COUNT_WORDS for p in pieces(r))]
    data = non_count or data
    # '비율 100%'는 응답 기준(분모) 행이라 정보가 없고 오해만 부른다 — 다른 값이 있으면 뺀다
    def is_base(r):
        return r.get('UNIT_NM') == '%' and str(r.get('DT', '')).strip() in ('100', '100.0')
    informative = [r for r in data if not is_base(r)]
    data = informative or data
    constant = set(pieces(data[0]))
    for r in data[1:]:
        constant &= set(pieces(r))

    def label(r):
        meaningful = [p for p in pieces(r) if p and p not in TOTAL_WORDS]
        parts = [p for p in meaningful if p not in constant]
        if parts:
            return ' · '.join(parts)
        # 다 공통이면(예: '전체' 행의 '실시 비율') 무엇의 값인지 알 수 있게 가장 짧은 조각을 남긴다
        return min(meaningful, key=len) if meaningful else '전체'

    totals = [r for r in data if r.get('C1_NM', '') in TOTAL_WORDS]   # 첫 분류가 '전체'인 행 = 총괄값
    picked, seen = [], set()
    for r in (totals or data):
        lab = label(r)
        if lab in seen or r.get('DT') in (None, '', '-'):
            continue
        seen.add(lab)
        picked.append({'label': lab, 'value': r.get('DT'), 'unit': r.get('UNIT_NM', '')})
        if len(picked) >= max_rows:
            break
    out = {'period': data[0].get('PRD_DE', ''), 'rows': picked}
    cache.set(ck, out, 60 * 60 * 6)
    return out


def kosis_lookup(terms: list, max_tables: int = 3) -> list:
    """재원의 검색어들 → 공식 통계표 발췌 [{title, org, period, url, rows}] (같은 표는 한 번만)."""
    found, seen = [], set()
    for term in terms[:4]:
        for t in kosis_search(term, limit=2):
            if t['tbl_id'] in seen:
                continue
            seen.add(t['tbl_id'])
            latest = kosis_latest(t['org_id'], t['tbl_id'])
            if latest.get('rows'):
                found.append({'title': t['title'], 'org': t['org'], 'period': latest['period'],
                              'url': t['url'], 'rows': latest['rows'], 'term': term})
            if len(found) >= max_tables:
                return found
    return found


def kosis_lines(tables: list) -> list:
    """칼럼니스트에게 넘길 문장 — 값·기준 시점·기관·URL."""
    out = []
    for t in tables:
        vals = '; '.join(f"{r['label']} {r['value']}{r['unit']}" for r in t['rows'][:6])
        out.append(f"[KOSIS 공식 통계] {t['title']} ({t['org']}, {t['period']}년 기준): {vals} — 원문 {t['url']}")
    return out


def kosis_facts(tables: list) -> str:
    """검증관·편집장에게 넘길 확인 사실 — 코드가 공식 API 로 직접 받은 값."""
    if not tables:
        return ''
    return '\n'.join(['- 아래 값은 국가통계포털(KOSIS) OpenAPI 로 시스템이 직접 받은 공식 통계입니다. '
                      '본문 수치가 이 값과 같으면 verified 로 판정하세요.'] + [f'  · {line}' for line in kosis_lines(tables)])


# ───────────────────────────── 네이버 검색어트렌드
def naver_trend(groups: list, months: int = 12) -> dict:
    """[{'name': 주제, 'keywords': [...]}] (최대 5개) → {주제: {'recent', 'prev', 'change', 'peak'}}.

    값은 이번 요청 안에서 가장 많이 검색된 구간을 100으로 둔 상대 비율이다 — 같은 요청으로 묶은
    주제끼리만 비교할 수 있다."""
    cid, sec = _key('NAVER_API_HUB_CLIENT_ID'), _key('NAVER_API_HUB_CLIENT_SECRET')
    groups = [g for g in groups if g.get('name') and g.get('keywords')][:5]
    if not (cid and sec and groups):
        return {}
    end = timezone.localdate().replace(day=1) - timedelta(days=1)          # 지난달 말일까지
    start = (end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    body = {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'timeUnit': 'month',
            'keywordGroups': [{'groupName': g['name'][:40], 'keywords': [k[:30] for k in g['keywords'][:20]]}
                              for g in groups]}
    req = urllib.request.Request(NAVER_TREND, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        'X-NCP-APIGW-API-KEY-ID': cid, 'X-NCP-APIGW-API-KEY': sec, 'Content-Type': 'application/json'})
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
    except Exception:  # noqa: BLE001
        logger.warning('네이버 검색어트렌드 조회 실패', exc_info=True)
        return {}
    out = {}
    for g in res.get('results') or []:
        series = [float(d.get('ratio') or 0) for d in g.get('data') or []]
        recent = sum(series[-3:]) / 3 if series else 0.0
        prev = sum(series[-6:-3]) / 3 if len(series) >= 6 else 0.0
        out[g.get('title', '')] = {
            'recent': round(recent, 1), 'prev': round(prev, 1), 'peak': round(max(series), 1) if series else 0,
            'change': round((recent - prev) / prev * 100) if prev else None, 'months': len(series),
        }
    return out


def demand_note(d: dict) -> str:
    if not d:
        return ''
    change = '' if d.get('change') is None else f", 직전 3개월 대비 {d['change']:+d}%"
    return f"네이버 검색 수요 {d['recent']:g}(최근 3개월 평균, 안건 내 최고=100 기준{change})"


# ───────────────────────────── GSC 기회 검색어
def gsc_opportunities(days: int = 28, limit: int = 12) -> list:
    """검색 기회 [{query, impr, clicks, ctr, position, page}] — 노출 많은 순.

    두 종류를 함께 잡는다(2026-10-09, 사이트 규모가 작아 '노출 20회+·CTR 2% 미만'만으로는 1건뿐이었다):
    - 문턱 검색어: 평균 순위 4~60위에 노출이 2회 이상 — 맞는 글을 쓰거나 보강하면 1페이지로 올라올 후보
    - 저CTR 검색어: 노출 20회 이상인데 CTR 2% 미만 — 제목·설명이 약하다는 신호
    page = 그 검색어로 지금 가장 많이 노출되는 우리 페이지 경로(없으면 '').
    """
    from django.conf import settings
    site_url = getattr(settings, 'GSC_SITE_URL', '')
    if not site_url:
        return []
    try:
        from common.management.commands.send_visitor_report import Command as VR
        from googleapiclient.discovery import build
        creds, _reason = VR()._gsc_credentials()
        if creds is None:
            return []
        end = timezone.localdate()
        start = end - timedelta(days=days)
        svc = build('searchconsole', 'v1', credentials=creds, cache_discovery=False)
        rows = svc.searchanalytics().query(siteUrl=site_url, body={
            'startDate': start.isoformat(), 'endDate': end.isoformat(), 'dimensions': ['query', 'page'],
            'rowLimit': 1000}).execute().get('rows', [])
    except Exception:  # noqa: BLE001
        logger.warning('GSC 기회 검색어 수집 실패', exc_info=True)
        return []
    return gsc_gaps_from_rows(rows, limit)


def gsc_gaps_from_rows(rows: list, limit: int = 12) -> list:
    """(query, page) 행 → 검색어별 합계 + 대표 페이지. 순수 함수(테스트용으로 분리)."""
    by_query: dict = {}
    for r in rows:
        query, page = r['keys'][0], r['keys'][1] if len(r['keys']) > 1 else ''
        impr = r.get('impressions', 0)
        g = by_query.setdefault(query, {'query': query, 'impr': 0, 'clicks': 0, '_pos': 0.0, 'page': '', '_best': -1})
        g['impr'] += impr
        g['clicks'] += r.get('clicks', 0)
        g['_pos'] += r.get('position', 0) * impr
        if impr > g['_best']:
            # www·쿼리스트링 변형을 대표 경로로 묶어 보여준다
            path = urllib.parse.urlsplit(page).path if page else ''
            g['page'], g['_best'] = path, impr
    gaps = []
    for g in by_query.values():
        if not g['impr']:
            continue
        pos = g['_pos'] / g['impr']
        ctr = g['clicks'] / g['impr']
        near_miss = 4 <= pos <= 60 and g['impr'] >= 2
        weak_ctr = g['impr'] >= 20 and ctr < 0.02
        if near_miss or weak_ctr:
            gaps.append({'query': g['query'], 'impr': int(g['impr']), 'clicks': int(g['clicks']),
                         'ctr': round(ctr * 100, 1), 'position': round(pos, 1), 'page': g['page']})
    gaps.sort(key=lambda g: (g['impr'], -g['position']), reverse=True)
    return gaps[:limit]
