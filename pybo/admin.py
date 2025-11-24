
from django.contrib import admin

from .models import Question, Answer, Comment, Category, WordChainGame, WordChainEntry
from .models import WordChainChatMessage, TicTacToeGame, NumberBaseballGame, NumberBaseballAttempt, GuestBook, Game2048

class QuestionAdmin(admin.ModelAdmin):
    search_fields = ['subject']

class AnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'author', 'create_date')

class CommentAdmin(admin.ModelAdmin):
    list_display = ('content', 'author', 'create_date')

class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')


class WordChainGameAdmin(admin.ModelAdmin):
    list_display = ('title', 'creator', 'status', 'create_date', 'get_word_count')
    list_filter = ('status', 'create_date')
    search_fields = ('title', 'creator__username')
    readonly_fields = ('create_date',)
    
    def get_word_count(self, obj):
        return obj.wordchainentry_set.count()
    get_word_count.short_description = '단어 수'


class WordChainEntryAdmin(admin.ModelAdmin):
    list_display = ('word', 'game', 'author', 'create_date', 'is_valid')
    list_filter = ('is_valid', 'create_date', 'game__status')
    search_fields = ('word', 'author__username', 'game__title')
    readonly_fields = ('create_date',)


class WordChainChatMessageAdmin(admin.ModelAdmin):
    list_display = ('game', 'author', 'create_date', 'short_message')
    list_filter = ('create_date', 'game')
    search_fields = ('author__username', 'message')
    readonly_fields = ('create_date',)

    def short_message(self, obj):
        return (obj.message[:60] + '...') if len(obj.message) > 60 else obj.message
    short_message.short_description = '메시지'




class TicTacToeGameAdmin(admin.ModelAdmin):
    list_display = ('title', 'player_x', 'player_o', 'status', 'winner', 'create_date')
    list_filter = ('status', 'create_date')
    search_fields = ('title', 'player_x__username', 'player_o__username')
    readonly_fields = ('create_date', 'start_date', 'end_date')


class NumberBaseballGameAdmin(admin.ModelAdmin):
    list_display = ('player', 'attempts', 'max_attempts', 'status', 'create_date')
    list_filter = ('status', 'create_date')
    search_fields = ('player__username',)
    readonly_fields = ('create_date', 'end_date', 'secret_number')


class NumberBaseballAttemptAdmin(admin.ModelAdmin):
    list_display = ('game', 'guess_number', 'strikes', 'balls', 'create_date')
    list_filter = ('create_date',)
    readonly_fields = ('create_date',)


class GuestBookAdmin(admin.ModelAdmin):
    list_display = ('author', 'short_content', 'color', 'create_date')
    list_filter = ('create_date', 'color')
    search_fields = ('author__username', 'content')
    readonly_fields = ('create_date', 'modify_date')
    
    def short_content(self, obj):
        return (obj.content[:50] + '...') if len(obj.content) > 50 else obj.content
    short_content.short_description = '내용'




class Game2048Admin(admin.ModelAdmin):
    list_display = ('player', 'score', 'best_score', 'status', 'moves', 'create_date')
    list_filter = ('status', 'create_date')
    search_fields = ('player__username',)
    readonly_fields = ('create_date', 'end_date')

# Register your models here.
admin.site.register(Question, QuestionAdmin)
admin.site.register(Answer, AnswerAdmin)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(WordChainGame, WordChainGameAdmin)
admin.site.register(WordChainEntry, WordChainEntryAdmin)
admin.site.register(WordChainChatMessage, WordChainChatMessageAdmin)
admin.site.register(TicTacToeGame, TicTacToeGameAdmin)
admin.site.register(NumberBaseballGame, NumberBaseballGameAdmin)
admin.site.register(NumberBaseballAttempt, NumberBaseballAttemptAdmin)
admin.site.register(GuestBook, GuestBookAdmin)
admin.site.register(Game2048, Game2048Admin)