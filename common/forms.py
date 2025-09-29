
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile


class UserForm(UserCreationForm):
    email = forms.EmailField(label="이메일")
    nickname = forms.CharField(max_length=30, required=False, label="닉네임", 
                              help_text="닉네임을 설정하지 않으면 사용자명이 표시됩니다.")

    class Meta:
        model = User
        fields = ("username", "password1", "password2", "email")


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

