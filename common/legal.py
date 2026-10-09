"""이용약관·개인정보 처리방침 버전 관리.

문서 본문은 templates/common/legal/<kind>_<YYYYMMDD>.html 한 곳에만 둔다(가입 화면·동의 화면·공개 페이지가
같은 파일을 include). 개정할 때는 새 날짜 파일을 만들고 아래 VERSIONS 맨 앞에 추가한다 — 지난 버전은
「개인정보 보호법」 작성지침에 따라 계속 열람할 수 있게 남겨 둔다.

시행일이 미래인 버전은 공고 중(아직 적용 전)으로 보고, 공개 페이지에 "○○부터 적용, 그 전까지는 직전 버전"을 함께 안내한다.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

# (버전 키 = 시행일 YYYYMMDD, 공고일, 시행일) — 최신이 앞
VERSIONS = {
    'terms': [
        ('20261016', date(2026, 10, 9), date(2026, 10, 16)),
        ('20260607', date(2026, 6, 7), date(2026, 6, 7)),
    ],
    'privacy': [
        ('20261009', date(2026, 10, 9), date(2026, 10, 9)),
        ('20260607', date(2026, 6, 7), date(2026, 6, 7)),
    ],
}
TITLES = {'terms': '이용약관', 'privacy': '개인정보 처리방침'}


def latest(kind: str) -> str:
    """가장 최근에 공고한 버전 — 지금 가입·동의하는 사람이 동의하는 문서."""
    return VERSIONS[kind][0][0]


def in_force(kind: str, today: date | None = None) -> str:
    """오늘 시행 중인 버전."""
    today = today or timezone.localdate()
    for key, _announced, effective in VERSIONS[kind]:
        if effective <= today:
            return key
    return VERSIONS[kind][-1][0]


def info(kind: str, key: str) -> dict | None:
    for k, announced, effective in VERSIONS[kind]:
        if k == key:
            return {'key': k, 'announced': announced, 'effective': effective,
                    'template': f'common/legal/{kind}_{k}.html'}
    return None


def consent_version() -> str:
    """Profile.terms_version 에 남기는 값 — 동의한 약관·처리방침 버전."""
    return f"terms:{latest('terms')}/privacy:{latest('privacy')}"
