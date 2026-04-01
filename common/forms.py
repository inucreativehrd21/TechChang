
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from PIL import Image
import os
from .models import Profile, EmailVerification

ALLOWED_PROFILE_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_PROFILE_IMAGE_DIMENSION = 5000


class UserForm(UserCreationForm):
    email = forms.EmailField(
        label="이메일",
        help_text="이메일 인증이 필요합니다.",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'example@email.com'
        })
    )
    nickname = forms.CharField(
        max_length=30,
        required=False,
        label="닉네임",
        help_text="닉네임을 설정하지 않으면 사용자명이 표시됩니다.",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '커뮤니티에서 표시될 이름'
        })
    )
    email_code = forms.CharField(
        max_length=4,
        label="이메일 인증코드",
        help_text="이메일로 받은 4자리 인증코드를 입력하세요.",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '4자리 숫자'
        })
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '영문, 숫자, 특수문자'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 비밀번호 필드에 Bootstrap 클래스 추가
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '8자리 이상'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '비밀번호 재입력'
        })

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("이미 사용 중인 이메일입니다.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['nickname', 'profile_image']
        labels = {
            'nickname': '닉네임',
            'profile_image': '프로필 이미지',
        }
        widgets = {
            'nickname': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '닉네임을 입력하세요'}),
            'profile_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean_profile_image(self):
        image = self.cleaned_data.get('profile_image')
        if image and hasattr(image, 'name'):
            ext = os.path.splitext(image.name)[1].lower()
            if ext == '.svg':
                raise ValidationError('SVG 파일은 보안상의 이유로 업로드할 수 없습니다.')
            if ext not in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
                raise ValidationError(
                    f'허용되지 않는 이미지 형식입니다. 허용: {", ".join(ALLOWED_PROFILE_IMAGE_EXTENSIONS)}'
                )
            if image.size > MAX_PROFILE_IMAGE_SIZE:
                raise ValidationError(
                    f'이미지 크기가 너무 큽니다. 최대 {MAX_PROFILE_IMAGE_SIZE // (1024 * 1024)}MB까지 가능합니다.'
                )
            try:
                img = Image.open(image)
                if img.width > MAX_PROFILE_IMAGE_DIMENSION or img.height > MAX_PROFILE_IMAGE_DIMENSION:
                    raise ValidationError(
                        f'이미지 해상도가 너무 높습니다. 최대 {MAX_PROFILE_IMAGE_DIMENSION}x{MAX_PROFILE_IMAGE_DIMENSION}px까지 가능합니다.'
                    )
                img.verify()
                image.seek(0)
            except ValidationError:
                raise
            except Exception:
                raise ValidationError('유효하지 않은 이미지 파일입니다.')
        return image


class EmailVerificationForm(forms.Form):
    """이메일 인증 코드 확인 폼"""
    email = forms.EmailField(label="이메일")
    code = forms.CharField(max_length=6, min_length=6, label="인증코드",
                          help_text="이메일로 받은 6자리 숫자를 입력하세요.")

    def clean_code(self):
        code = self.cleaned_data.get('code')
        if not code.isdigit():
            raise forms.ValidationError("인증코드는 6자리 숫자여야 합니다.")
        return code

