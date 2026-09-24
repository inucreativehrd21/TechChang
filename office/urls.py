from django.urls import path

from . import views

app_name = 'office'

urlpatterns = [
    path('', views.office_home, name='home'),
    path('state.json', views.office_state, name='state'),
    path('admin/', views.office_admin, name='admin'),
    path('admin/decision/<int:decision_id>/choose/', views.decision_choose, name='decision_choose'),
    path('admin/draft/<int:draft_id>/publish/', views.draft_publish, name='draft_publish'),
    path('admin/activity.json', views.admin_activity, name='admin_activity'),
    path('admin/draft/<int:draft_id>/revise/', views.draft_revise, name='draft_revise'),
    path('admin/draft/<int:draft_id>/reject/', views.draft_reject, name='draft_reject'),
    path('admin/task/new/', views.task_create, name='task_create'),
    path('admin/task/<int:task_id>/', views.task_action, name='task_action'),
    path('admin/run/', views.run_job, name='run_job'),
]
