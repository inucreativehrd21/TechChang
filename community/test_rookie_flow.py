"""실제 폼·CSRF·저장·리다이렉트를 거치는 커리어 통합 검사."""
import copy
import json
import random
from collections import Counter
from datetime import timedelta
from unittest import mock

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from . import rookie as R
from . import rookie_career as C
from . import rookie_league as L
from . import rookie_lite as X
from . import rookie_story as S
from . import rookie_world as W
from .management.commands.rookie_balance import choose
from .models import LiteCareer, RookiePlayer
from .test_rookie_lite import member, PC, MOBILE


class CareerHttpFlowTests(TestCase):
    def post_form(self, client, url, data):
        response = client.post(url, data, follow=True,
                               HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, (url, data))
        warnings = [str(m) for m in get_messages(response.wsgi_request) if m.level >= 30]
        self.assertEqual(warnings, [], (url, data, warnings))
        return response

    def run_life(self, role, position, ua, guest, seed, policy):
        cache.clear()
        client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=ua)
        user = member('flow-' + str(seed))
        if not guest:
            client.force_login(user)
        self.assertEqual(client.get('/rookie/lite/').status_code, 200)
        rng = random.Random(seed)
        with mock.patch('community.views.rookie_lite_views._rng', return_value=rng):
            self.post_form(client, '/rookie/lite/new/', dict(
                name='흐름검사', role=role, region='서울', team='lg', number=17,
                **{'position_' + role: position, 'style_' + role: list(X.STYLES[role])[0]}))
            c = LiteCareer.objects.get(user=user) if not guest else LiteCareer.objects.get(guest=client.session['lite_guest'])
            seen = Counter()
            claimed = False
            for step in range(260):
                # 수십 년 분량을 수초에 진행한다. 실제 분당 요청 제한과는 별도로 검사한다.
                cache.clear()
                c.refresh_from_db()
                if c.retired_at:
                    break
                if guest and not claimed and c.seasons.count() >= 3:
                    client.force_login(user)
                    self.assertEqual(client.get('/rookie/lite/').status_code, 200)
                    c.refresh_from_db()
                    self.assertEqual(c.user_id, user.pk)
                    self.assertEqual(c.guest, '')
                    claimed = True
                pending = copy.deepcopy(c.pending)
                seen[pending.get('what', pending['kind'])] += 1
                if pending['kind'] == 'plan':
                    event = pending.get('event')
                    data = dict(action='play', program=X.pick_programs(c, rng), intensity='normal')
                    if event:
                        data['event_choice'] = rng.choice(X.EVENTS[event]['choices'])[0]
                    data.update({'intl_' + key: 'go' for key in pending.get('intl') or []})
                elif pending['kind'] == 'review':
                    data = dict(action='next')
                else:
                    decision = X.decision_view(c)
                    data = dict(action='decide', what=pending['what'], choice=choose(c, rng, policy),
                                event_id=decision.get('id', ''))
                before = (json.dumps(pending, sort_keys=True), c.year, c.seasons.count())
                self.post_form(client, '/rookie/lite/act/', data)
                c.refresh_from_db()
                after = (json.dumps(c.pending, sort_keys=True), c.year, c.seasons.count())
                self.assertTrue(c.retired_at or before != after, (step, data, c.pending))
            self.assertIsNotNone(c.retired_at, (seen, c.pending))
            self.assertGreater(seen['plan'], 3)
            self.assertGreater(seen['draft'], 0)
            self.assertGreater(seen['review'], 0)
            if guest:
                self.assertTrue(claimed)
            for url in (f'/rookie/lite/c/{c.pk}/', f'/rookie/lite/c/{c.pk}/card/',
                        '/rookie/lite/cards/', '/rookie/lite/hall/', '/rookie/lite/today/'):
                self.assertEqual(client.get(url).status_code, 200, url)
            other = Client(HTTP_USER_AGENT=ua)
            self.assertEqual(other.get(f'/rookie/lite/c/{c.pk}/card/').status_code, 200)

    def test_member_batter_desktop_entire_career(self):
        self.run_life('batter', 'SS', PC, False, 20261051, 'us')

    def test_guest_batter_mobile_claim_and_entire_career(self):
        self.run_life('batter', 'OF', MOBILE, True, 20261052, 'playing')

    def test_member_relief_mobile_entire_career(self):
        self.run_life('pitcher', 'RP', MOBILE, False, 20261053, 'us')

    def test_guest_starter_desktop_claim_and_entire_career(self):
        self.run_life('pitcher', 'SP', PC, True, 20261054, 'domestic')


class FullCareerHttpFlowTests(TestCase):
    post_form = CareerHttpFlowTests.post_form

    def test_little_league_to_pro_and_retirement_with_daily_activity(self):
        cache.clear()
        user = member('full-flow')
        client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=MOBILE)
        client.force_login(user)
        start = timezone.localdate()
        rng = random.Random(20261055)
        with mock.patch('random.SystemRandom', return_value=rng):
            client.get('/rookie/')
            self.post_form(client, '/rookie/create/', dict(
                name='흐름투수', role='pitcher', pitch_position='RP', team='lg', region='서울',
                focus_pitcher='control', number=17))
            p = RookiePlayer.objects.get(user=user)
            leagues = set()
            for offset in range(1100):
                cache.clear()
                day = start + timedelta(days=offset)
                with mock.patch('django.utils.timezone.localdate', return_value=day):
                    L.advance(day, max_days=4)
                    R.award(user, 'checkin', ref=day.isoformat())
                    self.assertEqual(client.get('/rookie/').status_code, 200)
                    p.refresh_from_db()
                    leagues.add(p.league)
                    if p.retired_at:
                        break
                    if p.pending.get('kind') == 'apply' and not p.pending.get('choice'):
                        school = W.schools(p.pending['to'])[0][1]
                        self.post_form(client, '/rookie/apply/', dict(school=school))
                    elif p.pending.get('kind') == 'draft':
                        self.post_form(client, '/rookie/decide/', dict(
                            choice='sign' if p.pending.get('offer') else 'develop'))
                    p.refresh_from_db()
                    event = S.daily_view(p)
                    if event:
                        keys = [ch['key'] for ch in event.get('choices', [])]
                        preferred = ('test', 'course', 'accept', 'rebuild', 'retry', 'keep', 'stay', 'retire')
                        choice = next((key for key in preferred if key in keys), keys[0] if keys else 'stay')
                        self.post_form(client, '/rookie/story/', dict(event_id=event['id'], choice=choice))
                    p.refresh_from_db()
                    if p.retired_at:
                        break
                    available = [key for key in p.stats if p.stats[key] < C.stat_cap(p, key) - .3]
                    if available and p.tp >= R.TRAIN_COST:
                        stat = min(available, key=p.stats.get)
                        response = client.post('/rookie/train/', dict(stat=stat, times=1),
                                               HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value,
                                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                        self.assertEqual(response.status_code, 200, (day, p.age, p.league, response.content[:300]))
                        self.assertTrue(response.json()['ok'])
            self.assertIsNotNone(p.retired_at, (p.age, p.league, p.pending))
            self.assertTrue({'little', 'ms', 'hs'}.issubset(leagues), leagues)
            self.assertTrue(any(W.is_pro(lg) for lg in leagues), leagues)
            self.assertGreater(p.season_stats.count(), 1)
            for url in (f'/rookie/p/{p.pk}/', f'/rookie/p/{p.pk}/card/',
                        '/rookie/league/', '/rookie/records/', '/rookie/awards/'):
                self.assertEqual(client.get(url).status_code, 200, url)
