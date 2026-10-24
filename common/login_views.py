"""일반 로그인 뒤 기존 회원에게 계정 연결을 안내해요."""
from django.contrib.auth.views import LoginView

from .social_views import PROVIDERS, enabled

LINK_PROMPT_SESSION_KEY = 'account_link_prompt_user'


class AccountLoginView(LoginView):
    template_name = 'common/login.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        self.request.session.pop(LINK_PROMPT_SESSION_KEY, None)
        if not user.social_identities.exists() and any(enabled(p) for p in PROVIDERS):
            self.request.session[LINK_PROMPT_SESSION_KEY] = user.pk
        return response
