"""검색 노출 점검 — 칼럼 색인 현황(URL 검사 API)과 제목 다시 쓰기 후보(검색 성과).

주간 방문자 리포트(send_visitor_report)와 seo_retitle 명령이 쓴다. 모델 호출은 없다.
- 색인 현황: 연구팀 칼럼 주소마다 GSC URL 검사 → '색인됨' 비율과 미색인 사유. 일 2,000건 한도라
  칼럼 수(수십 편) 정도는 주 1회 전수 검사해도 여유가 있다.
- 제목 후보: 노출은 쌓였는데(1페이지 근처에 뜨는데) 클릭이 안 나는 칼럼 = 제목·설명이 약한 글.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

SITE = 'https://techchang.com'
# 제목 다시 쓰기 후보 문턱 — 사이트 규모가 커지면 올린다
RETITLE_MIN_IMPR = 30
RETITLE_MAX_CTR = 0.02
RETITLE_MAX_POS = 15
RETITLE_MIN_AGE_DAYS = 21       # 발행 직후 순위가 요동치는 기간은 판단하지 않는다


def _service():
    from common.management.commands.send_visitor_report import Command as VR
    from googleapiclient.discovery import build
    creds, reason = VR()._gsc_credentials()
    if creds is None:
        raise RuntimeError(f'GSC 자격증명 없음: {reason}')
    return build('searchconsole', 'v1', credentials=creds, cache_discovery=False)


def _columns():
    from community.models import Question
    return list(Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False, is_locked=False)
                .only('id', 'subject', 'create_date').order_by('-create_date'))


def index_coverage(limit: int = 120) -> dict:
    """{'available', 'total', 'indexed', 'not_indexed': [{id, subject, state}]}"""
    site_url = getattr(settings, 'GSC_SITE_URL', '')
    if not site_url:
        return {'available': False, 'reason': '미설정'}
    try:
        svc = _service()
    except Exception as ex:  # noqa: BLE001
        return {'available': False, 'reason': str(ex)[:120]}
    cols = _columns()[:limit]
    indexed, missing, errors = 0, [], 0
    for q in cols:
        url = f'{SITE}/{q.id}/'
        try:
            res = svc.urlInspection().index().inspect(body={'inspectionUrl': url, 'siteUrl': site_url}).execute()
            status = res.get('inspectionResult', {}).get('indexStatusResult', {})
        except Exception:  # noqa: BLE001 — 한 건 실패로 전체 점검을 멈추지 않는다
            errors += 1
            logger.warning('URL 검사 실패: %s', url, exc_info=True)
            continue
        if status.get('verdict') == 'PASS':
            indexed += 1
        else:
            missing.append({'id': q.id, 'subject': q.subject, 'state': status.get('coverageState', '알 수 없음')})
    return {'available': True, 'total': len(cols) - errors, 'indexed': indexed, 'not_indexed': missing,
            'errors': errors}


def page_queries(days: int = 28) -> dict:
    """{question_id: {'impr', 'clicks', 'position', 'queries': [상위 검색어]}} — 칼럼 주소만."""
    site_url = getattr(settings, 'GSC_SITE_URL', '')
    svc = _service()
    end = timezone.localdate()
    rows = svc.searchanalytics().query(siteUrl=site_url, body={
        'startDate': (end - timedelta(days=days)).isoformat(), 'endDate': end.isoformat(),
        'dimensions': ['page', 'query'], 'rowLimit': 5000}).execute().get('rows', [])
    return aggregate_page_rows(rows)


def aggregate_page_rows(rows: list) -> dict:
    """(page, query) 행 → 글 번호별 합계. www·?sort= 같은 변형 주소는 같은 글로 묶는다(순수 함수)."""
    out: dict = {}
    for r in rows:
        page, query = r['keys'][0], r['keys'][1]
        parts = [p for p in urllib.parse.urlsplit(page).path.split('/') if p]
        if len(parts) != 1 or not parts[0].isdigit():
            continue
        qid = int(parts[0])
        impr = r.get('impressions', 0)
        g = out.setdefault(qid, {'impr': 0, 'clicks': 0, '_pos': 0.0, '_q': {}})
        g['impr'] += impr
        g['clicks'] += r.get('clicks', 0)
        g['_pos'] += r.get('position', 0) * impr
        g['_q'][query] = g['_q'].get(query, 0) + impr
    for g in out.values():
        g['position'] = round(g.pop('_pos') / g['impr'], 1) if g['impr'] else 0
        g['queries'] = [q for q, _n in sorted(g.pop('_q').items(), key=lambda t: t[1], reverse=True)[:5]]
    return out


def retitle_candidates(stats: dict | None = None) -> list:
    """[{id, subject, impr, clicks, ctr, position, queries}] — 노출 대비 클릭이 약한 칼럼, 노출 많은 순."""
    if stats is None:
        stats = page_queries()
    cutoff = timezone.now() - timedelta(days=RETITLE_MIN_AGE_DAYS)
    out = []
    for q in _columns():
        s = stats.get(q.id)
        if not s or q.create_date > cutoff:
            continue
        ctr = s['clicks'] / s['impr'] if s['impr'] else 0
        if s['impr'] >= RETITLE_MIN_IMPR and ctr < RETITLE_MAX_CTR and s['position'] <= RETITLE_MAX_POS:
            out.append({'id': q.id, 'subject': q.subject, 'impr': int(s['impr']), 'clicks': int(s['clicks']),
                        'ctr': round(ctr * 100, 1), 'position': s['position'], 'queries': s['queries']})
    out.sort(key=lambda c: c['impr'], reverse=True)
    return out
