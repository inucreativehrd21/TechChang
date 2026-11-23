"""테크창 삼국지 DB 층·화면 검사."""
from datetime import date, datetime, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from common.models import DailyCheckIn
from community import samguk as S
from community import samguk_data as D
from community import samguk_rules as R
from community.models import (Category, Question, SamgukActivity, SamgukCodex, SamgukDay, SamgukMember, SamgukRun)

KST = timezone.get_default_timezone()


def verified(name, **extra):
    u = User.objects.create_user(name, password='pw', **extra)
    u.profile.is_email_verified = True
    u.profile.save()
    return u


def at(y, m, d, h, mi=0):
    return timezone.make_aware(datetime(y, m, d, h, mi), KST)


@override_settings(SAMGUK_ENABLED=True, GAME_CONTROLS_USE_DB=False, SAMGUK_BALANCE_STARTS=False)
class SamgukTests(TestCase):
    def setUp(self):
        cache.clear()                                           # 보안 미들웨어의 분당 요청 수 집계를 비운다
        self.user = verified('sg1')
        self.other = verified('sg2')

    # ── 게임일 ──
    def test_game_day_turns_at_six(self):
        self.assertEqual(S.game_day(at(2026, 11, 20, 5, 59)), date(2026, 11, 19))
        self.assertEqual(S.game_day(at(2026, 11, 20, 6, 0)), date(2026, 11, 20))

    # ── 세력 ──
    def test_faction_lock_seven_days(self):
        S.set_faction(self.user, 'wei')
        with self.assertRaises(S.GameError):
            S.set_faction(self.user, 'shu')
        m = SamgukMember.objects.get(user=self.user)
        m.faction_since = S.game_day() - timedelta(days=7)
        m.save()
        S.set_faction(self.user, 'shu')
        self.assertEqual(SamgukMember.objects.get(user=self.user).faction, 'shu')

    # ── 판 ──
    def _start(self, user=None):
        user = user or self.user
        S.set_faction(user, 'wei')
        return S.start(user, 0)

    def test_one_run_per_day(self):
        self._start()
        with self.assertRaises(S.GameError):
            S.start(self.user, 1)

    def test_act_and_seq_guard(self):
        run = self._start()
        city = run.state['start']
        run, res = S.act(self.user, {'kind': 'develop', 'city': city}, seq=0)
        self.assertEqual(run.ap_spent, 1)
        with self.assertRaises(S.GameError):                    # 같은 화면에서 두 번 누름
            S.act(self.user, {'kind': 'develop', 'city': city}, seq=0)
        self.assertEqual(run.actions.count(), 1)

    def test_rule_error_spends_nothing(self):
        self._start()
        with self.assertRaises(S.GameError):
            S.act(self.user, {'kind': 'develop', 'city': 'nowhere'})
        self.assertEqual(SamgukRun.objects.get(user=self.user).ap_spent, 0)

    def test_codex_seen_on_start(self):
        run = self._start()
        seen = set(SamgukCodex.objects.filter(user=self.user).values_list('general', flat=True))
        self.assertTrue(set(run.state['cities'][run.state['start']]['officers']) <= seen)

    # ── 추가 군령 ──
    def test_bonus_before_and_after_start(self):
        day = S.game_day()
        S.credit(self.user, 'column', ref='1', day=day)
        S.credit(self.user, 'column', ref='1', day=day)          # 같은 칼럼은 한 번
        run = self._start()
        self.assertEqual(run.state['ap_bonus'], 1)
        S.credit(self.user, 'column', ref='2', day=day)
        S.credit(self.user, 'column', ref='3', day=day)          # 칼럼은 하루 2편까지
        S.credit(self.user, 'comment', ref='c1', day=day)
        DailyCheckIn.objects.create(user=self.user)               # 신호 → 출석
        run.refresh_from_db()
        expected = min(R.AP_BONUS_MAX, 1 * 2 + 1 + (2 if DailyCheckIn.objects.get(user=self.user).check_in_date == day else 0))
        self.assertEqual(run.state['ap_bonus'], expected)
        self.assertLessEqual(run.state['ap_bonus'], R.AP_BONUS_MAX)

    def test_column_read_credits(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        with mock.patch('office.signals.transaction.on_commit'):
            q = Question.objects.create(author=bot, category=Category.objects.create(name='HRD'), subject='칼럼',
                                        content='본문 ' * 50, create_date=timezone.now())
        self.client.force_login(self.user)
        self.client.get(reverse('community:detail', args=[q.pk]))
        self.assertTrue(SamgukActivity.objects.filter(user=self.user, source='column', ref=str(q.pk)).exists())

    # ── 마감 ──
    def test_close_day_ranks_and_titles(self):
        a = self._start(self.user)
        b = self._start(self.other)
        SamgukRun.objects.filter(pk=a.pk).update(score=0)
        S.act(self.other, {'kind': 'develop', 'city': b.state['start']})
        day = a.day.date
        with mock.patch.object(R, 'score', side_effect=lambda st: {'total': 100 if st['ap_spent'] else 10}):
            S.close_day(day)
        d = SamgukDay.objects.get(date=day)
        self.assertEqual(d.status, 'closed')
        self.assertEqual(d.winner, self.other)
        self.assertEqual(SamgukRun.objects.get(pk=b.pk).rank, 1)
        m = SamgukMember.objects.get(user=self.other)
        self.assertEqual(m.wins, 1)
        self.assertIn(f'{day.month}월 {day.day}일의 천하인', m.titles)
        self.assertIn('wei', d.faction_scores)
        with self.assertRaises(S.GameError):
            S.act(self.other, {'kind': 'develop', 'city': b.state['start']})

    def test_yesterday_winner_becomes_boss(self):
        run = self._start()
        day = run.day.date
        S.close_day(day)
        with mock.patch.object(S, 'game_day', return_value=day + timedelta(days=1)):
            tomorrow = S.get_day()
        self.assertIn('boss', tomorrow.board['lords'])

    # ── 화면 ──
    def test_pages_flow(self):
        self.client.force_login(self.user)
        url = reverse('community:samguk_home')
        self.assertContains(self.client.get(url), '세력을 골라 주세요')
        self.client.post(reverse('community:samguk_faction'), {'faction': 'shu'})
        self.assertContains(self.client.get(url), '튜토리얼로 한 판 연습해 볼까요?')
        self.client.post(reverse('community:samguk_tutorial_choice'), {'choice': 'skip'})
        self.assertContains(self.client.get(url), '시작 도시를 골라 주세요')
        self.client.post(reverse('community:samguk_start'), {'start': '0'})
        run = SamgukRun.objects.get(user=self.user)
        self.client.post(reverse('community:samguk_act'),
                         {'seq': '0', 'kind': 'develop', 'city': run.state['start']})
        run.refresh_from_db()
        self.assertEqual(run.ap_spent, 1)
        self.assertContains(self.client.get(url), 'sg-board')
        self.assertEqual(self.client.get(reverse('community:samguk_ranking')).status_code, 200)

    def test_tutorial_leaves_no_records(self):
        self.client.force_login(self.user)
        S.set_faction(self.user, 'wei')
        self.client.post(reverse('community:samguk_tutorial_choice'), {'choice': 'do'})
        self.assertContains(self.client.get(reverse('community:samguk_tutorial')), '튜토리얼')
        for _ in range(6):
            self.client.post(reverse('community:samguk_tutorial_act'), {'kind': 'develop', 'city': 'xuchang'})
        self.client.get(reverse('community:samguk_tutorial'))
        self.assertEqual(SamgukRun.objects.count(), 0)
        self.assertEqual(SamgukCodex.objects.count(), 0)
        self.assertEqual(SamgukMember.objects.get(user=self.user).tutorial, 'done')

    def test_guest_can_open_tutorial(self):
        self.assertContains(self.client.get(reverse('community:samguk_home')), '튜토리얼로 해 보기')
        self.assertEqual(self.client.get(reverse('community:samguk_tutorial')).status_code, 200)

    def test_server_duel_result_is_displayed(self):
        run = self._start()
        S.set_tutorial(self.user, 'skipped')
        st = run.state
        src = st['start']
        dst = D.CITY[src].links[0]
        for city in st['cities'].values():
            city['officers'] = [code for code in city['officers'] if code not in ('guanyu', 'liru')]
        st['cities'][src].update(officers=['guanyu'], troops=10000)
        st['cities'][dst].update(owner=R.YELLOW, officers=['liru'], troops=100, wall=0)
        st['food'] = 5000
        SamgukRun.objects.filter(pk=run.pk).update(state=st)
        _, result = S.act(self.user, {'kind': 'attack', 'from': src, 'to': dst,
                                     'officers': ['guanyu'], 'troops': 5000}, seq=0)
        self.assertEqual(result['duel'], {'att': 'guanyu', 'def': 'liru', 'winner': 'guanyu'})
        self.client.force_login(self.user)
        response = self.client.get(reverse('community:samguk_home'))
        self.assertContains(response, 'class="sg-duel"')
        self.assertContains(response, '승자')

    def test_nested_mobile_pages_use_mobile_base(self):
        agent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile'
        for page in ['samguk_home', 'samguk_tutorial', 'samguk_ranking']:
            response = self.client.get(reverse('community:' + page), HTTP_USER_AGENT=agent)
            self.assertTemplateUsed(response, 'base_mobile.html')
            self.assertTemplateNotUsed(response, 'base.html')
        self.client.cookies['force_version'] = 'mobile'
        response = self.client.get(reverse('community:samguk_home'), HTTP_USER_AGENT='Mozilla/5.0 Desktop')
        self.assertTemplateUsed(response, 'base_mobile.html')

    def test_replay_only_after_close(self):
        run = self._start()
        day = run.day.date.isoformat()
        self.assertEqual(self.client.get(reverse('community:samguk_replay', args=[day])).status_code, 404)
        S.close_day(run.day.date)
        self.assertEqual(self.client.get(reverse('community:samguk_replay', args=[day])).status_code, 200)
        mobile = self.client.get(reverse('community:samguk_replay', args=[day]), HTTP_USER_AGENT='iPhone Mobile')
        self.assertTemplateUsed(mobile, 'base_mobile.html')


@override_settings(SAMGUK_ENABLED=False, GAME_CONTROLS_USE_DB=False)
class SamgukLockedTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_hidden_until_public(self):
        self.assertEqual(self.client.get(reverse('community:samguk_home')).status_code, 404)
        staff = verified('ops', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('community:samguk_home')).status_code, 200)

    def test_no_credit_until_public(self):
        u = User.objects.create_user('u', password='pw')
        self.assertEqual(S.credit(u, 'column', ref='1'), 0)
        self.assertFalse(SamgukActivity.objects.exists())


@override_settings(SAMGUK_ENABLED=True, GAME_CONTROLS_USE_DB=False, SAMGUK_BALANCE_STARTS=False)
class SamgukManorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = verified('inn1')
        self.client.force_login(self.user)

    def test_inn_one_guest_per_day(self):
        from community import samguk_manor as M
        inn = M.inn_today(self.user)
        self.assertEqual(len(inn.offers), M.INN_GUESTS - (1 if inn.traveler_rumor else 0))   # 나그네가 한 자리
        self.assertTrue(all(D.GENERAL[c].tier <= 3 for c in inn.offers))
        res = M.inn_pick(self.user, inn.offers[0])
        self.assertFalse(res['reunion'])
        row = SamgukCodex.objects.get(user=self.user, general=inn.offers[0])
        self.assertIsNotNone(row.first_recruited)
        with self.assertRaises(S.GameError):
            M.inn_pick(self.user, inn.offers[1])

    def test_inn_reunion_gives_fame(self):
        from community import samguk_manor as M
        inn = M.inn_today(self.user)
        SamgukCodex.objects.create(user=self.user, general=inn.offers[0], first_seen=S.game_day(),
                                   first_recruited=S.game_day(), times_recruited=1)
        res = M.inn_pick(self.user, inn.offers[0])
        self.assertTrue(res['reunion'])
        self.assertEqual(SamgukMember.objects.get(user=self.user).fame, M.REUNION_FAME)

    def test_added_women_can_be_recruited_and_displayed(self):
        from community import samguk_manor as M
        codes = ['daqiao', 'xiaoqiao', 'zhenji']
        inn = M.inn_today(self.user)
        for code in codes:
            inn.offers, inn.picked = codes, ''
            inn.save(update_fields=['offers', 'picked'])
            result = M.inn_pick(self.user, code)
            self.assertFalse(result['reunion'])
            M.place(self.user, 'front1', code)
            self.assertEqual(M.manor_view(self.user)['placed'][0]['officer']['code'], code)
        items = {i['code']: i for group in M.codex_view(self.user)['groups'] for i in group['items']}
        for code in codes:
            self.assertEqual(items[code]['state'], 'recruited')
            self.assertEqual(items[code]['name'], D.GENERAL[code].name)
            self.assertIsNotNone(items[code]['detail'])

    def test_codex_states(self):
        from community import samguk_manor as M
        SamgukCodex.objects.create(user=self.user, general='caocao', first_seen=S.game_day())
        SamgukCodex.objects.create(user=self.user, general='liubei', first_seen=S.game_day(),
                                   first_recruited=S.game_day(), times_recruited=1)
        v = M.codex_view(self.user)
        items = {i['code']: i for g in v['groups'] for i in g['items']}
        self.assertEqual(items['caocao']['state'], 'seen')
        self.assertIsNone(items['caocao']['detail'])
        self.assertEqual(items['liubei']['state'], 'recruited')
        self.assertEqual(items['sunquan']['name'], '???')
        self.assertEqual((v['seen'], v['got']), (2, 1))

    def test_pages_pc_and_mobile(self):
        for name in ('community:samguk_codex', 'community:samguk_inn'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
            r = self.client.get(reverse(name), HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile')
            self.assertContains(r, 'PC에서 이용해 주세요')
            self.assertTemplateUsed(r, 'base_mobile.html')


@override_settings(SAMGUK_ENABLED=True, GAME_CONTROLS_USE_DB=False, SAMGUK_BALANCE_STARTS=False)
class SamgukSocialTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a = verified('soc_a')
        self.b = verified('soc_b')

    def test_guestbook_rules_and_fame(self):
        from community import samguk_social as SO
        with self.assertRaises(S.GameError):
            SO.guestbook_write(self.a, self.a, '내 장원')
        with self.assertRaises(S.GameError):
            SO.guestbook_write(self.b, self.a, '여기로 오세요 https://spam.example')
        with self.assertRaises(S.GameError):
            SO.guestbook_write(self.b, self.a, '가' * 101)
        fame = SO.guestbook_write(self.b, self.a, '반가워요!')
        self.assertEqual(fame, {'author': 1, 'owner': 1})
        with self.assertRaises(S.GameError):                        # 같은 장원 하루 1개
            SO.guestbook_write(self.b, self.a, '또 왔어요')
        self.assertEqual(SamgukMember.objects.get(user=self.a).fame, 1)
        self.assertEqual(SamgukMember.objects.get(user=self.b).fame, 1)

    def test_guestbook_write_cap(self):
        from community import samguk_social as SO
        owners = [verified(f'own{i}') for i in range(SO.GB_WRITE_CAP + 1)]
        for o in owners:
            SO.guestbook_write(o, self.a, '안녕하세요')
        self.assertEqual(SamgukMember.objects.get(user=self.a).fame, SO.GB_WRITE_CAP)

    def test_friend_flow_and_block(self):
        from community import samguk_social as SO
        self.assertEqual(SO.friend_request(self.a, self.b), 'pending_out')
        self.assertEqual(SO.relation(self.b, self.a), 'pending_in')
        SO.friend_accept(self.b, self.a)
        self.assertEqual(SO.relation(self.a, self.b), 'friend')
        self.assertEqual(SO.relation(self.b, self.a), 'friend')
        SO.block(self.b, self.a)
        self.assertEqual(SO.relation(self.a, self.b), 'blocked_by')
        with self.assertRaises(S.GameError):
            SO.guestbook_write(self.b, self.a, '안녕')
        with self.assertRaises(S.GameError):
            SO.friend_request(self.a, self.b)
        SO.unblock(self.b, self.a)
        self.assertEqual(SO.relation(self.a, self.b), 'none')

    def test_mutual_request_becomes_friends(self):
        from community import samguk_social as SO
        SO.friend_request(self.a, self.b)
        self.assertEqual(SO.friend_request(self.b, self.a), 'friend')

    def test_manor_upgrade_and_place(self):
        from community import samguk_manor as M
        with self.assertRaises(S.GameError):
            M.upgrade(self.a, 'main')                                # 명성 없음
        S.member(self.a)
        SamgukMember.objects.filter(user=self.a).update(fame=500)
        with self.assertRaises(S.GameError):
            M.upgrade(self.a, 'inn')                                 # 본채보다 높게 못 올림
        M.upgrade(self.a, 'main')
        M.upgrade(self.a, 'pavilion')
        st = M.manor_state(SamgukMember.objects.get(user=self.a))
        self.assertIn('pavilion1', M.open_slots(st))
        with self.assertRaises(S.GameError):
            M.place(self.a, 'front1', 'caocao')                      # 도감에 없는 장수
        SamgukCodex.objects.create(user=self.a, general='caocao', first_seen=S.game_day(), first_recruited=S.game_day())
        M.place(self.a, 'front1', 'caocao')
        M.place(self.a, 'front2', 'caocao')                          # 같은 장수는 한 자리에만
        placed = SamgukMember.objects.get(user=self.a).manor['placed']
        self.assertEqual(placed, {'front2': 'caocao'})

    def test_fame_on_close(self):
        S.set_faction(self.a, 'wei')
        run = S.start(self.a, 0)
        S.close_day(run.day.date)
        from community import samguk_manor as M
        self.assertEqual(SamgukMember.objects.get(user=self.a).fame, M.FAME_FINISH + M.FAME_WIN)

    def test_beggar_never_tells_today(self):
        from community import samguk_manor as M
        S.set_faction(self.b, 'wei')
        S.start(self.b, 0)                                           # 오늘 진행 중인 판
        texts = [M.beggar_talk(self.a)['text'] for _ in range(M.BEGGAR_LINES)]
        name = S.display_name(self.b)
        self.assertFalse(any(name in t for t in texts))
        with self.assertRaises(S.GameError):
            M.beggar_talk(self.a)

    def test_beggar_tells_yesterday_and_respects_hide(self):
        from community import samguk_manor as M
        S.set_faction(self.b, 'wei')
        run = S.start(self.b, 0)
        S.close_day(run.day.date)
        with mock.patch.object(S, 'game_day', return_value=run.day.date + timedelta(days=1)):
            text = M.beggar_talk(self.a)['text']
            self.assertIn(S.display_name(self.b), text)
            SamgukMember.objects.filter(user=self.b).update(hide_from_beggar=True)
            SamgukMember.objects.filter(user=self.a).update(beggar={})
            text = M.beggar_talk(self.a)['text']
            self.assertNotIn(S.display_name(self.b), text)

    def test_manor_pages(self):
        self.client.force_login(self.a)
        self.assertContains(self.client.get(reverse('community:samguk_manor')), '의 장원')
        r = self.client.get(reverse('community:samguk_manor_of', args=[self.b.pk]))
        self.assertContains(r, '친구 신청')
        self.client.post(reverse('community:samguk_manor_post'),
                         {'what': 'guestbook', 'user': self.b.pk, 'text': '들렀다 가요'})
        self.assertTrue(self.b.samguk_guestbook.filter(text='들렀다 가요').exists())
        r = self.client.get(reverse('community:samguk_manor'),
                            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14) Mobile')
        self.assertContains(r, 'PC에서 이용해 주세요')

    def test_withdraw_removes_samguk_rows(self):
        """탈퇴는 계정을 지우지 않고 익명화한다(common.services.account) — 삼국지 기록은 직접 파기해야 한다."""
        from common.services.account import withdraw
        from community import samguk_social as SO
        from community.models import SamgukFriend, SamgukGuestbook
        SO.friend_request(self.a, self.b)
        SO.guestbook_write(self.b, self.a, '안녕')
        SO.guestbook_write(self.a, self.b, '반가워')
        S.set_faction(self.a, 'wei')
        run = S.start(self.a, 0)
        S.close_day(run.day.date)
        withdraw(self.a)
        self.assertFalse(SamgukFriend.objects.exists())
        self.assertFalse(SamgukGuestbook.objects.exists())
        self.assertFalse(SamgukRun.objects.filter(user=self.a).exists())
        self.assertFalse(SamgukCodex.objects.filter(user=self.a).exists())
        self.assertFalse(SamgukMember.objects.filter(user=self.a).exists())
        self.assertIsNone(SamgukDay.objects.get(pk=run.day.pk).winner)


class SamgukBalanceTests(TestCase):
    def test_compensation_is_stored_and_applied(self):
        from community import samguk_balance as BAL
        from community import samguk_board as B
        board = BAL.compensate(B.generate(date(2026, 11, 23)))
        self.assertEqual(len(board['start_estimate']), 3)
        for i, opt in enumerate(board['starts']):
            st = R.new_run(board, 'wei', i, seed=1)
            extra = opt.get('bonus') or {}
            self.assertEqual(st['cities'][opt['city']]['troops'], R.START_TROOPS + extra.get('troops', 0))


@override_settings(SAMGUK_ENABLED=True, GAME_CONTROLS_USE_DB=False, SAMGUK_BALANCE_STARTS=False)
class SamgukLegendTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = verified('leg1')
        S.set_faction(self.user, 'shu')

    def _run_with_event(self, event='nanman'):
        """오늘 판에 event 를 시작 도시 옆에 억지로 올린다(판 생성 순환과 무관하게 시험)."""
        day = S.get_day()
        start = day.board['starts'][0]['city']
        near = next(iter(D.CITY[start].links))
        day.board['legends'] = [{'event': event, 'city': near}]
        day.save(update_fields=['board'])
        run = S.start(self.user, 0)
        return run, near

    def test_event_step_once_per_day(self):
        from community import samguk_legends as L
        from community.models import SamgukLegend
        run, city = self._run_with_event('nanman')
        st = run.state
        strong = 'zhangfei'
        st['cities'][st['start']]['officers'].append(strong)        # 무력 75 이상 장수를 곁에 둔다
        SamgukRun.objects.filter(pk=run.pk).update(state=st)
        weak = next(o for o in st['cities'][st['start']]['officers'] if D.GENERAL[o].war < 75)
        self.client.force_login(self.user)
        S.set_tutorial(self.user, 'skipped')
        home = reverse('community:samguk_home')
        post = reverse('community:samguk_act')
        self.assertNotContains(self.client.get(home), 'data-event="nanman"')
        with self.assertRaises(S.GameError):
            S.act(self.user, {'kind': 'legend', 'series': 'menghuo', 'city': city, 'by': strong})
        _, discovery = S.act(self.user, {'kind': 'scout', 'city': city})
        self.assertEqual(discovery['discoveries'], [D.CITY[city].name])
        self.assertContains(self.client.get(home), 'data-event="nanman"')
        self.assertContains(self.client.get(home), L.SERIES['menghuo']['rumors'][0])
        with self.assertRaises(S.GameError):
            S.act(self.user, {'kind': 'legend', 'series': 'menghuo', 'city': city, 'by': weak})
        self.client.post(post, {'kind': 'legend', 'series': 'menghuo', 'city': city, 'by': strong, 'seq': 1})
        run.refresh_from_db()
        res = run.actions.get(seq=1).result
        self.assertEqual(res['kind'], 'legend')
        self.assertEqual(run.score, R.score(run.state)['total'])
        row = SamgukLegend.objects.get(user=self.user, series='menghuo')
        self.assertEqual(row.progress['count'], 1)
        with self.assertRaises(S.GameError):                         # 하루 한 걸음
            S.act(self.user, {'kind': 'legend', 'series': 'menghuo', 'city': city, 'by': strong})

    def test_attempt_needs_completion_and_fame(self):
        from community import samguk_legends as L
        from community.models import SamgukLegend
        with self.assertRaises(S.GameError):
            L.attempt(self.user, 'menghuo')
        SamgukLegend.objects.create(user=self.user, series='menghuo', step=1, completed_at=S.game_day())
        with self.assertRaises(S.GameError):
            L.attempt(self.user, 'menghuo')                          # 명성 부족
        SamgukMember.objects.filter(user=self.user).update(fame=50)
        L.attempt(self.user, 'menghuo')
        self.assertTrue(SamgukCodex.objects.filter(user=self.user, general='menghuo',
                                                   first_recruited__isnull=False).exists())

    def test_two_loyal_retainers_granted_together(self):
        from community import samguk_legends as L
        from community.models import SamgukLegend
        SamgukLegend.objects.create(user=self.user, series='milu', step=3, completed_at=S.game_day())
        SamgukMember.objects.filter(user=self.user).update(fame=100)
        L.attempt(self.user, 'milu')
        got = set(SamgukCodex.objects.filter(user=self.user, first_recruited__isnull=False).values_list('general', flat=True))
        self.assertTrue({'milu', 'yuyu'} <= got)

    def test_hidden_general_can_be_displayed_in_manor(self):
        from community import samguk_manor as M
        SamgukCodex.objects.create(user=self.user, general='huangyueying', first_seen=S.game_day(),
                                   first_recruited=S.game_day())
        M.place(self.user, 'front1', 'huangyueying')
        self.assertEqual(M.manor_view(self.user)['placed'][0]['officer']['name'], '황월영')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('community:samguk_manor')), '황월영')

    def test_counter_step_counts_at_close(self):
        from community.models import SamgukLegend
        SamgukLegend.objects.create(user=self.user, series='goi', step=0)
        run = S.start(self.user, 0)
        for i in range(3):
            run, _ = S.act(self.user, {'kind': 'develop', 'city': run.state['start']})
        S.close_day(run.day.date)
        row = SamgukLegend.objects.get(user=self.user, series='goi')
        self.assertEqual(row.progress['count'], 1)                   # 서로 다른 세 날 중 하루
        S.close_day(run.day.date)                                    # 두 번 닫아도 한 번만 센다
        self.assertEqual(SamgukLegend.objects.get(pk=row.pk).progress['count'], 1)

    def test_rumors_progress_and_prophecy(self):
        from community import samguk_legends as L
        from community.models import SamgukRumor
        texts = [L.rumor_for(self.user) for _ in range(5)]
        self.assertTrue(all(texts))
        self.assertEqual(SamgukRumor.objects.filter(user=self.user).count(), 5)
        for _ in range(sum(len(v['rumors']) for v in L.SERIES.values())):
            L.rumor_for(self.user)
        last = SamgukRumor.objects.get(user=self.user, series='guanlu', level=5)
        self.assertIn(D.CITY[L._prophecy(self.user)].name, last.text)
        self.assertIsNone(L.rumor_for(self.user))                    # 다 들으면 더 없다

    def test_codex_hidden_slots(self):
        from community import samguk_manor as M
        v = M.codex_view(self.user)
        labels = {g['label']: g for g in v['hidden']}
        self.assertEqual(labels['외전']['total'], 8)
        self.assertEqual(labels['기연']['total'], 19)
        self.assertEqual(labels['기연']['got'], 0)

    def test_no_korea_invaders_and_hidden_not_on_board(self):
        from community import samguk_board as B
        from community import samguk_legends as L
        for banned in ('toyotomi', 'hideyoshi', 'kato', 'konishi'):
            self.assertFalse(any(banned in c for c in L.HIDDEN))
        board = B.generate(date(2026, 11, 25))
        placed = {o for v in board['cities'].values() for o in v['officers']}
        self.assertFalse(placed & set(L.HIDDEN))

    def test_board_events_exist_over_week(self):
        from community import samguk_board as B
        seen = set()
        for i in range(14):
            seen.update(e['event'] for e in B.generate(B.EPOCH + timedelta(days=i))['legends'])
        self.assertTrue({'nanman', 'rift'} <= seen)


class SamgukGameCenterTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(SAMGUK_ENABLED=True, GAME_CONTROLS_USE_DB=False)
    def test_game_center_lists_samguk_when_public(self):
        r = self.client.get(reverse('community:games_index'))
        self.assertContains(r, '테크창 삼국지')
        self.assertContains(r, reverse('community:samguk_tutorial'))
        self.assertContains(r, f'장수 {len(D.GENERALS)}명 도감')
        self.assertEqual(SamgukDay.objects.count(), 0)                # 게임센터는 판을 만들지 않는다(판 생성은 몇 초)

    @override_settings(SAMGUK_ENABLED=False, GAME_CONTROLS_USE_DB=False)
    def test_game_center_hides_samguk_before_launch(self):
        self.assertNotContains(self.client.get(reverse('community:games_index')), '테크창 삼국지')
