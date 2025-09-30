
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, EmailVerification


class UserForm(UserCreationForm):
    email = forms.EmailField(label="이메일", help_text="이메일 인증이 필요합니다.")
    nickname = forms.CharField(max_length=30, required=False, label="닉네임", 
                              help_text="닉네임을 설정하지 않으면 사용자명이 표시됩니다.")
    email_code = forms.CharField(max_length=4, label="이메일 인증코드", 
                                help_text="이메일로 받은 4자리 인증코드를 입력하세요.", 
                                required=False)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")
    
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


class EmailVerificationForm(forms.Form):
    """이메일 인증 코드 확인 폼"""
    email = forms.EmailField(label="이메일")
    code = forms.CharField(max_length=4, min_length=4, label="인증코드",
                          help_text="이메일로 받은 4자리 숫자를 입력하세요.")
    
    def clean_code(self):
        code = self.cleaned_data.get('code')
        if not code.isdigit():
            raise forms.ValidationError("인증코드는 4자리 숫자여야 합니다.")
        return code

