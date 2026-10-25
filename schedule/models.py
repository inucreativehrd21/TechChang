from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

MAX_SPAN_DAYS = 366


class Event(models.Model):
    """회원이 등록하는 일정. 개인 일정(나만 보기)과 커뮤니티 일정(모두에게 공개, 운영진 등록)."""

    PRIVATE = 'private'
    COMMUNITY = 'community'
    VISIBILITY_CHOICES = [
        (PRIVATE, '나만 보기'),
        (COMMUNITY, '커뮤니티 일정'),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='schedule_events', verbose_name='등록한 사람')
    title = models.CharField('제목', max_length=100)
    start_date = models.DateField('시작일', db_index=True)
    end_date = models.DateField('종료일', db_index=True)
    start_time = models.TimeField('시작 시각', null=True, blank=True)
    end_time = models.TimeField('종료 시각', null=True, blank=True)
    location = models.CharField('장소', max_length=120, blank=True)
    link = models.URLField('관련 링크', blank=True)
    memo = models.TextField('메모', blank=True)
    visibility = models.CharField('공개 범위', max_length=10, choices=VISIBILITY_CHOICES,
                                  default=PRIVATE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_date', 'start_time', 'id']
        indexes = [models.Index(fields=['visibility', 'start_date', 'end_date'])]
        verbose_name = '일정'
        verbose_name_plural = '일정'

    def __str__(self):
        return f'{self.start_date} {self.title}'

    def clean(self):
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValidationError({'end_date': '종료일은 시작일과 같거나 그 뒤여야 해요.'})
            if self.end_date - self.start_date > timedelta(days=MAX_SPAN_DAYS):
                raise ValidationError({'end_date': '일정은 1년을 넘길 수 없어요.'})
        if (self.start_date == self.end_date and self.start_time and self.end_time
                and self.end_time <= self.start_time):
            raise ValidationError({'end_time': '종료 시각은 시작 시각보다 늦어야 해요.'})

    @property
    def is_community(self):
        return self.visibility == self.COMMUNITY

    @property
    def is_all_day(self):
        return self.start_time is None

    def get_absolute_url(self):
        return reverse('schedule:event_detail', args=[self.pk])

    def is_visible_to(self, user):
        return self.is_community or (user.is_authenticated and user.pk == self.owner_id)

    def can_edit(self, user):
        if not user.is_authenticated:
            return False
        if self.is_community:
            return user.is_staff or user.pk == self.owner_id
        return user.pk == self.owner_id


class WeatherSnapshot(models.Model):
    """기상청 예보를 받아 둔 결과. 화면은 이것만 읽는다(요청마다 기상청을 부르지 않는다).

    days = {'YYYY-MM-DD': {'condition', 'icon', 'temp_low', 'temp_high', 'rain_prob'}}
    """

    region = models.CharField(max_length=40)
    announced_at = models.CharField('기상청 발표시각', max_length=12, blank=True)
    days = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        get_latest_by = 'fetched_at'
        verbose_name = '날씨 스냅샷'
        verbose_name_plural = '날씨 스냅샷'

    def __str__(self):
        return f'{self.region} {self.announced_at}'
