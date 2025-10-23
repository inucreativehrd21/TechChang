from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/wordchain/(?P<game_id>\w+)/$', consumers.WordChainConsumer.as_asgi()),
]
