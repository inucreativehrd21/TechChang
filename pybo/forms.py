
from django import forms
from pybo.models import Question, Answer, Comment, Category


class QuestionForm(forms.ModelForm):
    # 카테고리는 실제 Category 인스턴스를 선택하도록 변경
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(name__in=['HRD', '데이터분석', '프로그래밍']).order_by('name'),
        empty_label='카테고리 선택',
        widget=forms.Select(attrs={'class': 'form-select', 'required': True}),
        label='카테고리'
    )
    
    class Meta:
        model = Question  # 사용할 모델
        fields = ['category', 'subject', 'content', 'image']  # 이미지 필드 추가
        labels = {
            'subject': '제목',
            'content': '내용',
            'image': '이미지 첨부',
        }  # 폼의 속성에 대한 한글 라벨 지정
        widgets = {
            'subject': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '질문 제목을 입력하세요'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 10,
                'placeholder': '질문 내용을 자세히 작성해주세요'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }

class AnswerForm(forms.ModelForm):
    class Meta:
        model = Answer
        fields = ['content', 'image']
        labels = {
            'content': '답변내용',
            'image': '이미지 첨부',
        }
        widgets = {
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content', 'image']
        labels = {
            'content': '댓글내용',
            'image': '이미지 첨부',
        }
        widgets = {
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }