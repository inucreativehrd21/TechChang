"""
pybo views package
"""

from . import base_views
from . import question_views
from . import answer_views
from . import comment_views
from . import profile_views
# 실시간 게임 비활성화 (WebSocket 필요)
# from . import wordchain_views
# from . import tictactoe_views
from . import baseball_views
from . import guestbook_views
from . import game2048_views

__all__ = [
    'base_views',
    'question_views',
    'answer_views',
    'comment_views',
    'profile_views',
    # 'wordchain_views',  # 비활성화
    # 'tictactoe_views',  # 비활성화
    'baseball_views',
    'guestbook_views',
    'game2048_views',
]
