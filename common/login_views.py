"""일반 로그인 뒤 기존 회원에게 계정 연결을 안내해요. 실패가 쌓이면 잠시 막아요(common.login_throttle)."""
from django.contrib.auth.views import LoginView
from django.forms.utils import ErrorDict

from . import login_throttle
from .social_views import PROVIDERS, enabled

LINK_PROMPT_SESSION_KEY = 'account_link_prompt_user'


class AccountLoginView(LoginView):
    template_name = 'common/login.html'

    def _username(self):
        return str(self.request.POST.get('username', ''))[:254]

    def post(self, request, *args, **kwargs):
        if login_throttle.blocked(request, self._username()):
            # 잠금 중에는 비밀번호를 확인하지 않아요 — 맞는 비밀번호여도 결과로 대입 성공을 알 수 없게
            # 바인딩한 폼은 errors 를 읽는 순간 clean() 이 authenticate() 를 불러요 — 비어 있는 폼에 안내만 달아요
            form = self.get_form_class()(request, initial={'username': self._username()})
            form._errors, form.cleaned_data = ErrorDict(), {}
            form.add_error(None, login_throttle.MESSAGE)
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        login_throttle.failed(self.request, self._username())
        return super().form_invalid(form)

    def form_valid(self, form):
        login_throttle.succeeded(self.request, self._username())
        response = super().form_valid(form)
        user = form.get_user()
        self.request.session.pop(LINK_PROMPT_SESSION_KEY, None)
        if not user.social_identities.exists() and any(enabled(p) for p in PROVIDERS):
            self.request.session[LINK_PROMPT_SESSION_KEY] = user.pk
        return response
