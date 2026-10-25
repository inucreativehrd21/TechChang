"""투타 호환성·실제 승부 효과·만개 수명·추가 각성 1회·요청 재전송을 검증해요."""
from copy import deepcopy
import random
from unittest import mock
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, Client, override_settings
from community import rookie_lite as X, rookie_bloom as B, rookie_handedness as H
from community import rookie_sim as M, rookie_extreme as E, rookie_modes as Modes, rookie as R
from community.models import LiteCareer, LiteSeason
from community.test_rookie_lite import new, member, PC, MOBILE

DULL = {'pa': 400, 'ab': 360, 'h': 80, 'd': 12, 'hr': 4, 'bb': 30, 'so': 90, 'hbp': 2, 'sf': 3}       # 평범한 시즌
GREAT = {'pa': 600, 'ab': 520, 'h': 185, 'd': 38, 'hr': 38, 'bb': 70, 'so': 80, 'hbp': 4, 'sf': 5}    # 눈에 띄는 시즌


def seasons(c, leagues, totals=DULL):
    for i, lg in enumerate(leagues):
        LiteSeason.objects.create(career=c, year=c.year - len(leagues) + i, age=c.age - len(leagues) + i, league=lg,
                                  club=c.club, games=144, totals=dict(totals))


def veteran(name='만개검사', history=('kbo2', 'kbo2')):
    c=new(name)
    c.age,c.year,c.league,c.club,c.grade=32,17,'kbo2','lg',0
    c.potential,c.traits,c.traits_seen=70,[],[]
    c.flags=dict(c.flags,pro_years=12,served=True)
    c.stats={k:round(X.stat_pot(c,k)-1,1) for k in c.stats}
    c.ovr=c.best_ovr=R.overall(c.role,c.stats)
    c.save()
    seasons(c, history)                       # 만개 조건 — 오래 빛을 못 봤다(기본: 퓨처스 2시즌 적재)
    c.pending=B.offer(c) or c.pending
    c.save()
    return c

class HandsTests(TestCase):
    def test_legacy_rows_are_right_right_without_writing_json(self):
        c=new()
        c.flags.pop('hands',None)
        c.save()
        before=deepcopy(c.flags)
        self.assertEqual(c.hand_label,'우투·우타')
        self.assertEqual(H.sides(c),('R','R'))
        c.refresh_from_db()
        self.assertEqual(c.flags,before)

    @override_settings(ROOKIE_EXTREME_ENABLED=True)
    def test_all_modes_can_select_left_and_right_and_reject_invalid_values(self):
        for mode in ('lite','extreme'):
            c=X.create(member(mode+'손선택'),name='새선수',role='batter',position='SS',style='contact',
                region='서울',team='lg',mode=mode,throwing='L',batting='L',rng=random.Random(11))
            c.refresh_from_db()
            self.assertEqual(c.hand_label,'좌투·좌타')
            self.assertTrue(all(H.eligible(c,t) for t in c.traits))
        p=R.create(member('정식손선택'),name='정식선수',role='pitcher',position='SP',
                   region='서울',team='lg',throwing='L',batting='R',rng=random.Random(4))
        p.refresh_from_db()
        self.assertEqual(p.hand_label,'좌투·우타')
        with self.assertRaises(X.LiteError):
            X.create(member('잘못손'),name='잘못손',role='batter',position='SS',style='contact',
                     region='서울',team='lg',throwing='X')

    def test_new_member_http_form_saves_both_hands_with_csrf(self):
        client=Client(enforce_csrf_checks=True,HTTP_USER_AGENT=MOBILE)
        self.assertEqual(client.get('/rookie/lite/').status_code,200)
        response=client.post('/rookie/lite/new/',dict(name='좌타선수',role='batter',position_batter='SS',
            style_batter='contact',region='서울',team='lg',throwing='R',batting='L'),
            HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code,302)
        c=LiteCareer.objects.get()
        self.assertEqual(c.hand_label,'우투·좌타')
        self.assertContains(client.get('/rookie/lite/'),'우투·좌타')

    def test_secret_trait_pool_never_gives_wrong_side_or_role(self):
        c=new()
        for role in ('batter','pitcher'):
            c.role=role
            for throwing in ('L','R'):
                for batting in ('L','R'):
                    for seed in range(40):
                        c.traits,c.traits_seen=[],[]
                        H.initialize(c,throwing,batting,random.Random(seed))
                        self.assertTrue(all(H.eligible(c,t) for t in c.traits))
                        self.assertEqual(c.traits_seen,[])

    def test_handedness_draw_preserves_existing_career_event_rng(self):
        c=new()
        rng=random.Random(12)
        before=rng.getstate()
        H.initialize(c,'L','L',rng)
        self.assertEqual(rng.getstate(),before)

class PlatoonTests(SimpleTestCase):
    def test_traits_change_only_the_matching_opponent(self):
        b=dict.fromkeys(M.BAT,64)
        p=dict.fromkeys(M.PIT,64)
        p.update(_throwing='R',_hand_traits=['left_slayer'])
        left=dict(b,_batting='L')
        right=dict(b,_batting='R')
        base=dict(p,_hand_traits=[])
        self.assertGreater(M.pa_probs(left,p)['SO'],M.pa_probs(left,base)['SO'])
        self.assertEqual(M.pa_probs(right,p),M.pa_probs(right,base))
        slugger=dict(b,_batting='R',_hand_traits=['right_slugger'])
        self.assertGreater(M.pa_probs(slugger,base)['HR'],M.pa_probs(dict(b,_batting='R'),base)['HR'])
        self.assertEqual(b,dict.fromkeys(M.BAT,64))

    def test_bare_stats_keep_original_calibration_and_probabilities_sum_to_one(self):
        b,p=dict.fromkeys(M.BAT,64),dict.fromkeys(M.PIT,64)
        before=M.pa_probs(b,p)
        for bs in ('L','R'):
            for ps in ('L','R'):
                probs=M.pa_probs(dict(b,_batting=bs),dict(p,_throwing=ps))
                self.assertAlmostEqual(sum(probs.values()),1)
                self.assertTrue(all(0 <= x <= 1 for x in probs.values()))
        self.assertEqual(M.pa_probs(b,p),before)

class BloomTests(TestCase):
    def setUp(self):
        cache.clear()
        appear = mock.patch.object(B, 'APPEAR', 1.0)          # 조건 검사 — 제안이 뜨는 확률은 따로 잰다
        appear.start()
        self.addCleanup(appear.stop)
        self.c=veteran()

    def win(self):
        X.decide(self.c,'bloom','try',random.Random(1))
        self.c.save()
        self.assertTrue(B.succeeded(self.c))

    def test_eligibility_only_lite_after_31_low_talent_at_limit(self):
        self.assertTrue(B.ready(self.c))
        for change in (dict(age=31),dict(mode='extreme'),dict(potential=84),dict(retired_at=mock.sentinel.retired)):
            p=deepcopy(self.c)
            for k,v in change.items():setattr(p,k,v)
            self.assertFalse(B.ready(p),change)
        fresh=veteran('만개없음',history=())                   # 기록이 없으면 '오래 빛을 못 봤다'가 아니다
        self.assertFalse(B.ready(fresh))
        p=deepcopy(self.c);p.stats=dict.fromkeys(p.stats,25)
        self.assertFalse(B.ready(p))

    def test_success_gives_exactly_four_stars_and_preserves_previous_awaken_history(self):
        self.c.potential=60
        self.c.flags['awaken']=2
        self.c.stats={k:X.stat_pot(self.c,k)-1 for k in self.c.stats}
        self.c.pending=B.offer(self.c)
        self.assertIsNotNone(self.c.pending)
        self.win()
        self.assertEqual(self.c.potential,77)
        self.assertEqual(X.base_stars(self.c)+X.awakened(self.c),4)
        self.assertEqual(self.c.flags['awaken'],2)
        self.assertTrue(B.bonus_available(self.c))
        self.assertEqual(self.c.pending['what'],'bloom_result')
        self.assertTrue(all(25<=v<=X.stat_pot(self.c,k) for k,v in self.c.stats.items()))
        self.assertIn('ledger',self.c.flags)

    def test_aging_relief_has_exact_three_seasons_and_expiry(self):
        self.win()
        for offset in (0,1,2):
            self.c.year=17+offset
            self.assertEqual(B.aging_multiplier(self.c),.30)
        self.c.year=20
        self.assertEqual(B.aging_multiplier(self.c),1)
        self.assertTrue(B.bonus_available(self.c))

    def test_actual_growth_ledger_reduces_aging_only(self):
        self.win()
        a,b=deepcopy(self.c),deepcopy(self.c)
        b.flags['bloom']['year']=b.year-3
        programs=['balance', 'contact']
        first=X.grow(a,programs,'normal',.5,1,random.Random(5))
        normal=X.grow(b,programs,'normal',.5,1,random.Random(5))
        for k in a.stats:
            aged=lambda d:sum(v for label,v in d['_why'][k] if label=='나이(노쇠)')
            self.assertAlmostEqual(aged(first),aged(normal)*.30)

    def test_failure_is_once_without_stat_loss_and_skip_keeps_attempt(self):
        before=deepcopy(self.c.stats)
        X.decide(self.c,'bloom','try',random.Random(2))
        self.assertFalse(B.succeeded(self.c))
        self.assertEqual(self.c.stats,before)
        self.assertFalse(B.ready(self.c))
        self.assertEqual(self.c.pending['what'],'bloom_result')
        self.c.flags.pop('bloom')
        self.c.pending=B.offer(self.c)
        X.decide(self.c,'bloom','skip',random.Random(1))
        self.assertFalse(B.state(self.c).get('attempted',False))
        self.assertFalse(B.ready(self.c))
        self.c.year+=1
        self.assertTrue(B.ready(self.c))

    def test_bonus_awaken_obeys_growth_gates_and_consumes_exactly_one_try(self):
        self.win()
        self.c.pending={'kind':'plan'}
        self.assertFalse(X.awaken_ready(self.c))
        self.c.stats={k:X.stat_pot(self.c,k) for k in self.c.stats}
        self.assertTrue(X.awaken_ready(self.c))
        self.c.pending=dict(kind='decision',what='awaken',odds=0)
        X.decide(self.c,'awaken','skip',random.Random(1))
        self.assertTrue(B.bonus_available(self.c))
        self.c.year+=3
        self.assertTrue(X.awaken_ready(self.c))
        self.c.pending=dict(kind='decision',what='awaken',odds=0)
        X.decide(self.c,'awaken','try',random.Random(1))
        self.assertFalse(B.bonus_available(self.c))
        self.c.year+=3
        self.assertFalse(X.awaken_ready(self.c))

    def test_bonus_success_reaches_five_and_never_repeats(self):
        self.win()
        self.c.stats={k:X.stat_pot(self.c,k) for k in self.c.stats}
        self.c.pending=dict(kind='decision',what='awaken',odds=1)
        X.decide(self.c,'awaken','try',random.Random(1))
        self.assertEqual(X.base_stars(self.c)+X.awakened(self.c),5)
        self.assertFalse(B.bonus_available(self.c))

    def test_pending_scene_precedes_release_pressure_and_very_late_success_has_three_years(self):
        self.c.pending={'kind':'review'}
        with mock.patch.object(X.Balance,'retention',return_value=1):
            self.assertEqual(X.next_step(self.c,random.Random(1))['what'],'bloom')
        self.c.age=42
        self.c.pending=B.offer(self.c)
        self.win()
        self.assertEqual(B.retirement_limit(self.c,X.RETIRE_AT),44)

    def test_csrf_and_event_id_replay_reject_double_submission(self):
        client=Client(enforce_csrf_checks=True,HTTP_USER_AGENT=PC)
        client.force_login(self.c.user)
        page=client.get('/rookie/lite/')
        self.assertContains(page,B.scene(self.c)['story']['title'])
        data=dict(action='decide',what='bloom',choice='try',event_id=self.c.pending['id'])
        self.assertEqual(client.post('/rookie/lite/act/',data).status_code,403)
        token=client.cookies['csrftoken'].value
        with mock.patch('community.views.rookie_lite_views._rng',return_value=random.Random(1)):
            client.post('/rookie/lite/act/',data,HTTP_X_CSRFTOKEN=token)
        self.c.refresh_from_db()
        self.assertTrue(B.succeeded(self.c))
        before=deepcopy(self.c.flags)
        client.post('/rookie/lite/act/',data,HTTP_X_CSRFTOKEN=token)
        self.c.refresh_from_db()
        self.assertEqual(self.c.flags,before)

@override_settings(ROOKIE_EXTREME_ENABLED=True)
class ExtremeDownsideTests(TestCase):
    def fixture(self):
        c=X.create(member('큰도전'),name='큰도전',role='batter',position='SS',style='contact',
            region='서울',team='lg',mode='extreme',rng=random.Random(10))
        c.flags['extreme']['pending']['key']='school_starter'
        c.ovr=next(r['level'] for r in c.flags['extreme']['rivals'] if r['id']=='school')
        c.save()
        return c

    def test_failure_persists_real_stat_and_training_costs_then_season_modifier_expires(self):
        c=self.fixture()
        before=deepcopy(c.stats)
        result=E.apply_choice(c,E.event_view(c)['id'],'compete',random.Random(2))
        self.assertFalse(result['success'])
        self.assertEqual(len(result['stats']),2)
        self.assertTrue(all(item['delta']==-4 for item in result['stats']))
        self.assertLess(Modes.training_multiplier(c),1)
        self.assertTrue(any(c.stats[k]<before[k] for k in before))
        self.assertLessEqual(result['trust'],-7)
        c.save()
        c.refresh_from_db()
        self.assertLess(Modes.training_multiplier(c),1)
        c.year+=1;c.age+=1;E.complete_year(c)
        self.assertEqual(Modes.training_multiplier(c),1.35)
        self.assertTrue(any(c.stats[k]<before[k] for k in before))

    def test_safe_choice_has_no_failure_draw_or_direct_stat_damage(self):
        c=self.fixture()
        before=deepcopy(c.stats)
        result=E.apply_choice(c,E.event_view(c)['id'],'team',random.Random(2))
        self.assertIsNone(result['success'])
        self.assertEqual(c.stats,before)
        self.assertEqual(result['stats'],[])

    def test_over_cap_stats_never_drop_on_success_or_lose_more_than_advertised(self):
        original=self.fixture()
        for success in (False,True):
            with self.subTest(success=success):
                c=deepcopy(original)
                c.stats={k:X.stat_pot(c,k)+10 for k in c.stats}
                c.ovr=next(r['level'] for r in c.flags['extreme']['rivals'] if r['id']=='school')
                result=E.apply_choice(c,E.event_view(c)['id'],'compete',random.Random(1 if success else 2))
                self.assertEqual(result['success'],success)
                self.assertTrue(all(row['delta']==(0 if success else -4) for row in result['stats']))

    def test_public_http_saves_failure_stats_and_shows_cost_before_choice(self):
        c=self.fixture()
        client=Client(enforce_csrf_checks=True,HTTP_USER_AGENT=PC)
        client.force_login(c.user)
        self.assertContains(client.get('/rookie/extreme/'),'능력치 2개 최대 −4')
        data=dict(action='extreme_event',choice='compete',event_id=E.event_view(c)['id'])
        token=client.cookies['csrftoken'].value
        before=deepcopy(c.stats)
        with mock.patch('community.views.rookie_lite_views._rng',return_value=random.Random(2)):
            client.post('/rookie/extreme/act/',data,HTTP_X_CSRFTOKEN=token)
        c.refresh_from_db()
        self.assertTrue(any(c.stats[k]<before[k] for k in before))
        after=deepcopy(c.stats)
        client.post('/rookie/extreme/act/',data,HTTP_X_CSRFTOKEN=token)
        c.refresh_from_db()
        self.assertEqual(c.stats,after)



class BloomGateTests(TestCase):
    """2026-10-25 — 만개는 오래 평범했거나 하위 리그에 묶였을 때만, 그것도 APPEAR 확률로."""

    def setUp(self):
        cache.clear()
        appear = mock.patch.object(B, 'APPEAR', 1.0)
        appear.start()
        self.addCleanup(appear.stop)

    def test_dull_top_league_years_qualify_but_a_great_year_does_not(self):
        dull = veteran('평범한1군', history=('kbo1', 'kbo1', 'kbo1'))
        self.assertTrue(B.overlooked(dull))
        mixed = veteran('한해반짝', history=())
        seasons(mixed, ('kbo1', 'kbo1', 'kbo1'))
        mixed.seasons.filter(year=mixed.year - 1).update(totals=GREAT)          # 가장 최근 시즌은 눈에 띄었다
        self.assertFalse(B.overlooked(mixed))
        self.assertFalse(B.ready(mixed))

    def test_buried_in_minors_qualifies_in_every_system(self):
        for lg in ('kbo2', 'mlb_aa', 'mlb_aaa', 'npb2'):
            c = veteran(f'적재{lg}', history=())
            seasons(c, (lg, lg), GREAT)                     # 성적이 좋아도 하위 리그에 묶여 있었으면
            self.assertTrue(B.overlooked(c), lg)
        one = veteran('한시즌만', history=())
        seasons(one, ('kbo1', 'kbo2'), GREAT)
        self.assertFalse(B.overlooked(one))

    def test_offer_appears_only_at_appear_rate_and_is_fixed_per_season(self):
        c = veteran('확률검사')
        self.assertTrue(B.ready(c))
        with mock.patch.object(B, 'APPEAR', .30):
            hits = 0
            for year in range(200):
                c.year = year
                hits += B.appears(c)
                self.assertEqual(B.appears(c), B.appears(c))
            self.assertTrue(40 <= hits <= 80, hits)

    def test_stale_offer_from_old_rules_does_not_block(self):
        c = veteran('예전제안', history=())
        c.pending = dict(kind='decision', what='bloom', id='old', odds=.6)
        text = X.decide(c, 'bloom', 'try', random.Random(1))
        self.assertIn('사라졌어요', text)
        self.assertNotEqual(c.pending.get('what'), 'bloom')
        self.assertFalse(B.succeeded(c))


class BloomStoryTests(TestCase):
    """2026-10-25 — 만개 안내 이야기 여러 개(로직은 같다)."""

    def setUp(self):
        cache.clear()
        appear = mock.patch.object(B, 'APPEAR', 1.0)
        appear.start()
        self.addCleanup(appear.stop)

    def test_every_story_fills_all_words_for_both_roles(self):
        from community import rookie_bloom_stories as S
        c = veteran('이야기검사')
        self.assertGreaterEqual(len(S.STORIES), 7)
        for role in ('batter', 'pitcher'):
            c.role = role
            for story in S.STORIES:
                r = S.render(c, story['key'])
                text = ' '.join([r['title'], r['try_label']] + r['intro'] + r['ok'] + r['fail'])
                self.assertNotIn('{', text, story['key'])
                self.assertEqual((len(r['intro']), len(r['ok']), len(r['fail'])), (3, 2, 2))
        c.role = 'batter'
        self.assertIn('방망이를', S.render(c, 'regret')['intro'][0])
        c.role = 'pitcher'
        self.assertIn('공을', S.render(c, 'regret')['intro'][0])

    def test_minor_only_story_and_same_story_through_result(self):
        from community import rookie_bloom_stories as S
        minor = veteran('퓨처스이야기')
        self.assertIn('bus', [s['key'] for s in S.pool(minor)])
        minor.league = 'kbo1'
        self.assertNotIn('bus', [s['key'] for s in S.pool(minor)])
        c = veteran('같은이야기')
        key = c.pending['story']
        self.assertEqual(B.scene(c)['story']['key'], key)
        self.assertEqual(B.scene(c)['title'], S.BY_KEY[key]['title'])
        X.decide(c, 'bloom', 'try', random.Random(1))
        self.assertEqual(c.pending['what'], 'bloom_result')
        self.assertEqual(B.scene(c)['story']['key'], key)

    def test_stories_spread_across_offers_and_old_pending_still_renders(self):
        from community import rookie_bloom_stories as S
        c = veteran('여러이야기')
        keys = {S.pick(c, f'seed{i}') for i in range(80)}
        self.assertGreaterEqual(len(keys), 6)
        c.pending = dict(kind='decision', what='bloom', id='oldid', odds=.6)       # story 키 없는 예전 저장
        self.assertIn(B.scene(c)['story']['key'], S.BY_KEY)


class BloomRoleStoryTests(TestCase):
    def test_role_stories_only_for_that_role_and_slot_word(self):
        from community import rookie_bloom_stories as S
        with mock.patch.object(B, 'APPEAR', 1.0):
            c = veteran('역할이야기')
        self.assertGreaterEqual(len(S.STORIES), 13)
        c.role = 'batter'
        keys = [s['key'] for s in S.pool(c)]
        self.assertIn('halfbeat', keys)
        self.assertNotIn('reinvent', keys)
        self.assertIn('4번 타자', ' '.join(S.render(c, 'trusted')['intro']))
        c.role = 'pitcher'
        keys = [s['key'] for s in S.pool(c)]
        self.assertIn('reinvent', keys)
        self.assertNotIn('halfbeat', keys)
        self.assertIn('선발 한 자리', ' '.join(S.render(c, 'trusted')['intro']))
