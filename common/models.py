from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import random
import string

User = get_user_model()


class Profile(models.Model):
	THEME_LIGHT = 'light'
	THEME_DARK = 'dark'
	THEME_HIGHCONTRAST = 'highcontrast'
	THEME_CHOICES = [
		(THEME_LIGHT, 'Light'),
		(THEME_DARK, 'Dark'),
		(THEME_HIGHCONTRAST, 'High Contrast'),
	]

	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
	nickname = models.CharField(max_length=30, blank=True, null=True, help_text='닉네임을 설정하지 않으면 사용자명이 표시됩니다.')
	profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True, help_text='프로필 이미지를 업로드하세요.')
	theme = models.CharField(max_length=20, choices=THEME_CHOICES, default=THEME_LIGHT)
	updated_at = models.DateTimeField(auto_now=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Profile'
		verbose_name_plural = 'Profiles'

	@property
	def display_name(self):
		"""닉네임이 있으면 닉네임을, 없으면 사용자명을 반환"""
		return self.nickname if self.nickname else self.user.username

	def __str__(self):
		return f"Profile({self.user.username})"


class EmailVerification(models.Model):
    """이메일 인증 모델"""

    CODE_LENGTH = 4
    CODE_EXPIRY_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    email = models.EmailField(verbose_name="이메일")
    code = models.CharField(max_length=CODE_LENGTH, verbose_name="인증코드")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="인증일시")
    is_verified = models.BooleanField(default=False, verbose_name="인증완료")
    attempts = models.PositiveIntegerField(default=0, verbose_name="시도횟수")
    
    class Meta:
        verbose_name = "이메일 인증"
        verbose_name_plural = "이메일 인증"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.email} - {self.code}"
    
    @classmethod
    def generate_code(cls):
        """고정 길이의 숫자 코드 생성"""
        return ''.join(random.choices(string.digits, k=cls.CODE_LENGTH))
    
    def is_expired(self):
        """10분 후 만료 체크"""
        return timezone.now() > self.created_at + timedelta(minutes=self.CODE_EXPIRY_MINUTES)
    
    def can_retry(self):
        """재시도 가능 여부 (5회 제한)"""
        return self.attempts < self.MAX_ATTEMPTS

    def remaining_attempts(self):
        return max(0, self.MAX_ATTEMPTS - self.attempts)

    def increment_attempts(self):
        """실패 시도 카운터 증가"""
        self.attempts += 1
        self.save(update_fields=['attempts'])
        return self.remaining_attempts()

    def mark_verified(self):
        self.is_verified = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_verified', 'verified_at'])

    def can_resend(self):
        return timezone.now() >= self.created_at + timedelta(seconds=self.RESEND_COOLDOWN_SECONDS)

# Create your models here.
