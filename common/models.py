from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import random
import string

User = get_user_model()


class KakaoUser(models.Model):
	"""카카오 로그인 사용자"""
	kakao_id = models.BigIntegerField(unique=True, verbose_name="카카오 ID")
	nickname = models.CharField(max_length=100, null=True, blank=True, verbose_name="닉네임")
	email = models.EmailField(null=True, blank=True, verbose_name="이메일")
	profile_image = models.URLField(null=True, blank=True, verbose_name="프로필 이미지")
	thumbnail_image = models.URLField(null=True, blank=True, verbose_name="썸네일 이미지")

	# 토큰 정보
	access_token = models.TextField(verbose_name="액세스 토큰")
	refresh_token = models.TextField(null=True, blank=True, verbose_name="리프레시 토큰")
	token_expires_at = models.DateTimeField(null=True, blank=True, verbose_name="토큰 만료 시각")

	# 메타 정보
	created_at = models.DateTimeField(auto_now_add=True, verbose_name="가입일")
	last_login = models.DateTimeField(null=True, blank=True, verbose_name="최근 로그인")

	class Meta:
		verbose_name = "카카오 사용자"
		verbose_name_plural = "카카오 사용자들"
		db_table = 'kakao_users'

	def __str__(self):
		return f"카카오:{self.nickname or self.kakao_id}"


class Profile(models.Model):
	THEME_LIGHT = 'light'
	THEME_DARK = 'dark'
	THEME_HIGHCONTRAST = 'highcontrast'
	THEME_CHOICES = [
		(THEME_LIGHT, 'Light'),
		(THEME_DARK, 'Dark'),
		(THEME_HIGHCONTRAST, 'High Contrast'),
	]

	# 회원 등급
	RANK_REGULAR = 'regular'
	RANK_MEMBER = 'member'
	RANK_TECH_CHANG = 'tech_chang'
	RANK_CHOICES = [
		(RANK_REGULAR, '일반회원'),
		(RANK_MEMBER, '정회원'),
		(RANK_TECH_CHANG, '테크창'),
	]

	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
	nickname = models.CharField(max_length=30, blank=True, null=True, help_text='닉네임을 설정하지 않으면 사용자명이 표시됩니다.')
	profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True, help_text='프로필 이미지를 업로드하세요.')
	theme = models.CharField(max_length=20, choices=THEME_CHOICES, default=THEME_LIGHT)
	rank = models.CharField(max_length=20, choices=RANK_CHOICES, default=RANK_REGULAR, verbose_name='회원 등급')
	updated_at = models.DateTimeField(auto_now=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Profile'
		verbose_name_plural = 'Profiles'

	@property
	def display_name(self):
		"""닉네임이 있으면 닉네임을, 없으면 사용자명을 반환"""
		return self.nickname if self.nickname else self.user.username

	@property
	def rank_display(self):
		"""회원 등급을 한글로 반환"""
		return dict(self.RANK_CHOICES).get(self.rank, '일반회원')

	@property
	def rank_badge_class(self):
		"""회원 등급에 따른 뱃지 색상 클래스"""
		rank_classes = {
			self.RANK_REGULAR: 'bg-secondary',
			self.RANK_MEMBER: 'bg-primary',
			self.RANK_TECH_CHANG: 'bg-warning text-dark',
		}
		return rank_classes.get(self.rank, 'bg-secondary')

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
