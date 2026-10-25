"""외형 저장 경계·실제 생성 폼·모드 분리·기존 게임 데이터 보존을 확인해요."""
from copy import deepcopy
import random
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.template.loader import render_to_string
from . import rookie_avatar as A, rookie as R, rookie_lite as X
from .models import RookiePlayer, LiteCareer
from .test_rookie_lite import member, PC, MOBILE

class AvatarRecipeTests(SimpleTestCase):
    def test_strict_allowlist_and_legacy_default(self):
        self.assertEqual(A.clean({}),dict(A.DEFAULT,v=1))
        for value in ('../../secret','01.png','99','<script>'):
            with self.assertRaises(ValueError):A.clean({'avatar_body':value})
        self.assertEqual(A.recipe(),dict(A.DEFAULT,v=1))

    def test_formal_uses_same_skin_hair_without_hat(self):
        recipe=A.clean({'avatar_body':'07','avatar_hair':'14','avatar_tone':'05','avatar_cap':'green'})
        normal=A.parts(recipe)
        formal=A.parts(recipe,True)
        self.assertIn('body-07.png',formal)
        self.assertIn('hair-14-05.png',formal)
        self.assertIn('formal.png',formal)
        self.assertNotIn('cap-green.png',formal)
        self.assertIn('cap-green.png',normal)

    @override_settings(MEDIA_ROOT='__avatar_assets_missing__')
    def test_missing_assets_have_static_accessible_fallback(self):
        html=render_to_string('community/games/_rookie_avatar.html',{'avatar':A.presentation(state='award')})
        self.assertIn('is-missing',html)
        self.assertIn('트로피를 든 선수 아바타',html)
        self.assertIn('rk-avatar-fallback',html)

@override_settings(ROOKIE_EXTREME_ENABLED=True)
class AvatarHttpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user=member('avatar-flow')
        self.client=Client(enforce_csrf_checks=True,HTTP_USER_AGENT=PC)
        self.client.force_login(self.user)
        self.chosen=dict(avatar_body='07',avatar_hair='14',avatar_tone='05',avatar_kit='away',avatar_cap='green')

    def post(self,url,data):
        cache.clear()
        self.client.get('/rookie/')
        return self.client.post(url,data,HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_full_create_persists_and_invalid_recipe_does_not_create_player(self):
        data=dict(name='외형선수',role='batter',position='SS',focus_batter='contact',region='서울',team='lg',number=17,**self.chosen)
        bad=dict(data,avatar_hair='../../x')
        self.assertEqual(self.post('/rookie/create/',bad).status_code,302)
        self.assertFalse(RookiePlayer.objects.filter(user=self.user).exists())
        self.assertEqual(self.post('/rookie/create/',data).status_code,302)
        p=RookiePlayer.objects.get(user=self.user)
        self.assertEqual(A.recipe(p),A.clean(self.chosen))
        response=self.client.get('/rookie/')
        self.assertContains(response,'body-07.png')
        self.assertContains(response,'hair-14-05.png')
        self.assertContains(response,'캐릭터 에셋:')

    def test_guest_lite_and_extreme_keep_separate_avatar_after_progress(self):
        self.client.logout()
        for mode,body in [('lite','02'),('extreme','08')]:
            cache.clear()
            self.client.get(f'/rookie/{mode}/',HTTP_USER_AGENT=MOBILE)
            data=dict(name='외형선수',role='batter',position_batter='SS',style_batter=next(iter(X.STYLES['batter'])),region='서울',team='lg',**dict(self.chosen,avatar_body=body))
            response=self.client.post(f'/rookie/{mode}/new/',data,HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
            self.assertEqual(response.status_code,302)
            c=LiteCareer.objects.get(mode=mode,guest=self.client.session[mode+'_guest'])
            before=A.recipe(c)
            rng=random.Random(17)
            if mode == 'extreme':
                from . import rookie_extreme as E
                event=E.event_view(c)
                if event:
                    E.apply_choice(c,event['id'],event['choices'][0]['key'],rng)
                    c.save()
            event=(c.pending or {}).get('event')
            choice=X.EVENTS[event]['choices'][0][0] if event else ''
            X.start_season(c,X.pick_programs(c,rng),'normal',choice,{},rng)
            c.refresh_from_db()
            self.assertEqual(A.recipe(c),before)
            self.assertEqual(before['body'],body)
        self.assertNotEqual(self.client.session['lite_guest'],self.client.session['extreme_guest'])

    def test_save_merges_latest_json_without_touching_stats_or_random(self):
        p=R.create(self.user,name='보존선수',role='batter',team='lg',region='서울')
        before=deepcopy((p.stats,p.ovr,p.potential,p.traits,p.league,p.club))
        RookiePlayer.objects.filter(pk=p.pk).update(career=dict(p.career,newer='preserved'))
        state=random.getstate()
        A.save(p,A.clean(self.chosen))
        p.refresh_from_db()
        self.assertEqual((p.stats,p.ovr,p.potential,p.traits,p.league,p.club),before)
        self.assertEqual(p.career['newer'],'preserved')
        self.assertEqual(random.getstate(),state)

    def test_old_player_default_is_deterministic_and_does_not_save(self):
        p=R.create(self.user,name='기존선수',role='batter',team='lg',region='서울')
        before=deepcopy(p.career)
        self.assertEqual(A.recipe(p),A.recipe(p))
        A.presentation(p,state='award')
        p.refresh_from_db()
        self.assertEqual(p.career,before)

    def test_chosen_avatar_survives_lite_career_to_retirement(self):
        from .test_rookie_lite import autoplay
        rng=random.Random(134)
        c=X.create(self.user,name='끝까지선수',role='batter',position='SS',style=next(iter(X.STYLES['batter'])),region='서울',team='lg',rng=rng)
        A.save(c,A.clean(self.chosen))
        autoplay(c,rng)
        c.refresh_from_db()
        self.assertIsNotNone(c.retired_at)
        self.assertEqual(A.recipe(c),A.clean(self.chosen))

    def test_both_templates_show_picker_and_bounded_names(self):
        for ua in (PC,MOBILE):
            for url in ('/rookie/','/rookie/lite/','/rookie/extreme/'):
                cache.clear()
                response=self.client.get(url,HTTP_USER_AGENT=ua)
                self.assertContains(response,'data-avatar-picker',count=1)
                for key in A.OPTIONS:self.assertContains(response,f'name="avatar_{key}"',count=1)
