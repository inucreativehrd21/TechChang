
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'common'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='common/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_with_email_verification, name='signup'),
    path('theme/', views.save_theme, name='save_theme'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('password/change/', auth_views.PasswordChangeView.as_view(template_name='common/password_change.html', success_url='/common/password/change/done/'), name='password_change'),
    path('password/change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='common/password_change_done.html'), name='password_change_done'),
    path('account/delete/', views.account_delete, name='account_delete'),
    path('send-verification-email/', views.send_verification_email, name='send_verification_email'),
    path('verify-email-code/', views.verify_email_code, name='verify_email_code'),
    path('signup/verification/', views.signup_with_email_verification, name='signup_with_verification'),
]