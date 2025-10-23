
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'common'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='common/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup, name='signup'),
    path('theme/', views.save_theme, name='save_theme'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('password/change/', auth_views.PasswordChangeView.as_view(template_name='common/password_change.html', success_url='/common/password/change/done/'), name='password_change'),
    path('password/change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='common/password_change_done.html'), name='password_change_done'),
    path('account/delete/', views.account_delete, name='account_delete'),

    # 카카오 로그인
    path('kakao/login/', views.kakao_login, name='kakao_login'),
    path('kakao/callback/', views.kakao_callback, name='kakao_callback'),
    path('kakao/logout/', views.kakao_logout, name='kakao_logout'),

    # 관리자 기능
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/users/', views.admin_user_list, name='admin_user_list'),
    path('admin/user/<int:user_id>/', views.admin_user_detail, name='admin_user_detail'),
    path('admin/user/<int:user_id>/change-rank/', views.admin_change_rank, name='admin_change_rank'),
    path('admin/user/<int:user_id>/toggle-active/', views.admin_toggle_active, name='admin_toggle_active'),
]