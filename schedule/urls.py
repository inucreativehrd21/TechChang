from django.urls import path

from . import views

app_name = 'schedule'

urlpatterns = [
    path('', views.month_view, name='month'),
    path('<int:year>/<int:month>/', views.month_view, name='month_at'),
    path('day/<str:day>/', views.day_view, name='day'),
    path('new/', views.event_create, name='event_create'),
    path('event/<int:pk>/', views.event_detail, name='event_detail'),
    path('event/<int:pk>/edit/', views.event_edit, name='event_edit'),
    path('event/<int:pk>/delete/', views.event_delete, name='event_delete'),
    path('feed/community.ics', views.community_ics, name='community_ics'),
]
