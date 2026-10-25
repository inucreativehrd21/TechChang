"""office.calendar_feed.lab_schedule — 며칠(schedule) 달력에 얹는 연구실 일정.

schedule 앱이 설치되지 않아도 돈다(FeedItem 은 모델이 아니다).
"""
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office.calendar_feed import lab_schedule
from office.models import ColumnDraft, Meeting, Newsletter

NOW = timezone.make_aware(datetime(2026, 10, 15, 12, 0))      # 목요일 정오(KST)
START, END = date(2026, 10, 12), date(2026, 10, 31)


def aware(*args):
    return timezone.make_aware(datetime(*args))


class LabScheduleFeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bot = User.objects.create_user('techchang연구팀', password='x-pass-12345')
        cls.staff = User.objects.create_user('editor', password='x-pass-12345', is_staff=True)
        category = Category.objects.create(name='데이터분석')
        cls.question = Question.objects.create(author=cls.bot, subject='회귀분석 첫걸음', content='본문',
                                               create_date=aware(2026, 10, 14, 10, 0), category=category)
        ColumnDraft.objects.create(topic='data', status=ColumnDraft.STATUS_PUBLISHED, question=cls.question,
                                   subject=cls.question.subject)
        ColumnDraft.objects.create(topic='coding', status=ColumnDraft.STATUS_READY, subject='비밀 원고 제목',
                                   publish_at=aware(2026, 10, 17, 10, 0))
        Newsletter.objects.create(issue_no=7, slug='2026-w42', week_start=date(2026, 10, 9),
                                  week_end=date(2026, 10, 15), title='이번 주 연구실', published_at=aware(2026, 10, 16, 10, 0))
        meeting = Meeting.objects.create(week_start=date(2026, 10, 12))
        Meeting.objects.filter(pk=meeting.pk).update(held_at=aware(2026, 10, 18, 20, 0))

    def feed(self, user=None):
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            return {item.key: item for item in lab_schedule(START, END, user or AnonymousUser())}

    def test_published_column_links_to_post(self):
        item = self.feed()[f'lab:post:{self.question.pk}']
        self.assertEqual(item.title, '회귀분석 첫걸음')
        self.assertEqual(item.start_date, date(2026, 10, 14))
        self.assertEqual(item.time, time(10, 0))
        self.assertEqual(item.url, f'/{self.question.pk}/')
        self.assertEqual(item.note, '데이터분석 칼럼')

    def test_ready_draft_hides_subject_from_non_staff(self):
        anon = [i for i in self.feed().values() if i.key.startswith('lab:ready:')]
        self.assertEqual([i.title for i in anon], ['프로그래밍 칼럼 공개'])
        staff = [i for i in self.feed(self.staff).values() if i.key.startswith('lab:ready:')]
        self.assertEqual([i.title for i in staff], ['비밀 원고 제목'])

    def test_regular_slots_skip_past_and_filled_times(self):
        keys = self.feed().keys()
        self.assertNotIn('lab:slot:data:20261015', keys)          # 오늘 10시는 이미 지남
        self.assertNotIn('lab:slot:coding:20261017', keys)        # 예약 원고가 있는 시각
        self.assertIn('lab:slot:hrd:20261020', keys)
        self.assertIn('lab:slot:data:20261022', keys)
        self.assertIn("lab:slot:coding:20261024", keys)
        self.assertFalse(self.feed()["lab:slot:hrd:20261020"].listed)   # 요약 목록에는 올리지 않는다

    def test_slots_stop_after_projection_window(self):
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            items = lab_schedule(START, date(2026, 12, 31), AnonymousUser())
        last_slot = max(i.start_date for i in items if i.key.startswith('lab:slot:'))
        self.assertLessEqual(last_slot, NOW.date() + timedelta(days=21))

    def test_newsletter_and_meeting(self):
        feed = self.feed()
        self.assertEqual(feed['lab:weekly:7'].url, '/newsletter/2026-w42/')
        meeting = next(i for i in feed.values() if i.key.startswith('lab:meeting:'))
        self.assertEqual((meeting.start_date, meeting.time), (date(2026, 10, 18), time(20, 0)))
