"""칼럼 지도 — 연구팀 칼럼을 논문 검색처럼 찾고 둘러보는 공개 페이지(/map/).

- 누구나: 지도 둘러보기(카테고리 → 소주제 → 칼럼)와 검색(제목·키워드·요약·소주제, 검색어는 주소에 남아 공유된다)
- 회원: PDF 저장(인쇄 레이아웃). 비회원이 인쇄하면 본문 대신 '회원 전용' 안내가 찍힌다
- 관리자: 요약 갱신·연구실 관리 바로가기, '갱신 대기' 표시

요약·키워드·소주제는 office.digest 가 만들고(칼럼 저장 시 자동 갱신), 여기서는 읽기만 한다.
"""
import re
from collections import OrderedDict

from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe

CATS = [
    ('hrd', 'HRD', '교육·인재개발 담당자를 위한 학습 설계, 리더십, 인재관리'),
    ('data', '데이터분석', 'HR·조직 데이터를 다루는 방법론, 인프라, AI'),
    ('coding', '프로그래밍', '개발 도구, 언어, 인프라, AI 코딩의 현재'),
    ('series', '연재', '회차를 이어 가며 직접 만들어 보는 시리즈'),
]
CAT_LABEL = {k: label for k, label, _ in CATS}
PENDING_LABEL = '요약 준비 중'
SORTS = OrderedDict([('rel', '관련도순'), ('new', '최신순'), ('views', '조회순')])
MAX_TERMS = 6


def _entries():
    """지도에 오르는 칼럼마다 표시용 항목 하나."""
    from office import digest as D
    from office.models import ColumnDigest

    digests = {d.question_id: d for d in ColumnDigest.objects.all()}
    out = []
    for q in D.columns().order_by('-create_date'):
        cat = D.category_key(q)
        if cat not in CAT_LABEL:
            continue
        dg = digests.get(q.pk)
        sub = dg.subtopic if dg else (q.series.title if q.series_id else PENDING_LABEL)
        out.append({
            'q': q, 'cat': cat, 'cat_label': CAT_LABEL[cat], 'sub': sub,
            'keywords': list(dg.keywords) if dg else [],
            # 요약이 아직 없으면 글머리 요약으로 대신한다 — 방문자에게 빈칸을 보이지 않는다
            'summary': dg.summary if dg else q.seo_description,
            'has_digest': dg is not None,
            'stale': dg is None or dg.content_hash != D.content_hash(q),
        })
    return out


def _terms(q: str) -> list[str]:
    return [t for t in re.split(r'\s+', q.strip().lower()) if t][:MAX_TERMS]


def _score(e: dict, terms: list[str]) -> int:
    """모든 낱말이 어딘가에 있어야 결과에 든다. 제목 > 키워드 > 소주제 > 요약 순으로 가중."""
    subject, summary = e['q'].subject.lower(), (e['summary'] or '').lower()
    kws, sub = ' '.join(e['keywords']).lower(), e['sub'].lower()
    score = 0
    for t in terms:
        s = 5 * (t in subject) + 3 * (t in kws) + 2 * (t in sub) + 1 * (t in summary) + 1 * (t in e['cat_label'].lower())
        if not s:
            return 0
        score += s
    return score


def highlight(text: str, terms: list[str]):
    """검색어를 <mark> 로 감싼다 — 원문은 이스케이프한 뒤 감싸므로 안전하다."""
    safe = escape(text or '')
    if not terms:
        return safe
    pattern = re.compile('|'.join(re.escape(escape(t)) for t in sorted(terms, key=len, reverse=True)), re.I)
    return mark_safe(pattern.sub(lambda m: f'<mark>{m.group(0)}</mark>', safe))


def column_map(request):
    q = (request.GET.get('q') or '').strip()[:100]
    cat = request.GET.get('cat') or ''
    cat = cat if cat in CAT_LABEL else ''
    sub = (request.GET.get('sub') or '').strip()[:60]
    sort = request.GET.get('sort') or ('rel' if q else 'new')
    sort = sort if sort in SORTS else 'new'
    terms = _terms(q)

    entries = _entries()
    is_admin = request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
    stale = sum(e['stale'] for e in entries) if is_admin else 0

    # 검색어에 맞는 글 → 카테고리·소주제 집계(왼쪽 패싯)는 검색어만 반영한다
    matched = [e for e in entries if not terms or _score(e, terms)]
    facet_cats = [{'key': k, 'label': label, 'count': sum(1 for e in matched if e['cat'] == k)} for k, label, _ in CATS]
    sub_counts = OrderedDict()
    for e in matched:
        if not cat or e['cat'] == cat:
            sub_counts[e['sub']] = sub_counts.get(e['sub'], 0) + 1
    facet_subs = sorted(sub_counts.items(), key=lambda kv: (kv[0] == PENDING_LABEL, -kv[1], kv[0]))

    results = [e for e in matched if (not cat or e['cat'] == cat) and (not sub or e['sub'] == sub)]
    for e in results:
        e['title_html'] = highlight(e['q'].subject, terms)
        e['summary_html'] = highlight(e['summary'], terms)

    searching = bool(terms or sub)
    groups = []
    if searching:
        if sort == 'rel' and terms:
            results.sort(key=lambda e: (-_score(e, terms), -e['q'].create_date.timestamp()))
        elif sort == 'views':
            results.sort(key=lambda e: -e['q'].view_count)
        else:
            results.sort(key=lambda e: -e['q'].create_date.timestamp())
    else:
        # 둘러보기 — 카테고리 → 소주제(많은 순) → 칼럼(최신순, 연재는 회차순)
        for k, label, desc in CATS:
            if cat and k != cat:
                continue
            rows = [e for e in results if e['cat'] == k]
            if not rows:
                continue
            subs = OrderedDict()
            for e in rows:
                subs.setdefault(e['sub'], []).append(e)
            sub_list = [{'name': n, 'items': items} for n, items in subs.items()]
            if k == 'series':
                for s in sub_list:
                    s['items'].sort(key=lambda e: e['q'].episode_number or 0)
            else:
                sub_list.sort(key=lambda s: (s['name'] == PENDING_LABEL, -len(s['items']), s['name']))
            for i, s in enumerate(sub_list):
                s['anchor'] = f'{k}-{i}'
            groups.append({'key': k, 'label': label, 'desc': desc, 'count': len(rows), 'subs': sub_list})

    return render(request, 'community/column_map.html', {
        'q': q, 'cat': cat, 'cat_label': CAT_LABEL.get(cat, ''), 'sub': sub, 'sort': sort, 'sorts': SORTS,
        'searching': searching, 'results': results, 'groups': groups, 'total': len(entries),
        'facet_cats': facet_cats, 'facet_subs': facet_subs, 'is_admin': is_admin, 'stale': stale,
        'shown': len(results), 'total_matched': len(matched),
    })
