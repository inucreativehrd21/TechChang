from django.urls import path

from . import views

app_name = 'office'

urlpatterns = [
    path('', views.office_home, name='home'),
    path('state.json', views.office_state, name='state'),
    path('admin/', views.office_admin, name='admin'),
    path('admin/decision/<int:decision_id>/choose/', views.decision_choose, name='decision_choose'),
    path('admin/draft/<int:draft_id>/publish/', views.draft_publish, name='draft_publish'),
    path('admin/draft/<int:draft_id>/reject/', views.draft_reject, name='draft_reject'),
    path('admin/run/', views.run_job, name='run_job'),
]
