"""명시적인 소셜 계정 연결. 이메일 일치만으로 계정을 합치지 않는다."""
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import requests
from google.auth.exceptions import GoogleAuthError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Profile, SocialIdentity

PROVIDERS = {'kakao': '카카오', 'google': 'Google'}


def config(provider):
    if provider not in PROVIDERS:
        raise Http404
    prefix = 'KAKAO_REST_API_KEY' if provider == 'kakao' else 'GOOGLE_CLIENT_ID'
    secret = 'KAKAO_CLIENT_SECRET' if provider == 'kakao' else 'GOOGLE_CLIENT_SECRET'
    return (getattr(settings, prefix, os.environ.get(prefix, '')),
            getattr(settings, secret, os.environ.get(secret, '')))


def enabled(provider):
    client, secret = config(provider)
    return bool(client and (secret or provider == 'kakao'))


def _next(request):
    value = request.GET.get('next', '/')
    return value if url_has_allowed_host_and_scheme(value, {request.get_host()}, require_https=request.is_secure()) else '/'


def start(request, provider):
    if request.user.is_authenticated:
        return redirect('common:connections')
    return _start(request, provider, 'login')


@login_required(login_url='common:login')
@require_POST
def connect(request, provider):
    return _start(request, provider, 'connect')


def _start(request, provider, intent):
    if not enabled(provider):
        messages.error(request, f'{PROVIDERS[provider]} 로그인 설정을 준비 중이에요. 아이디와 비밀번호로 로그인해 주세요.')
        return redirect('common:connections' if intent == 'connect' else 'common:login')
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    callback = request.build_absolute_uri(reverse(f'common:{provider}_callback'))
    request.session[f'social_{provider}'] = {
        'state': state, 'nonce': nonce, 'created': timezone.now().timestamp(),
        'intent': intent, 'user': request.user.pk if request.user.is_authenticated else None,
        'next': _next(request), 'callback': callback,
    }
    params = {'client_id': config(provider)[0], 'redirect_uri': callback,
              'response_type': 'code', 'state': state}
    if provider == 'google':
        params.update(scope='openid email profile', nonce=nonce, prompt='select_account')
        url = 'https://accounts.google.com/o/oauth2/v2/auth'
    else:
        # 연결 시 현재 브라우저의 카카오 계정을 무심코 연결하지 않게 계정 확인을 거친다.
        if intent == 'connect':
            params['prompt'] = 'login'
        url = 'https://kauth.kakao.com/oauth/authorize'
    return redirect(url + '?' + urlencode(params))


def _identity(provider, code, flow):
    client, secret = config(provider)
    payload = {'grant_type': 'authorization_code', 'client_id': client,
               'redirect_uri': flow['callback'], 'code': code}
    if secret:
        payload['client_secret'] = secret
    endpoint = 'https://oauth2.googleapis.com/token' if provider == 'google' else 'https://kauth.kakao.com/oauth/token'
    response = requests.post(endpoint, data=payload, timeout=15)
    response.raise_for_status()
    token = response.json()
    if provider == 'google':
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import verify_oauth2_token
        class BoundedRequest(Request):
            def __call__(self, *args, **kwargs):
                kwargs['timeout'] = 15
                return super().__call__(*args, **kwargs)
        info = verify_oauth2_token(token['id_token'], BoundedRequest(), client)
        if not secrets.compare_digest(str(info.get('nonce', '')), flow['nonce']):
            raise ValueError('nonce')
        subject = info['sub']
        if not isinstance(subject, str) or not subject:
            raise ValueError('subject')
        email = info.get('email', '') if info.get('email_verified') is True else ''
        return subject, email, info.get('name') or '', bool(email)
    response = requests.get('https://kapi.kakao.com/v2/user/me',
                            headers={'Authorization': 'Bearer ' + token['access_token']}, timeout=15)
    response.raise_for_status()
    info = response.json()
    subject = info['id']
    if not isinstance(subject, int) or isinstance(subject, bool) or subject <= 0:
        raise ValueError('subject')
    account = info.get('kakao_account') or {}
    verified = account.get('is_email_valid') is True and account.get('is_email_verified') is True
    email = account.get('email', '') if verified else ''
    return str(subject), email, (account.get('profile') or {}).get('nickname') or '', verified


def callback(request, provider):
    if provider not in PROVIDERS:
        raise Http404
    flow = request.session.pop(f'social_{provider}', None)
    destination = 'common:connections' if flow and flow.get('intent') == 'connect' else 'common:login'
    try:
        if not flow or not secrets.compare_digest(str(request.GET.get('state', '')), flow['state']):
            raise ValueError('state')
        age = timezone.now().timestamp() - flow['created']
        if age < 0 or age > timedelta(minutes=5).total_seconds():
            raise ValueError('expired')
        if request.GET.get('error') or not request.GET.get('code'):
            raise ValueError('cancelled')
        if flow['intent'] == 'connect' and (not request.user.is_authenticated or request.user.pk != flow['user']):
            raise ValueError('changed session')
        if flow['intent'] == 'login' and request.user.is_authenticated:
            raise ValueError('already logged in')
        subject, email, nickname, verified = _identity(provider, request.GET['code'], flow)
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise ValueError('subject')
        if not isinstance(email, str) or not isinstance(nickname, str):
            raise ValueError('profile fields')
        # 두 공급자 모두 같은 User/Profile 필드 규칙을 사용해요.
        email = User.objects.normalize_email(email.strip()) if email and verified else ''
        if email:
            validate_email(email)
            if len(email) > User._meta.get_field('email').max_length:
                raise ValueError('email length')
        nickname = nickname.strip()[:Profile._meta.get_field('nickname').max_length]
        verified = bool(email)
        with transaction.atomic():
            identity = SocialIdentity.objects.select_related('user').filter(provider=provider, subject=subject).first()
            if flow['intent'] == 'connect':
                user = User.objects.select_for_update().get(pk=flow['user'], is_active=True)
                if identity and identity.user_id != user.pk:
                    messages.error(request, '다른 회원에게 연결된 계정이에요. 계정 병합은 자동으로 하지 않아요.')
                    return redirect(destination)
                if SocialIdentity.objects.filter(user=user, provider=provider).exclude(subject=subject).exists():
                    messages.error(request, '이미 다른 계정이 연결돼 있어요. 기존 연결을 먼저 해제해 주세요.')
                    return redirect(destination)
                linked, _ = SocialIdentity.objects.get_or_create(provider=provider, subject=subject, defaults={'user': user})
                if linked.user_id != user.pk:
                    raise ValueError('identity changed')
                # 공급자가 같은 이메일의 소유권을 확인한 경우에만 사이트 이메일도 인증해요.
                if email and user.email.casefold() == email.casefold():
                    Profile.objects.filter(user=user).update(is_email_verified=True)
                request.session.pop('account_link_prompt_user', None)
                messages.success(request, f'{PROVIDERS[provider]} 계정을 연결했어요. 기존 기록으로 로그인할 수 있어요.')
                return redirect(destination)
            if identity:
                user = identity.user
                if not user.is_active:
                    raise ValueError('inactive')
            else:
                # 이메일은 소셜 계정의 키가 아니다. 동일 이메일이면 기존 계정으로 로그인해 연결한다.
                if email and User.objects.filter(email__iexact=email).exists():
                    messages.info(request, '같은 이메일의 기존 계정이 있어요. 기존 계정으로 로그인한 뒤 프로필의 계정 연결에서 연결해 주세요.')
                    return redirect(destination)
                user = User.objects.create_user(username=f'{provider}_{secrets.token_hex(12)}', email=email, password=None)
                Profile.objects.update_or_create(user=user, defaults={'nickname': nickname[:30] or None,
                                                                      'is_email_verified': verified})
                SocialIdentity.objects.create(user=user, provider=provider, subject=subject)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'{PROVIDERS[provider]} 계정으로 로그인했어요.')
        return redirect(flow['next'])
    except (requests.RequestException, GoogleAuthError, ValidationError, ValueError, KeyError, TypeError, IntegrityError, User.DoesNotExist):
        # 공급자의 원 응답·토큰·개인정보는 화면이나 로그에 기록하지 않는다.
        messages.error(request, '인증을 완료하지 못했어요. 계정을 확인한 뒤 다시 시작해 주세요.')
        return redirect(destination)


@login_required(login_url='common:login')
def connections(request):
    request.session.pop('account_link_prompt_user', None)
    profile, _ = Profile.objects.get_or_create(user=request.user)
    identities = set(request.user.social_identities.values_list('provider', flat=True))
    return render(request, 'common/connections.html', {'profile': profile, 'providers': [
        {'key': p, 'label': name, 'connected': p in identities, 'enabled': enabled(p)}
        for p, name in PROVIDERS.items()]})


@login_required(login_url='common:login')
@require_POST
def disconnect(request, provider):
    if provider not in PROVIDERS:
        raise Http404
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        identities = SocialIdentity.objects.filter(user=user)
        if not user.has_usable_password() and not identities.exclude(provider=provider).exists():
            messages.error(request, '마지막 로그인 수단은 해제할 수 없어요. 먼저 다른 계정을 연결해 주세요.')
        elif user.has_usable_password() and not user.check_password(request.POST.get('password', '')):
            messages.error(request, '연결을 해제하려면 현재 사이트 비밀번호를 입력해 주세요.')
        else:
            identities.filter(provider=provider).delete()
            messages.success(request, f'{PROVIDERS[provider]} 연결을 해제했어요.')
    return redirect('common:connections')
