
from django.contrib import admin

from .models import Question, Answer, Comment, Category

class QuestionAdmin(admin.ModelAdmin):
    search_fields = ['subject']

class AnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'author', 'create_date')

class CommentAdmin(admin.ModelAdmin):
    list_display = ('content', 'author', 'create_date')

class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')

# Register your models here.
admin.site.register(Question, QuestionAdmin)
admin.site.register(Answer, AnswerAdmin)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Category, CategoryAdmin)