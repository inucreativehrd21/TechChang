"""화면·권한: 공개 범위, 등록/수정/삭제 권한, 입력 검증, 피드 장애 격리, 모바일 템플릿, ICS."""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from schedule.feeds import FeedItem
from schedule.models import Event, WeatherSnapshot

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}
NO_FEEDS = {'FIRST_WEEKDAY': 6, 'FEED_PROVIDERS': []}


def broken_provider(start, end, user):
    raise RuntimeError('provider down')


def sample_provider(start, end, user):
    return [FeedItem(key='test:lab:1', title='데이터분석 칼럼 공개', start_date=timezone.localdate(),
                     time=time(10), icon='fa-feather', note='공개 예정')]


def view_context(response) -> dict:
    """뷰가 템플릿에 넘긴 값 (include 가 있으면 ContextList 로 온다)"""
    ctx = response.context
    return (ctx[0] if isinstance(ctx, list) else ctx).flatten()


def make_user(username, **extra):
    user = get_user_model().objects.create_user(username, password='calendar-pass-12', **extra)
    profile = getattr(user, 'profile', None)        # 호스트 사이트의 이메일 인증 강제 미들웨어 대비
    if profile is not None and hasattr(profile, 'is_email_verified'):
        profile.is_email_verified = True
        profile.save()
    return user


@override_settings(SCHEDULE=NO_FEEDS)
class ScheduleViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.owner = make_user('owner')
        cls.other = make_user('other')
        cls.staff = make_user('staffer', is_staff=True)
        cls.private = Event.objects.create(owner=cls.owner, title='치과 예약', start_date=cls.today,
                                           end_date=cls.today, start_time=time(11), end_time=time(12))
        cls.community = Event.objects.create(owner=cls.staff, title='HRD 밋업, 강남', start_date=cls.today,
                                             end_date=cls.today + timedelta(days=1),
                                             visibility=Event.COMMUNITY, location='강남역')

    def get(self, url, **extra):
        return self.client.get(url, **UA, **extra)

    # --- 공개 범위 ---
    def test_anonymous_sees_community_but_not_private(self):
        response = self.get(reverse('schedule:month'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'HRD 밋업')
        self.assertNotContains(response, '치과 예약')
        self.assertContains(response, '로그인하면 내 일정도')

    def test_owner_sees_private_other_user_does_not(self):
        self.client.force_login(self.owner)
        self.assertContains(self.get(reverse('schedule:month')), '치과 예약')
        self.client.force_login(self.other)
        self.assertNotContains(self.get(reverse('schedule:month')), '치과 예약')

    def test_private_detail_is_404_for_others(self):
        url = self.private.get_absolute_url()
        self.assertEqual(self.get(url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.get(url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertContains(self.get(url), '치과 예약')

    def test_community_detail_is_public(self):
        self.assertContains(self.get(self.community.get_absolute_url()), '강남역')

    # --- 등록 ---
    def test_create_requires_login(self):
        response = self.get(reverse('schedule:event_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('next=', response['Location'])

    def test_member_creates_private_event_even_if_posting_community(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('schedule:event_create'), {
            'title': '스터디', 'start_date': self.today.isoformat(), 'visibility': Event.COMMUNITY,
        }, **UA)
        self.assertEqual(response.status_code, 302)
        event = Event.objects.get(title='스터디')
        self.assertEqual(event.visibility, Event.PRIVATE)
        self.assertEqual(event.end_date, self.today)             # 종료일 비우면 하루 일정
        self.assertTrue(event.is_all_day)

    def test_staff_can_create_community_event(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('schedule:event_create'), {
            'title': '공식 세미나', 'start_date': self.today.isoformat(), 'visibility': Event.COMMUNITY,
        }, **UA)
        self.assertEqual(Event.objects.get(title='공식 세미나').visibility, Event.COMMUNITY)

    def test_create_form_prefills_date(self):
        self.client.force_login(self.owner)
        response = self.get(reverse('schedule:event_create') + f'?date={self.today.isoformat()}')
        self.assertContains(response, f'value="{self.today.isoformat()}"')
        self.assertNotContains(response, 'name="visibility"')    # 일반 회원에게는 공개 범위가 없다

    def test_validation_messages(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('schedule:event_create'), {
            'title': '거꾸로', 'start_date': self.today.isoformat(),
            'end_date': (self.today - timedelta(days=1)).isoformat(),
        }, **UA)
        self.assertContains(response, '종료일은 시작일과 같거나 그 뒤여야 해요.')
        response = self.client.post(reverse('schedule:event_create'), {
            'title': '시각만', 'start_date': self.today.isoformat(), 'end_time': '10:00',
        }, **UA)
        self.assertContains(response, '시작 시각도 넣어 주세요')
        response = self.client.post(reverse('schedule:event_create'), {
            'title': '시각 역전', 'start_date': self.today.isoformat(), 'start_time': '15:00', 'end_time': '14:00',
        }, **UA)
        self.assertContains(response, '종료 시각은 시작 시각보다 늦어야 해요.')
        self.assertFalse(Event.objects.filter(title__in=['거꾸로', '시각만', '시각 역전']).exists())

    # --- 수정·삭제 권한 ---
    def test_edit_permissions(self):
        self.client.force_login(self.other)
        self.assertEqual(self.get(reverse('schedule:event_edit', args=[self.private.pk])).status_code, 404)
        self.assertEqual(self.get(reverse('schedule:event_edit', args=[self.community.pk])).status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.post(reverse('schedule:event_edit', args=[self.private.pk]), {
            'title': '치과 예약 변경', 'start_date': self.today.isoformat(),
        }, **UA)
        self.assertEqual(response.status_code, 302)
        self.private.refresh_from_db()
        self.assertEqual(self.private.title, '치과 예약 변경')

    def test_delete_flow(self):
        self.client.force_login(self.owner)
        url = reverse('schedule:event_delete', args=[self.private.pk])
        self.assertContains(self.get(url), '일정을 삭제할까요?')
        self.assertEqual(self.client.post(url, **UA).status_code, 302)
        self.assertFalse(Event.objects.filter(pk=self.private.pk).exists())

    # --- 날짜 화면 ---
    def test_day_view_and_bad_dates(self):
        response = self.get(reverse('schedule:day', args=[self.today.isoformat()]))
        self.assertContains(response, 'HRD 밋업')
        self.assertEqual(self.get(reverse('schedule:day', args=['2026-13-40'])).status_code, 404)
        self.assertEqual(self.get(reverse('schedule:month_at', args=[1999, 1])).status_code, 404)
        self.assertEqual(self.get(reverse('schedule:month_at', args=[2026, 13])).status_code, 404)

    def test_explicit_month_is_noindex(self):
        response = self.get(reverse('schedule:month_at', args=[self.today.year, self.today.month]))
        self.assertContains(response, 'noindex, follow')

    # --- 피드 ---
    @override_settings(SCHEDULE={**NO_FEEDS, 'FEED_PROVIDERS': ['schedule.tests.test_views.broken_provider']})
    def test_broken_feed_does_not_break_calendar(self):
        with self.assertLogs('schedule.feeds', level='ERROR'):
            response = self.get(reverse('schedule:month'))
        self.assertContains(response, 'HRD 밋업')

    @override_settings(SCHEDULE={**NO_FEEDS, 'FEED_PROVIDERS': ['schedule.tests.test_views.sample_provider']})
    def test_feed_items_are_drawn(self):
        response = self.get(reverse('schedule:month'))
        self.assertContains(response, '데이터분석 칼럼 공개')
        self.assertContains(response, 'mc-k-lab')

    # --- 날씨 ---
    def test_weather_snapshot_is_shown_with_source(self):
        WeatherSnapshot.objects.create(region='서울', announced_at='202610160600', days={
            self.today.isoformat(): {'condition': '구름많음', 'icon': 'schedule/weather/03_overcast.svg',
                                     'temp_low': 14, 'temp_high': 23, 'rain_prob': 30},
        })
        response = self.get(reverse('schedule:month'))
        self.assertContains(response, '03_overcast.svg')
        self.assertContains(response, '기상청 단기예보')
        self.assertContains(response, '강수확률 30%')

    # --- 모바일 템플릿 ---
    def test_mobile_templates_render_with_view_context(self):
        self.client.force_login(self.owner)
        response = self.get(reverse('schedule:month'))
        html = render_to_string('schedule/mobile/month.html', view_context(response),
                                request=response.wsgi_request)
        self.assertIn('mc-m-grid', html)
        self.assertIn('치과 예약', html)
        day = self.get(reverse('schedule:day', args=[self.today.isoformat()]))
        self.assertIn('HRD 밋업', render_to_string('schedule/mobile/day.html', view_context(day),
                                                    request=day.wsgi_request))

    # --- ICS ---
    def test_ics_contains_only_public_items(self):
        response = self.get(reverse('schedule:community_ics'))
        self.assertEqual(response['Content-Type'], 'text/calendar; charset=utf-8')
        body = response.content.decode()
        self.assertIn('BEGIN:VCALENDAR', body)
        self.assertIn('SUMMARY:HRD 밋업\\, 강남', body)
        self.assertIn(f'DTSTART;VALUE=DATE:{self.today:%Y%m%d}', body)
        self.assertNotIn('치과', body)
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split('\r\n')))


def unlisted_provider(start, end, user):
    day = timezone.localdate() + timedelta(days=3)
    return [FeedItem(key='test:slot:1', title='매주 정기 안내', start_date=day, listed=False),
            FeedItem(key='test:news:1', title='위클리 발행', start_date=day)]


@override_settings(SCHEDULE={**NO_FEEDS, 'FEED_PROVIDERS': ['schedule.tests.test_views.unlisted_provider']})
class UpcomingSummaryTests(TestCase):
    def test_unlisted_feed_items_stay_on_grid_only(self):
        response = self.client.get(reverse('schedule:month'), **UA)
        upcoming = [it.title for it in view_context(response)['upcoming']]
        self.assertEqual(upcoming, ['위클리 발행'])
        self.assertContains(response, '매주 정기 안내')          # 달력 칸에는 그린다
