"""
GitHub REST 얇은 래퍼 — 정비반이 이슈·PR 을 만든다.

토큰(.env GITHUB_DISPATCH_TOKEN)이 없으면 모든 함수가 (None, 사유) 를 돌려주고 조용히 넘어간다.
필요한 권한: Contents(read/write), Issues(read/write), Pull requests(read/write).
"""
from __future__ import annotations

import requests
from django.conf import settings

API = 'https://api.github.com'
TIMEOUT = 20


def _conf():
    token = getattr(settings, 'GITHUB_DISPATCH_TOKEN', '')
    repo = getattr(settings, 'GITHUB_REPO', '')
    if not token or not repo:
        return None, None
    return token, repo


def available() -> bool:
    return all(_conf())


def _headers(token):
    return {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'}


def _post(path: str, payload: dict):
    token, repo = _conf()
    if not token:
        return None, 'GITHUB_DISPATCH_TOKEN/GITHUB_REPO 미설정'
    try:
        r = requests.post(f'{API}/repos/{repo}{path}', headers=_headers(token), json=payload, timeout=TIMEOUT)
        if r.status_code in (200, 201):
            return r.json(), ''
        return None, f'{r.status_code} {r.text[:200]}'
    except Exception as ex:  # noqa: BLE001
        return None, str(ex)[:200]


def create_issue(title: str, body: str, labels: list | None = None):
    """이슈 생성 → (issue dict, '') 또는 (None, 사유)"""
    return _post('/issues', {'title': title[:250], 'body': body, 'labels': labels or []})


def comment_issue(number: int, body: str):
    return _post(f'/issues/{number}/comments', {'body': body})


def close_issue(number: int, reason: str = 'completed'):
    token, repo = _conf()
    if not token:
        return None, '토큰 미설정'
    try:
        r = requests.patch(f'{API}/repos/{repo}/issues/{number}', headers=_headers(token),
                           json={'state': 'closed', 'state_reason': reason}, timeout=TIMEOUT)
        return (r.json(), '') if r.status_code == 200 else (None, f'{r.status_code} {r.text[:150]}')
    except Exception as ex:  # noqa: BLE001
        return None, str(ex)[:200]


def create_pr(branch: str, title: str, body: str, base: str = 'main'):
    return _post('/pulls', {'title': title[:250], 'head': branch, 'base': base, 'body': body})


def repo_url() -> str:
    _, repo = _conf()
    return f'https://github.com/{repo}' if repo else ''
