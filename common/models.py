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
	points = models.IntegerField(default=0, verbose_name='포인트')
	selected_emoticon = models.ForeignKey('Emoticon', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='선택한 이모티콘', related_name='selected_by')
	is_email_verified = models.BooleanField(default=False, verbose_name='이메일 인증 여부', help_text='이메일 인증을 완료한 사용자인지 여부')
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

    CODE_LENGTH = 8  # 보안 강화: 6자리 → 8자리 (1억 조합)
    CODE_EXPIRY_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    email = models.EmailField(verbose_name="이메일")
    code = models.CharField(max_length=10, verbose_name="인증코드")  # max_length 증가
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시", db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="인증일시")
    is_verified = models.BooleanField(default=False, verbose_name="인증완료")
    attempts = models.PositiveIntegerField(default=0, verbose_name="시도횟수")

    class Meta:
        verbose_name = "이메일 인증"
        verbose_name_plural = "이메일 인증"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'created_at']),  # Rate limiting 쿼리 최적화
        ]

    def __str__(self):
        return f"{self.email} - {self.code}"

    @classmethod
    def generate_code(cls):
        """암호학적으로 안전한 8자리 코드 생성"""
        import secrets
        return ''.join(secrets.choice(string.digits) for _ in range(cls.CODE_LENGTH))

    @classmethod
    def can_send_new_code(cls, email):
        """Rate limiting: 1분에 1회만 발송 가능"""
        one_minute_ago = timezone.now() - timedelta(minutes=1)
        recent_count = cls.objects.filter(
            email=email,
            created_at__gte=one_minute_ago
        ).count()
        return recent_count == 0
    
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


class Emoticon(models.Model):
    """이모티콘 모델"""
    name = models.CharField(max_length=50, verbose_name='이모티콘 이름')
    image = models.ImageField(upload_to='emoticons/', verbose_name='이모티콘 이미지')
    price = models.IntegerField(verbose_name='가격 (포인트)')
    is_available = models.BooleanField(default=True, verbose_name='판매 중')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')

    class Meta:
        verbose_name = '이모티콘'
        verbose_name_plural = '이모티콘 목록'
        ordering = ['price', '-created_at']

    def __str__(self):
        return f"{self.name} ({self.price}P)"


class UserEmoticon(models.Model):
    """사용자가 구매한 이모티콘"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_emoticons', verbose_name='사용자')
    emoticon = models.ForeignKey(Emoticon, on_delete=models.CASCADE, verbose_name='이모티콘')
    purchased_at = models.DateTimeField(auto_now_add=True, verbose_name='구매일')

    class Meta:
        verbose_name = '구매한 이모티콘'
        verbose_name_plural = '구매한 이모티콘 목록'
        unique_together = ['user', 'emoticon']
        ordering = ['-purchased_at']

    def __str__(self):
        return f"{self.user.username} - {self.emoticon.name}"


class DailyCheckIn(models.Model):
    """일일 출석 체크"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='check_ins', verbose_name='사용자')
    check_in_date = models.DateField(auto_now_add=True, verbose_name='출석일')
    points_earned = models.IntegerField(default=5, verbose_name='획득 포인트')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')

    class Meta:
        verbose_name = '출석 체크'
        verbose_name_plural = '출석 체크 목록'
        unique_together = ['user', 'check_in_date']
        ordering = ['-check_in_date']

    def __str__(self):
        return f"{self.user.username} - {self.check_in_date}"


class PointHistory(models.Model):
    """포인트 히스토리"""
    REASON_CHECKIN = 'checkin'
    REASON_PURCHASE = 'purchase'
    REASON_ADMIN = 'admin'
    REASON_GAME = 'game'

    REASON_CHOICES = [
        (REASON_CHECKIN, '출석 체크'),
        (REASON_PURCHASE, '이모티콘 구매'),
        (REASON_ADMIN, '관리자 지급'),
        (REASON_GAME, '게임 보상'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='point_history', verbose_name='사용자')
    amount = models.IntegerField(verbose_name='포인트 변동량')  # 양수: 획득, 음수: 사용
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, verbose_name='사유')
    description = models.CharField(max_length=200, blank=True, verbose_name='상세 설명')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일시')

    class Meta:
        verbose_name = '포인트 히스토리'
        verbose_name_plural = '포인트 히스토리 목록'
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.amount > 0 else ''
        return f"{self.user.username} {sign}{self.amount}P - {self.get_reason_display()}"


class BlockedIP(models.Model):
    """차단된 IP 주소"""
    ip_address = models.GenericIPAddressField(unique=True, verbose_name='IP 주소')
    reason = models.CharField(max_length=200, blank=True, verbose_name='차단 사유')
    blocked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='차단한 관리자', related_name='blocked_ips')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='차단일시')
    is_active = models.BooleanField(default=True, verbose_name='활성 상태')

    class Meta:
        verbose_name = '차단된 IP'
        verbose_name_plural = '차단된 IP 목록'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.ip_address} ({self.reason})"

# Create your models here.
