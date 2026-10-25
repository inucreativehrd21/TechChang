from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path('calendar/', include('schedule.urls')),
    path('login/', lambda request: HttpResponse('login'), name='login'),
]
