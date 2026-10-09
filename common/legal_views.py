"""이용약관·개인정보 처리방침 공개 페이지와 소셜 로그인 회원의 약관 동의 화면."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from . import legal


def legal_page(request, kind, version=None):
    """/terms/, /privacy/ (최신 공고본) · /terms/<버전>/ (지난 버전 열람)."""
    if kind not in legal.VERSIONS:
        raise Http404
    key = version or legal.latest(kind)
    doc = legal.info(kind, key)
    if doc is None:
        raise Http404
    today = timezone.localdate()
    current = legal.info(kind, legal.in_force(kind, today))
    versions = [legal.info(kind, k) for k, _a, _e in legal.VERSIONS[kind]]
    return render(request, 'common/legal_page.html', {
        'kind': kind, 'title': legal.TITLES[kind], 'doc': doc,
        'pending': doc['effective'] > today,          # 공고 중(아직 시행 전)
        'current': current, 'is_archive': bool(version) and key != legal.latest(kind),
        'versions': versions,
    })


def _safe_next(request):
    nxt = request.POST.get('next') or request.GET.get('next') or '/'
    return nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) else '/'


@login_required(login_url='common:login')
def consent(request):
    """약관 동의 기록이 없는 회원(카카오 소셜 로그인 가입자)이 서비스를 쓰기 전에 거치는 화면."""
    from .models import Profile

    profile, _ = Profile.objects.get_or_create(user=request.user)
    if profile.terms_agreed_at:
        return redirect(_safe_next(request))
    error = ''
    if request.method == 'POST':
        if all(request.POST.get(k) for k in ('agree_terms', 'agree_privacy', 'agree_age')):
            profile.terms_agreed_at = timezone.now()
            profile.terms_version = legal.consent_version()
            profile.save(update_fields=['terms_agreed_at', 'terms_version'])
            return redirect(_safe_next(request))
        error = '필수 항목에 모두 동의해야 서비스를 이용할 수 있습니다.'
    return render(request, 'common/consent.html', {
        'terms_template': legal.info('terms', legal.latest('terms'))['template'],
        'error': error, 'next': _safe_next(request),
    })
