
from django.urls import path

from .views import base_views, question_views, answer_views, comment_views, profile_views, wordchain_views, tictactoe_views, baseball_views, guestbook_views, game2048_views

app_name = 'pybo'

urlpatterns = [
    # base_views.py
    path('',
         base_views.index, name='index'),
    path('<int:question_id>/',
         base_views.detail, name='detail'),
    path('recent-answers/', base_views.recent_answers, name='recent_answers'),
    path('recent-comments/', base_views.recent_comments, name='recent_comments'),
    path('games/', base_views.games_index, name='games_index'),

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

    # wordchain_views.py - 끝말잇기 게임
    path('wordchain/', wordchain_views.wordchain_list, name='wordchain_list'),
    path('wordchain/create/', wordchain_views.wordchain_create, name='wordchain_create'),
    path('wordchain/<int:game_id>/', wordchain_views.wordchain_detail, name='wordchain_detail'),
    path('wordchain/<int:game_id>/join/', wordchain_views.wordchain_join, name='wordchain_join'),
    path('wordchain/<int:game_id>/start/', wordchain_views.wordchain_start, name='wordchain_start'),
    path('wordchain/<int:game_id>/add_word/', wordchain_views.wordchain_add_word, name='wordchain_add_word'),
     path('wordchain/<int:game_id>/add_chat/', wordchain_views.wordchain_add_chat, name='wordchain_add_chat'),
     path('wordchain/<int:game_id>/chats/', wordchain_views.wordchain_get_chats, name='wordchain_get_chats'),
    path('wordchain/<int:game_id>/state/', wordchain_views.wordchain_get_state, name='wordchain_get_state'),
    path('wordchain/<int:game_id>/finish/', wordchain_views.wordchain_finish, name='wordchain_finish'),
    # tictactoe_views.py - 틱택토 게임
    path('tictactoe/', tictactoe_views.tictactoe_list, name='tictactoe_list'),
    path('tictactoe/create/', tictactoe_views.tictactoe_create, name='tictactoe_create'),
    path('tictactoe/<int:game_id>/', tictactoe_views.tictactoe_detail, name='tictactoe_detail'),
    path('tictactoe/<int:game_id>/join/', tictactoe_views.tictactoe_join, name='tictactoe_join'),
    path('tictactoe/<int:game_id>/move/', tictactoe_views.tictactoe_move, name='tictactoe_move'),
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
    path('2048/<int:game_id>/', game2048_views.game2048_play, name='game2048_play'),
    path('2048/<int:game_id>/move/', game2048_views.game2048_move, name='game2048_move'),
    path('2048/<int:game_id>/restart/', game2048_views.game2048_restart, name='game2048_restart'),
]
