from django.db import models
from django.contrib.auth import get_user_model


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


# Create your models here.
