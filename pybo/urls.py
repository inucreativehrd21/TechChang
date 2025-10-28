
from django.urls import path

# 실시간 게임 비활성화 (나중을 위해 파일은 유지)
# from .views import wordchain_views, tictactoe_views
from .views import base_views, question_views, answer_views, comment_views, profile_views, baseball_views, guestbook_views, game2048_views, minesweeper_views

app_name = 'pybo'

urlpatterns = [
    # base_views.py
    path('',
         base_views.index, name='index'),
    path('recent-answers/', base_views.recent_answers, name='recent_answers'),
    path('recent-comments/', base_views.recent_comments, name='recent_comments'),
    # path('games/', base_views.games_index, name='games_index'),  # 게임센터 메인 비활성화

    # question_views.py
    path('question/create/',
         question_views.question_create, name='question_create'),
    path('question/modify/<int:question_id>/',
         question_views.question_modify, name='question_modify'),
    path('question/delete/<int:question_id>/',
         question_views.question_delete, name='question_delete'),

    # answer_views.py
    path('answer/create/<int:question_id>/',
         answer_views.answer_create, name='answer_create'),
    path('answer/modify/<int:answer_id>/',
         answer_views.answer_modify, name='answer_modify'),
    path('answer/delete/<int:answer_id>/',
         answer_views.answer_delete, name='answer_delete'),

    # vote
    path('question/vote/<int:question_id>/', question_views.question_vote, name='question_vote'),
    path('answer/vote/<int:answer_id>/', answer_views.answer_vote, name='answer_vote'),

    # comment_views.py
    path('comment/create/question/<int:question_id>/', comment_views.comment_create_question, name='comment_create_question'),
    path('comment/modify/question/<int:comment_id>/', comment_views.comment_modify_question, name='comment_modify_question'),
    path('comment/delete/question/<int:comment_id>/', comment_views.comment_delete_question, name='comment_delete_question'),
    path('comment/create/answer/<int:answer_id>/', comment_views.comment_create_answer, name='comment_create_answer'),
    path('comment/modify/answer/<int:comment_id>/', comment_views.comment_modify_answer, name='comment_modify_answer'),
    path('comment/delete/answer/<int:comment_id>/', comment_views.comment_delete_answer, name='comment_delete_answer'), 
    
    # profile_views.py
    path('profile/<int:user_id>/', profile_views.profile, name='profile'),

    # file download
    path('download/<int:question_id>/', base_views.download_file, name='download_file'),

    # ==================== 실시간 게임 비활성화 ====================
    # 끝말잇기 게임과 틱택토 게임은 WebSocket 실시간 통신이 필요하여 비활성화
    # 파일은 유지: pybo/views/wordchain_views.py, pybo/views/tictactoe_views.py
    # 재활성화 방법: 상단 import에서 wordchain_views, tictactoe_views 추가 후
    #               아래 URL 패턴 추가
    # =============================================================

    # baseball_views.py - 숫자야구 게임
    path('baseball/', baseball_views.baseball_start, name='baseball_start'),
    path('baseball/<int:game_id>/', baseball_views.baseball_play, name='baseball_play'),
    path('baseball/<int:game_id>/guess/', baseball_views.baseball_guess, name='baseball_guess'),
    path('baseball/<int:game_id>/giveup/', baseball_views.baseball_giveup, name='baseball_giveup'),
    
    # guestbook_views.py - 방명록
    path('guestbook/', guestbook_views.guestbook_list, name='guestbook_list'),
    path('guestbook/create/', guestbook_views.guestbook_create, name='guestbook_create'),
    path('guestbook/delete/<int:entry_id>/', guestbook_views.guestbook_delete, name='guestbook_delete'),

    # game2048_views.py - 2048 게임
    path('2048/', game2048_views.game2048_start, name='game2048_start'),
    path('2048/leaderboard/', game2048_views.game2048_leaderboard, name='game2048_leaderboard'),
    path('2048/<int:game_id>/', game2048_views.game2048_play, name='game2048_play'),
    path('2048/<int:game_id>/move/', game2048_views.game2048_move, name='game2048_move'),
    path('2048/<int:game_id>/restart/', game2048_views.game2048_restart, name='game2048_restart'),

    # minesweeper_views.py - 지뢰찾기 게임
    path('minesweeper/', minesweeper_views.minesweeper_start, name='minesweeper_start'),
    path('minesweeper/create/', minesweeper_views.minesweeper_create, name='minesweeper_create'),
    path('minesweeper/<int:game_id>/', minesweeper_views.minesweeper_play, name='minesweeper_play'),
    path('minesweeper/<int:game_id>/reveal/', minesweeper_views.minesweeper_reveal, name='minesweeper_reveal'),
    path('minesweeper/<int:game_id>/flag/', minesweeper_views.minesweeper_flag, name='minesweeper_flag'),
    path('minesweeper/<int:game_id>/update-time/', minesweeper_views.minesweeper_update_time, name='minesweeper_update_time'),

    # *** IMPORTANT: 이 패턴은 맨 마지막에 위치해야 합니다! ***
    # <int:question_id>/ 패턴이 숫자로 시작하는 다른 URL들(2048 등)을 가로채지 않도록
    # 모든 구체적인 URL 패턴을 먼저 정의한 후, 마지막에 이 일반적인 패턴을 배치합니다.
    path('<int:question_id>/', base_views.detail, name='detail'),
]
