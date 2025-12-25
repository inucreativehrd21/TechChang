
from django import forms
from django.core.exceptions import ValidationError
from PIL import Image
import os
from community.models import Question, Answer, Comment, Category

# 보안: 허용할 파일 확장자 정의
ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
ALLOWED_FILE_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt', '.zip', '.hwp', '.xlsx', '.pptx']
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_FILE_SIZE = 20 * 1024 * 1024   # 20MB


class QuestionForm(forms.ModelForm):
    """질문 생성/수정 폼 - 동적 카테고리 로딩 지원"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 동적으로 활성 카테고리만 로드
        self.fields['category'].queryset = Category.objects.all().order_by('name')
        self.fields['category'].empty_label = '카테고리를 선택하세요'
        
        # 필드별 커스텀 설정
        self._setup_form_fields()
    
    def _setup_form_fields(self):
        """폼 필드 설정 및 스타일링"""
        # 카테고리 필드 설정
        self.fields['category'].widget.attrs.update({
            'class': 'form-select',
            'required': True,
            'data-bs-toggle': 'tooltip',
            'title': '질문에 적합한 카테고리를 선택해주세요'
        })
        
        # 제목 필드 향상
        self.fields['subject'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': '명확하고 구체적인 질문 제목을 입력하세요',
            'maxlength': 200
        })
        
        # 내용 필드 향상
        self.fields['content'].widget.attrs.update({
            'class': 'form-control',
            'rows': 12,
            'placeholder': '질문의 배경, 시도한 방법, 기대하는 결과 등을 자세히 작성해주세요',
        })
        
        # 이미지 필드 향상
        self.fields['image'].widget.attrs.update({
            'class': 'form-control',
            'accept': 'image/*',
            'data-bs-toggle': 'tooltip',
            'title': '관련 이미지나 스크린샷을 첨부하세요 (선택사항)'
        })

        # 파일 필드 향상
        self.fields['file'].widget.attrs.update({
            'class': 'form-control',
            'data-bs-toggle': 'tooltip',
            'title': 'PDF, 문서, 압축파일 등을 첨부할 수 있습니다 (선택사항)'
        })

    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),  # __init__에서 동적 설정
        label='카테고리',
        help_text='질문 내용에 가장 적합한 카테고리를 선택하세요.'
    )

    def clean_image(self):
        """이미지 파일 검증 (확장자, 크기, 유효성)"""
        image = self.cleaned_data.get('image')
        if image:
            # 파일 확장자 검증
            ext = os.path.splitext(image.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError(
                    f'허용되지 않는 이미지 형식입니다. '
                    f'허용: {", ".join(ALLOWED_IMAGE_EXTENSIONS)}'
                )

            # 파일 크기 검증
            if image.size > MAX_IMAGE_SIZE:
                raise ValidationError(
                    f'이미지 크기가 너무 큽니다. 최대 {MAX_IMAGE_SIZE // (1024*1024)}MB까지 가능합니다.'
                )

            # 이미지 유효성 검증 (악성 파일 방지)
            try:
                img = Image.open(image)
                img.verify()  # 이미지 손상 여부 확인
                # verify() 후에는 파일 포인터를 처음으로 되돌려야 함
                image.seek(0)
            except Exception:
                raise ValidationError('유효하지 않은 이미지 파일입니다.')

        return image

    def clean_file(self):
        """첨부 파일 검증 (확장자, 크기)"""
        file = self.cleaned_data.get('file')
        if file:
            # 파일 확장자 검증
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in ALLOWED_FILE_EXTENSIONS:
                raise ValidationError(
                    f'허용되지 않는 파일 형식입니다. '
                    f'허용: {", ".join(ALLOWED_FILE_EXTENSIONS)}'
                )

            # 파일 크기 검증
            if file.size > MAX_FILE_SIZE:
                raise ValidationError(
                    f'파일 크기가 너무 큽니다. 최대 {MAX_FILE_SIZE // (1024*1024)}MB까지 가능합니다.'
                )

        return file

    class Meta:
        model = Question  # 사용할 모델
        fields = ['category', 'subject', 'content', 'image', 'file', 'is_locked']  # 파일 필드 및 잠금 필드 추가
        labels = {
            'subject': '제목',
            'content': '내용',
            'image': '이미지 첨부',
            'file': '파일 첨부',
            'is_locked': '회원 전용 글',
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
    """답변 생성/수정 폼 - 향상된 UX 지원"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_form_fields()
    
    def _setup_form_fields(self):
        """폼 필드 설정 및 스타일링"""
        self.fields['content'].widget.attrs.update({
            'class': 'form-control',
            'rows': 8,
            'placeholder': '도움이 되는 답변을 작성해주세요. 구체적인 예시나 설명을 포함하면 더욱 좋습니다.',
        })

        self.fields['image'].widget.attrs.update({
            'class': 'form-control',
            'accept': 'image/*',
            'data-bs-toggle': 'tooltip',
            'title': '답변을 설명하는 이미지나 코드 스크린샷을 첨부할 수 있습니다'
        })

    def clean_image(self):
        """이미지 파일 검증 (확장자, 크기, 유효성)"""
        image = self.cleaned_data.get('image')
        if image:
            # 파일 확장자 검증
            ext = os.path.splitext(image.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError(
                    f'허용되지 않는 이미지 형식입니다. '
                    f'허용: {", ".join(ALLOWED_IMAGE_EXTENSIONS)}'
                )

            # 파일 크기 검증
            if image.size > MAX_IMAGE_SIZE:
                raise ValidationError(
                    f'이미지 크기가 너무 큽니다. 최대 {MAX_IMAGE_SIZE // (1024*1024)}MB까지 가능합니다.'
                )

            # 이미지 유효성 검증 (악성 파일 방지)
            try:
                img = Image.open(image)
                img.verify()
                image.seek(0)
            except Exception:
                raise ValidationError('유효하지 않은 이미지 파일입니다.')

        return image

    class Meta:
        model = Answer
        fields = ['content', 'image']
        labels = {
            'content': '답변 내용',
            'image': '이미지 첨부 (선택사항)',
        }
        help_texts = {
            'content': '질문에 대한 상세한 답변을 작성해주세요.',
        }

class CommentForm(forms.ModelForm):
    """댓글 생성/수정 폼 - 간결한 사용성 지원"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_form_fields()
    
    def _setup_form_fields(self):
        """폼 필드 설정 및 스타일링"""
        self.fields['content'].widget.attrs.update({
            'class': 'form-control',
            'rows': 3,
            'placeholder': '댓글을 작성해주세요. 건설적인 의견을 개진합니다.',
            'maxlength': 500
        })

        self.fields['image'].widget.attrs.update({
            'class': 'form-control',
            'accept': 'image/*',
            'data-bs-toggle': 'tooltip',
            'title': '댓글에 관련 이미지를 첨부할 수 있습니다'
        })

    def clean_image(self):
        """이미지 파일 검증 (확장자, 크기, 유효성)"""
        image = self.cleaned_data.get('image')
        if image:
            # 파일 확장자 검증
            ext = os.path.splitext(image.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError(
                    f'허용되지 않는 이미지 형식입니다. '
                    f'허용: {", ".join(ALLOWED_IMAGE_EXTENSIONS)}'
                )

            # 파일 크기 검증
            if image.size > MAX_IMAGE_SIZE:
                raise ValidationError(
                    f'이미지 크기가 너무 큽니다. 최대 {MAX_IMAGE_SIZE // (1024*1024)}MB까지 가능합니다.'
                )

            # 이미지 유효성 검증 (악성 파일 방지)
            try:
                img = Image.open(image)
                img.verify()
                image.seek(0)
            except Exception:
                raise ValidationError('유효하지 않은 이미지 파일입니다.')

        return image

    class Meta:
        model = Comment
        fields = ['content', 'image']
        labels = {
            'content': '댓글 내용',
            'image': '이미지 첨부 (선택사항)',
        }
        help_texts = {
            'content': '질문이나 답변에 대한 짧은 의견을 남겨주세요.',
        }