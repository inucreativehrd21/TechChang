from django import forms

from .models import Event


class EventForm(forms.ModelForm):
    """일정 추가·수정. 시각을 비우면 하루 종일 일정이 된다. 공개 범위는 운영진에게만 보인다."""

    class Meta:
        model = Event
        fields = ['title', 'start_date', 'end_date', 'start_time', 'end_time',
                  'location', 'link', 'memo', 'visibility']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
            'location': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'autocomplete': 'off', 'placeholder': 'https://…'}),
            'memo': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'autocomplete': 'off'}),
            'visibility': forms.RadioSelect,
        }
        help_texts = {
            'start_time': '시각을 비워 두면 하루 종일 일정으로 저장돼요.',
            'location': '예: 강남역 스터디룸, 온라인(Zoom)',
            'link': '신청 페이지나 관련 글이 있으면 넣어 주세요.',
            'visibility': '커뮤니티 일정은 로그인하지 않은 방문자에게도 보여요.',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['end_date'].required = False
        self.fields['end_date'].help_text = '하루 일정이면 비워 두세요.'
        if not (user and user.is_staff):
            del self.fields['visibility']

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        if start and not cleaned.get('end_date'):
            cleaned['end_date'] = start
            self.instance.end_date = start
        if cleaned.get('end_time') and not cleaned.get('start_time'):
            self.add_error('start_time', '종료 시각을 넣으려면 시작 시각도 넣어 주세요.')
        return cleaned
