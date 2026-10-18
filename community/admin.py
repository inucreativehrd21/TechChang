
from django.contrib import admin

from .models import Question, QuestionImage, Answer, Comment, Category, WordChainGame, WordChainEntry
from .models import WordChainChatMessage, TicTacToeGame, NumberBaseballGame, NumberBaseballAttempt, GuestBook, Game2048

class QuestionImageInline(admin.TabularInline):
    model = QuestionImage
    extra = 0

class QuestionAdmin(admin.ModelAdmin):
    search_fields = ['subject']
    inlines = [QuestionImageInline]

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

# 야구선수 키우기 (규칙 community/rookie.py)
from django import forms  # noqa: E402

from . import rookie_world as W  # noqa: E402
from .models import RookieLog, RookiePlayer  # noqa: E402


class RookieLogInline(admin.TabularInline):
    model = RookieLog
    extra = 0
    fields = ('day', 'kind', 'source', 'tp', 'text')
    readonly_fields = fields
    ordering = ('-created_at',)
    max_num = 0


class RookiePlayerForm(forms.ModelForm):
    """리그는 목록에서 고르게 하고(자유 입력 오타가 밤 정산을 멈추지 않게), 프로면 소속이 그 나라 구단 코드인지 본다."""
    league = forms.ChoiceField(label='리그', choices=[(c, f"{v['name']} ({c})") for c, v in W.LEAGUES.items()])

    class Meta:
        model = RookiePlayer
        fields = '__all__'

    def clean(self):
        data = super().clean()
        league, club = data.get('league'), data.get('club', '')
        if league and W.is_pro(league):
            codes = [c for c, _n, _col in W.SYSTEM_TEAMS[W.system_of(league)]]
            if club not in codes:
                self.add_error('club', f"{W.league(league)['name']} 구단 코드가 아닙니다: {', '.join(codes)}")
        return data


@admin.register(RookiePlayer)
class RookiePlayerAdmin(admin.ModelAdmin):
    form = RookiePlayerForm
    list_display = ('name', 'user', 'league', 'club', 'role', 'age', 'ovr', 'tp', 'last_active', 'retired_at')
    list_filter = ('league', 'role', 'team')
    search_fields = ('name', 'user__username')
    readonly_fields = ('pending', 'career', 'traits', 'traits_seen')
    inlines = [RookieLogInline]
