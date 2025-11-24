from django.contrib import admin
from .models import Profile, Emoticon, UserEmoticon, DailyCheckIn, PointHistory, EmailVerification, KakaoUser, BlockedIP


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'nickname', 'rank', 'points', 'selected_emoticon', 'created_at']
    list_filter = ['rank', 'created_at']
    search_fields = ['user__username', 'nickname']
    ordering = ['-points']


@admin.register(Emoticon)
class EmoticonAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'is_available', 'created_at', 'image_preview']
    list_filter = ['is_available', 'created_at']
    search_fields = ['name']
    ordering = ['price']

    def image_preview(self, obj):
        if obj.image:
            return f'<img src="{obj.image.url}" width="50" height="50" />'
        return '-'
    image_preview.short_description = '미리보기'
    image_preview.allow_tags = True


@admin.register(UserEmoticon)
class UserEmoticonAdmin(admin.ModelAdmin):
    list_display = ['user', 'emoticon', 'purchased_at']
    list_filter = ['purchased_at']
    search_fields = ['user__username', 'emoticon__name']
    ordering = ['-purchased_at']


@admin.register(DailyCheckIn)
class DailyCheckInAdmin(admin.ModelAdmin):
    list_display = ['user', 'check_in_date', 'points_earned', 'created_at']
    list_filter = ['check_in_date']
    search_fields = ['user__username']
    ordering = ['-check_in_date']
    date_hierarchy = 'check_in_date'


@admin.register(PointHistory)
class PointHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'reason', 'description', 'created_at']
    list_filter = ['reason', 'created_at']
    search_fields = ['user__username', 'description']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ['email', 'code', 'is_verified', 'attempts', 'created_at']
    list_filter = ['is_verified', 'created_at']
    search_fields = ['email']
    ordering = ['-created_at']


@admin.register(KakaoUser)
class KakaoUserAdmin(admin.ModelAdmin):
    list_display = ['kakao_id', 'nickname', 'email', 'last_login', 'created_at']
    list_filter = ['created_at', 'last_login']
    search_fields = ['nickname', 'email', 'kakao_id']
    ordering = ['-created_at']


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ['ip_address', 'reason', 'blocked_by', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['ip_address', 'reason']
    ordering = ['-created_at']
