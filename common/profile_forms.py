from django import forms
from django.contrib.auth.models import User
from .models import Profile


class ProfileForm(forms.ModelForm):
    """프로필 설정 폼"""
    nickname = forms.CharField(
        max_length=30, 
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '닉네임을 입력하세요 (선택사항)'
        }),
        help_text='닉네임을 설정하지 않으면 사용자명이 표시됩니다.'
    )
    
    theme = forms.ChoiceField(
        choices=Profile.THEME_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='사이트 테마를 선택하세요.'
    )
    
    class Meta:
        model = Profile
        fields = ['nickname', 'theme']


class UserUpdateForm(forms.ModelForm):
    """사용자 정보 수정 폼"""
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': True
        }),
        help_text='사용자명은 변경할 수 없습니다.'
    )
    
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': '이메일 주소를 입력하세요'
        })
    )
    
    first_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '이름을 입력하세요'
        })
    )
    
    last_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '성을 입력하세요'
        })
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']