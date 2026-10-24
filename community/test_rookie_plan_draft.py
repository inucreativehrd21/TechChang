import random
from django.core.cache import cache
from django.test import Client, TestCase
from community import rookie_lite as X
from community.models import LiteCareer
from community.test_rookie_lite import member, PC, MOBILE
from community.views.rookie_lite_views import _plan_key


class PlanDraftTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = member('draft-player')
        self.client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=PC)
        self.client.force_login(self.user)
        self.c = X.create(self.user, name='선택검사', role='batter', position='SS', style='contact',
                          region='서울', team='lg', rng=random.Random(42))
        self.c.league = 'kbo1'
        self.c.club = 'lg'
        self.c.flags = dict(self.c.flags, cash=100000)
        event = next(iter(X.EVENTS))
        self.intl = next(iter(X.INTL))
        self.c.pending = {'kind': 'plan', 'event': event, 'intl': [self.intl]}
        self.c.save()
        self.choice = X.EVENTS[event]['choices'][0][0]
        self.programs = X.pick_programs(self.c, random.Random(99))

    def buy(self, data):
        self.client.get('/rookie/lite/')
        return self.client.post('/rookie/lite/act/', data, follow=True,
                                HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_purchase_keeps_unsubmitted_event_training_and_intensity_on_both_layouts(self):
        for ua in (PC, MOBILE):
            self.client.defaults['HTTP_USER_AGENT'] = ua
            result = self.buy({'action': 'buyplan', '_draft_key': _plan_key(self.c),
                               '_draft_program': self.programs, '_draft_intensity': 'normal',
                               '_draft_event_choice': self.choice, '_draft_intl_' + self.intl: 'go'})
            self.assertEqual(result.status_code, 200)
            self.c.refresh_from_db()
            self.assertEqual(self.c.pending['draft']['programs'], self.programs)
            self.assertEqual(self.c.pending['draft']['event_choice'], self.choice)
            self.assertEqual(self.c.pending['draft']['intl'][self.intl], 'go')
            self.assertContains(result, 'data-rl-flow')
            self.assertContains(result, 'rookie-flow.js')
            self.assertEqual(result.context['draft_programs'], self.programs)
            self.assertEqual(self.c.pending['kind'], 'plan')
            self.assertEqual(self.c.seasons.count(), 0)

    def test_another_seasons_draft_cannot_buy_or_replace_current_draft(self):
        before = self.c.flags.copy()
        self.buy({'action': 'buy', 'item': 'house', 'code': 'rent', '_draft_key': 'old-season',
                  '_draft_program': self.programs})
        self.c.refresh_from_db()
        self.assertEqual(self.c.flags, before)
        self.assertNotIn('draft', self.c.pending)

    def test_purchase_without_js_does_not_clear_existing_draft(self):
        self.c.pending['draft'] = {'programs': self.programs, 'event_choice': self.choice}
        self.c.save()
        self.buy({'action': 'buyplan'})
        self.c.refresh_from_db()
        self.assertEqual(self.c.pending['draft']['event_choice'], self.choice)

    def test_actual_item_purchase_spends_cash_and_retains_choices(self):
        self.buy({'action': 'buy', 'item': 'bat', 'code': 'pro', '_draft_key': _plan_key(self.c),
                  '_draft_program': self.programs, '_draft_event_choice': self.choice})
        self.c.refresh_from_db()
        self.assertLess(X.cash(self.c), 100000)
        self.assertEqual(self.c.flags['gear']['bat'], 'pro')
        self.assertEqual(self.c.pending['draft']['programs'], self.programs)

    def test_arbitrary_draft_values_are_filtered_and_do_not_advance(self):
        self.buy({'action': 'buyplan', '_draft_key': _plan_key(self.c), '_draft_program': ['secret', 'bad'],
                  '_draft_event_choice': 'bad', '_draft_intensity': 'infinite'})
        self.c.refresh_from_db()
        self.assertEqual(self.c.pending['draft']['programs'], [])
        self.assertEqual(self.c.pending['draft']['event_choice'], '')
        self.assertEqual(self.c.pending['draft']['intensity'], 'normal')
