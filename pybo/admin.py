
from django.contrib import admin

from .models import Question, Answer, Comment, Category, WordChainGame, WordChainEntry

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


# Register your models here.
admin.site.register(Question, QuestionAdmin)
admin.site.register(Answer, AnswerAdmin)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(WordChainGame, WordChainGameAdmin)
admin.site.register(WordChainEntry, WordChainEntryAdmin)