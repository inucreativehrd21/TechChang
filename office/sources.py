"""근거 문서 묶음 — 원고가 기대는 공식 문서를 코드가 직접 받아 문단으로 나누고, 원고와 관련 있는 문단만 고른다.

왜(2026-11-01 원장 대조 재생): 원장이 '주장마다 원문 한 문장'이라 v2 초안의 주장 57개 중 54개가 원장에 근거가
없었다. 튜토리얼의 근거는 대부분 공식 문서 몇 쪽이다. 주장별 인용 대신 문서 묶음(검색 코퍼스)과 대조한다(ALCE).
문서를 받는 일은 모델이 아니라 코드가 한다 — 구독 토큰이 들지 않는다.

외부 주소를 여는 기능이라 경계를 둔다: https 만, 공인 IP 로 풀리는 호스트만, 10초·2MB 제한, 문서 형식(text/html·
text/plain)만. 예약 도메인(example·test·invalid·localhost)은 열지 않는다.
"""
from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
import urllib.request
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

UA = 'Mozilla/5.0 (compatible; TechChangLab/1.0; +https://techchang.com)'
TIMEOUT = 10
MAX_BYTES = 2_000_000
MAX_DOCS = 6
PARA_CHARS = 1200
BUDGET = 30_000          # 원장 대조 프롬프트에 넣을 문서 문단 총량(글자)
_URL = re.compile(r'https?://[^\s)\]>"\'`]+')
_RESERVED = ('example.com', 'example.org', 'example.net', '.example', '.test', '.invalid', '.localhost', 'localhost')
_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_.]*[A-Za-z0-9_]|\d+(?:\.\d+)?')
_STOP = set('the and for with that this are from not but you your can will has have was were its into than then '
            'also when what which use used using such only more most each other may must should does http https www '
            'com org html docs doc en ref topics'.split())


def enabled() -> bool:
    from .switches import get
    return bool(get('source_fetch'))


def normalize(url: str) -> str:
    parts = urlsplit(url.strip().rstrip('.,;'))
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ''))


def allowed(url: str) -> bool:
    """https·공인 주소·예약 도메인 아님."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not host or parts.username or any(host == r.lstrip('.') or host.endswith(r)
                                                                   for r in _RESERVED):
        return False
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return False
    return bool(addrs) and all(ipaddress.ip_address(a).is_global for a in addrs)


def urls_in(*texts: str) -> list[str]:
    return list(dict.fromkeys(normalize(u) for t in texts for u in _URL.findall(t or '')))


class _Text(HTMLParser):
    """본문 텍스트를 블록 단위로 — 스크립트·탐색 메뉴는 버리고, 소제목을 문단 위치 표시로 남긴다."""
    BLOCK = {'p', 'li', 'pre', 'h1', 'h2', 'h3', 'h4', 'dt', 'dd', 'td', 'th', 'blockquote', 'div', 'section'}
    SKIP = {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg', 'form', 'button'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.buf, self.skip, self.heading, self.title = [], [], 0, '', ''
        self._in_title = self._in_heading = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.flush()
        if tag == 'title':
            self._in_title = True
        if tag in ('h1', 'h2', 'h3'):
            self._in_heading = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            if tag in ('h1', 'h2', 'h3'):
                self.heading = re.sub(r'\s+', ' ', ''.join(self.buf)).strip()[:80].rstrip('¶ ')
                self._in_heading = False
            self.flush()
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.buf.append(data)

    def flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self.buf)).strip()
        self.buf = []
        if len(text) >= 40 and not self._in_heading:
            self.blocks.append((self.heading, text))


def paragraphs(body: str, content_type: str = 'text/html') -> tuple[str, list[dict]]:
    """(문서 제목, [{'section', 'text'}]) — 짧은 블록은 같은 소제목 안에서 이어 붙여 PARA_CHARS 안팎으로."""
    if 'html' in content_type:
        parser = _Text()
        parser.feed(body)
        parser.flush()
        title, blocks = html.unescape(parser.title).strip(), parser.blocks
    else:
        title = ''
        blocks = [('', re.sub(r'[ \t]+', ' ', b).strip()) for b in re.split(r'\n\s*\n', body) if len(b.strip()) >= 40]
    out, cur = [], None
    for section, text in blocks:
        if cur and cur['section'] == section and len(cur['text']) + len(text) < PARA_CHARS:
            cur['text'] += ' ' + text
            continue
        cur = {'section': section, 'text': text[:PARA_CHARS * 2]}
        out.append(cur)
    return title, out


def _download(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,text/plain'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get('Content-Type', '')
        if not ctype.startswith(('text/html', 'text/plain')):
            raise ValueError(f'문서 형식이 아니에요: {ctype}')
        raw = r.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('문서가 너무 커요')
        charset = r.headers.get_content_charset() or 'utf-8'
        return raw.decode(charset, errors='replace'), ctype


def _version(url: str) -> str:
    m = re.search(r'/(?:en|ko)/(\d+(?:\.\d+)*)/', url) or re.search(r'stable/(\d+(?:\.\d+)*)', url)
    return m.group(1) if m else ''


class Corpus:
    """실행 하나의 문서 묶음. 같은 URL 은 한 번만 받는다(실패도 기억해 다시 열지 않는다)."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.failed: dict[str, str] = {}

    def add(self, urls) -> None:
        if not enabled():
            return
        for url in urls:
            if len(self.docs) >= MAX_DOCS:
                break
            url = normalize(url)
            if url in self.docs or url in self.failed:
                continue
            if not allowed(url):
                self.failed[url] = '허용하지 않는 주소'
                continue
            try:
                body, ctype = _download(url)
                title, paras = paragraphs(body, ctype)
            except Exception as exc:  # noqa: BLE001 — 문서를 못 받으면 그 문서만 빼고 웹 확인 경로가 대신한다
                self.failed[url] = f'{type(exc).__name__}: {exc}'[:120]
                logger.info('근거 문서를 받지 못했어요: %s (%s)', url, self.failed[url])
                continue
            if paras:
                self.docs[url] = {'title': title or url, 'version': _version(url), 'paras': paras}

    def select(self, content: str, budget: int = BUDGET) -> list[dict]:
        """원고와 겹치는 식별자·용어가 많은 문단부터 budget 글자까지. 드문 말일수록 무게가 크다."""
        raw = [w for w in _TOKEN.findall(re.sub(r'https?://\S+', ' ', content or '')) if len(w) >= 3]
        words = {w.lower() for w in raw if w.lower() not in _STOP}
        # 코드 식별자(select_related·assertNumQueries·QuerySet.filter) — 하나도 빠짐없이 근거 문단을 확보할 대상
        idents = {w.lower() for w in raw if '_' in w or '.' in w.strip('.') or re.search(r'[a-z][A-Z]', w)}
        if not words or not self.docs:
            return []
        rows = []
        for url, doc in self.docs.items():
            for i, p in enumerate(doc['paras'], 1):
                toks = {w.lower() for w in _TOKEN.findall(p['text'])}
                rows.append((url, doc, i, p, toks & words))
        df = {}
        for *_x, hit in rows:
            for w in hit:
                df[w] = df.get(w, 0) + 1
        scored = sorted(((sum(1 / df[w] for w in hit), url, doc, i, p, hit) for url, doc, i, p, hit in rows if hit),
                        key=lambda r: -r[0])
        # 1) 원고의 코드 식별자마다 그 이름이 든 최고점 문단 하나씩(드문 것부터) 2) 남은 예산을 점수순으로.
        # 2026-11-01 v3 파일럿: 테스트 도구 문서를 받아 놓고도 점수순 선택에서 밀려 assertNumQueries·
        # CaptureQueriesContext 주장이 '원장 밖'이 됐다.
        order = []
        for w in sorted(idents & set(df), key=lambda w: df[w]):
            first = next((r for r in scored if w in r[5]), None)
            if first is not None and first not in order:
                order.append(first)
        order += [r for r in scored if r not in order]
        out, used = [], 0
        for _score, url, doc, i, p, _hit in order:
            if used + len(p['text']) > budget:
                continue
            used += len(p['text'])
            out.append({'url': url, 'title': doc['title'], 'version': doc['version'], 'n': i,
                        'section': p['section'], 'text': p['text']})
        return sorted(out, key=lambda r: (r['url'], r['n']))


def entries(selected: list[dict]) -> list[dict]:
    """원장 항목 모양(office.grounded) — 문단 전체가 발췌, 위치는 소제목·문단 번호, 대상은 문서, 기간은 판·확인일."""
    today = date.today().isoformat()
    return [{'fact': f"{s['title']} — {s['section'] or '본문'}", 'quote': s['text'], 'url': s['url'],
             'context': '', 'kind': 'document',
             'source_locator': f"{s['section'] or '본문'} · 문단 {s['n']}",
             'population': s['title'][:80],
             'period': (f"{s['version']}판 문서, {today} 확인" if s['version'] else f'{today} 확인본'),
             'source_date': 'unknown'} for s in selected]
