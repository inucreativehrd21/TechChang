"""IndexNow — 글이 생기거나 바뀌면 검색엔진에 바로 알린다.

api.indexnow.org 한 곳에 보내면 IndexNow 참여 엔진(Bing·네이버·Yandex·Seznam 등)이 공유한다.
구글은 IndexNow 를 받지 않으므로 사이트맵 lastmod 로 처리한다(sitemap-columns.xml 등).

- 키: settings.INDEXNOW_KEY (32자 16진수). 비어 있으면 아무것도 하지 않는다(로컬·테스트 기본값).
- 소유 확인: https://techchang.com/<KEY>.txt 가 키 문자열을 그대로 돌려준다(config/urls.py).
- 요청을 막지 않도록 트랜잭션 커밋 뒤 별도 스레드에서 보내고, 실패는 로그만 남긴다.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

ENDPOINT = 'https://api.indexnow.org/indexnow'
HOST = 'techchang.com'
DEDUP_SECONDS = 600     # 같은 주소를 연달아 고칠 때(재심사·수정 반복) 10분에 한 번만 보낸다


def enabled() -> bool:
    return bool(getattr(settings, 'INDEXNOW_KEY', ''))


def submit(urls: list[str]) -> int | None:
    """주소 목록을 즉시 보낸다(동기). 보낸 HTTP 상태 코드, 꺼져 있거나 보낼 게 없으면 None."""
    key = getattr(settings, 'INDEXNOW_KEY', '')
    urls = [u for u in dict.fromkeys(urls) if u.startswith(f'https://{HOST}/')]
    if not key or not urls:
        return None
    body = json.dumps({'host': HOST, 'key': key, 'keyLocation': f'https://{HOST}/{key}.txt',
                       'urlList': urls[:10000]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method='POST',
                                 headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            logger.info('IndexNow %s: %d개 (%s…)', res.status, len(urls), urls[0])
            return res.status
    except urllib.error.HTTPError as ex:
        logger.warning('IndexNow 거절 %s: %s', ex.code, urls[0])
        return ex.code
    except Exception:  # noqa: BLE001 — 알림 실패가 글 저장을 막으면 안 된다
        logger.warning('IndexNow 전송 실패: %s', urls[0], exc_info=True)
        return None


def notify(url: str) -> None:
    """한 주소를 백그라운드로 알린다(중복 억제). 저장 트랜잭션이 커밋된 뒤에 호출할 것."""
    if not enabled():
        return
    if not cache.add(f'indexnow:{url}', 1, DEDUP_SECONDS):
        return
    # non-daemon — cron 명령(office_publish 등)이 바로 끝나도 전송은 마치고 종료되게
    threading.Thread(target=submit, args=([url],), name='indexnow').start()
