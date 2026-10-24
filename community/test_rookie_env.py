"""경기 환경·경기 전 대비(rookie_env) — 환경은 커리어 난수로 정해지고, 보정은 작고, 루틴은 손해만 줄여요."""
import random
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import rookie_env as E
from . import rookie_lite as X
from . import rookie_universe as U
from .management.commands.rookie_balance import choose
from .test_rookie_lite import member


def fake(pk=3, name='환경', year=4, club='lg'):
    return SimpleNamespace(pk=pk, name=name, year=year, club=club)


class EnvRulesTests(SimpleTestCase):
    def test_season_is_deterministic_and_follows_fixtures(self):
        fx = U.club_fixtures('kbo1', 144, 'lg')
        a = E.season(fake(), 'kbo1', 'lg', 144, fx)
        self.assertEqual(a, E.season(fake(), 'kbo1', 'lg', 144, fx))
        self.assertNotEqual(a, E.season(fake(pk=4), 'kbo1', 'lg', 144, fx))
        for env, f in zip(a, fx):
            self.assertEqual(env['home'], 'home' if f['home'] else 'away')
            if env['park'] == 'dome':
                self.assertEqual(env['weather'], '돔')
        self.assertEqual(sum(1 for e in a if e['home'] == 'home'), sum(1 for f in fx if f['home']))
        lg_home = [e for e in a if e['home'] == 'home']
        self.assertTrue(all(e['park'] == 'pitcher' for e in lg_home))          # LG 홈은 투수 친화

    def test_weather_follows_the_month(self):
        envs = E.season(fake(club='kia'), 'kbo1', 'kia', 600, U.club_fixtures('kbo1', 144, 'kia') * 5)
        months = {}
        for e in envs:
            months.setdefault(e['month'], []).append(e['weather'])
        self.assertNotIn('폭염', months[4] + months[5] + months[9])             # 4·5·9월엔 폭염이 없다
        self.assertNotIn('한파', months[6] + months[7] + months[8])
        self.assertGreater(months[8].count('폭염'), 0)

    def test_effects_are_small_and_balanced(self):
        for role in ('batter', 'pitcher'):
            for weather in E.WEATHERS + ('돔',):
                for park in ('hitter', 'pitcher', 'dome', 'neutral'):
                    for home in ('home', 'away', 'neutral'):
                        env = {'month': 7, 'home': home, 'park': park, 'weather': weather if park != 'dome' else '돔',
                               'wind': 'out', 'time': '야간', 'crowd': '보통'}
                        for routine in E.ROUTINES:
                            d = E.delta(role, env, routine)
                            self.assertTrue(all(abs(v) <= 6 for v in d.values()), (role, env, routine, d))
        neutral = {'month': 5, 'home': 'neutral', 'park': 'neutral', 'weather': '맑음', 'wind': '', 'time': '야간', 'crowd': '보통'}
        self.assertEqual(E.delta('batter', neutral, 'travel'), {})
        home = dict(neutral, home='home')
        away = dict(neutral, home='away')
        self.assertEqual(E.delta('batter', home, 'travel')['contact'], -E.delta('batter', away, 'balance')['contact'] / .75)

    def test_routines_only_reduce_harm(self):
        cases = [
            ('travel', {'home': 'away'}, 'batter', 'contact'),
            ('heat', {'weather': '폭염'}, 'pitcher', 'stamina'),
            ('weather', {'weather': '한파'}, 'batter', 'power'),
        ]
        base = {'month': 8, 'home': 'neutral', 'park': 'neutral', 'weather': '맑음', 'wind': '', 'time': '야간', 'crowd': '보통'}
        for routine, change, role, key in cases:
            env = dict(base, **change)
            plain = E.delta(role, env, 'night' if role == 'pitcher' else 'heat').get(key, 0)    # 맞지 않는 루틴
            fit = E.delta(role, env, routine).get(key, 0)
            self.assertGreater(fit, plain - 1e-9, (routine, plain, fit))
        night = E.delta('batter', dict(base, time='주간'), 'night')
        self.assertLess(night['contact'], 0)                                  # 야간 집중은 주간에 손해

    def test_condition_splits_and_media_view(self):
        store = {}
        E.add_split(store, {'home': 'home', 'time': '야간', 'weather': '비', 'park': 'pitcher', 'wind': ''},
                    {'pa': 4, 'ab': 4, 'h': 2, 'hr': 1, 'g': 1})
        rows = E.split_rows('batter', store)
        self.assertEqual({r['key'] for r in rows}, {'홈', '야간', '비', '투수 친화 구장'})
        self.assertTrue(all(r['games'] == 1 and r['rate'] == '.500' for r in rows))
        v = E.media_view('한국시리즈 6차전', 'post')
        self.assertEqual([c['key'] for c in v['choices']], list(E.MEDIA))
        self.assertIn('미디어데이', v['title'])

    def test_series_games_get_environment_without_changing_results(self):
        from . import rookie_series as S
        for doc in S.demo('batter'):
            before = [(g['score'], g['won']) for rd in doc['rounds'] for g in rd['games']]
            E.decorate_series(fake(), doc)
            after = [(g['score'], g['won']) for rd in doc['rounds'] for g in rd['games']]
            self.assertEqual(before, after)
            self.assertTrue(all('env' in g for rd in doc['rounds'] for g in rd['games']))


@override_settings(ROOKIE_EXTREME_PREVIEW=True)
class EnvFlowTests(TestCase):
    def play(self, seed, enabled, routine='balance'):
        with override_settings(ROOKIE_ENV_ENABLED=enabled):
            rng = random.Random(seed)
            u = User.objects.create(username=f'env-{seed}-{enabled}-{routine}', is_staff=True)
            c = X.create(u, name='환경', role='pitcher', position='SP', style=next(iter(X.STYLES['pitcher'])),
                         region='서울', team='lg', rng=rng)
            media = 0
            for _ in range(200):
                if c.retired_at:
                    break
                p = c.pending
                if p['kind'] == 'plan':
                    event, pick = p.get('event'), ''
                    if event:
                        keys = [i[0] for i in X.EVENTS[event]['choices']]
                        pick = next((k for k in ('team_work', 'team', 'rest', 'together', 'short', 'break', 'accept') if k in keys), keys[0])
                    X.run_season(c, X.pick_programs(c, rng), 'normal', pick, rng, intl={k: 'go' for k in p.get('intl') or []},
                                 routine=routine)
                elif p['kind'] == 'review':
                    X.next_season(c, rng)
                else:
                    media += p.get('what') == 'mediaday'
                    try:
                        X.decide(c, p['what'], choose(c, rng, 'playing'), rng)
                    except X.LiteError:
                        view = X.decision_view(c) or {}
                        keys = [ch['key'] for ch in view.get('choices') or []] + [o['key'] for o in view.get('offers') or []]
                        X.decide(c, p['what'], keys[0], rng)
                    c.save()
            return c, list(c.seasons.order_by('year')), media

    def test_switch_off_keeps_everything_and_switch_on_records_conditions(self):
        _c, off, media_off = self.play(5150, False)
        self.assertFalse(any(s.env for s in off))
        self.assertEqual(media_off, 0)
        self.assertFalse(E.enabled())
        c, on, _media = self.play(5150, True, 'heat')
        pro = [s for s in on if s.env and s.env.get('splits')]
        self.assertTrue(pro)
        self.assertTrue(all(s.env['routine'] == 'heat' for s in pro))
        rows = E.split_rows(c.role, pro[-1].env['splits'])
        self.assertTrue(any(r['key'] in ('홈', '원정') for r in rows))

    def test_media_day_runs_before_the_big_moment(self):
        u = User.objects.create(username='media', is_staff=True)
        c = X.create(u, name='미디어', role='batter', position='SS', style='contact', region='서울', team='lg', rng=random.Random(3))
        s = c.seasons.create(year=c.year, age=c.age, league='kbo1', club='lg')
        moment = X.make_moment(c, 'series', '한국시리즈 6차전', '10월', random.Random(1))
        then = {'kind': 'decision', 'what': 'moment', 'year': s.year, 'moments': [moment], 'i': 0, 'done': []}
        c.pending = {'kind': 'decision', 'what': 'mediaday', 'year': s.year, 'stage': moment['stage'], 'scope': 'post', 'then': then}
        c.save()
        with override_settings(ROOKIE_ENV_ENABLED=True):
            view = X.decision_view(c)
            self.assertEqual(view['what'], 'mediaday')
            with self.assertRaises(X.LiteError):
                X.decide(c, 'mediaday', 'nope', random.Random(1))
            text = X.decide(c, 'mediaday', 'bold', random.Random(1))
        self.assertIn('우승을 선언할게요', text)
        self.assertEqual(c.pending['what'], 'moment')
        s.refresh_from_db()
        self.assertTrue(any('[미디어데이]' in p.get('tag', '') for p in s.press))

    def test_plan_screen_shows_routines_when_enabled(self):
        u = member('plan-env')                                              # 이메일 인증까지 마친 회원
        c = X.create(u, name='계획', role='batter', position='SS', style='contact', region='서울', team='lg', rng=random.Random(9))
        client = Client()
        client.force_login(u)
        with override_settings(ROOKIE_ENV_ENABLED=True):
            html = client.get('/rookie/lite/', HTTP_USER_AGENT='Mozilla/5.0 Windows NT 10.0 Chrome/130').content.decode()
        self.assertIn('name="routine"', html)
        self.assertIn('올 시즌 예보', html)
        html = client.get('/rookie/lite/', HTTP_USER_AGENT='Mozilla/5.0 Windows NT 10.0 Chrome/130').content.decode()
        self.assertNotIn('name="routine"', html)

    def test_env_splits_template_renders(self):
        rows = E.split_rows('pitcher', {'홈': {'outs': 27, 'r': 2, 'er': 2, 'h': 5, 'g': 1, 'g_env': 1}})
        html = render_to_string('community/games/_lite_env_splits.html', {'env_rows': rows, 'env_routine': '원정 루틴'})
        self.assertIn('조건별 성적', html)
        self.assertIn('평균자책점', html)


@override_settings(GAME_CONTROLS_USE_DB=False)
class ConditionalTraitTests(SimpleTestCase):
    def test_roll_is_deterministic_rare_and_never_contradictory(self):
        counts = {0: 0, 1: 0, 2: 0}
        for pk in range(1, 3001):
            got = E.roll_cond(fake(pk=pk))
            self.assertEqual(got, E.roll_cond(fake(pk=pk)))
            self.assertFalse({'home_tiger', 'road_reaper'} <= set(got))
            counts[len(got)] += 1
        self.assertTrue(.40 < counts[0] / 3000 < .52)
        self.assertTrue(.06 < counts[2] / 3000 < .14)

    def test_existing_trait_draw_is_untouched(self):
        pool = [t for t in X.TRAITS if t not in X.Hands.TRAITS and t not in E.COND_TRAITS]
        self.assertEqual(pool, ['early', 'late', 'iron', 'glass', 'grinder', 'learner', 'clutch', 'natural'])
        for t in E.COND_TRAITS:
            self.assertIn(t, X.TRAITS)                                     # 이름은 화면·스카우팅 리포트에 쓴다
        a = X.roll_traits(random.Random(5))
        self.assertTrue(set(a) <= set(pool))

    def test_effects_follow_the_condition(self):
        env = {'month': 7, 'home': 'home', 'park': 'dome', 'weather': '돔', 'wind': '', 'time': '주간', 'crowd': '만원'}
        self.assertEqual(E.cond_delta('batter', env, ['summer_man']), {'contact': 2.0, 'power': 2.0})
        self.assertEqual(E.cond_delta('pitcher', env, ['home_tiger', 'night_owl']), {'control': -1.0, 'breaking': -1.0})
        self.assertEqual(E.cond_delta('batter', env, ['dome_kid', 'big_stage']), {'contact': 3.5, 'power': 3.5})
        self.assertEqual(E.cond_delta('batter', env, ['rain_man']), {})
        self.assertEqual(E.cond_delta('batter', dict(env, weather='한파', park='neutral'), ['cold_weak']), {'contact': -4.0, 'power': -4.0})
        self.assertEqual(E.big_delta('batter', 'post', ['october']), {'contact': 4.0, 'power': 4.0})
        self.assertEqual(E.big_delta('pitcher', 'intl', ['october']), {})

    def test_reveal_needs_enough_games_and_shows_the_record(self):
        c = SimpleNamespace(role='batter', traits=['rain_man', 'october'], traits_seen=[])
        few = {'비': {'pa': 10, 'ab': 9, 'h': 4, 'g_env': 3}}
        self.assertEqual(E.reveal(c, few, {'pa': 500, 'ab': 450, 'h': 120}), [])
        many = {'비': {'pa': 40, 'ab': 36, 'h': 12, 'g_env': 9}}
        out = E.reveal(c, many, {'pa': 500, 'ab': 450, 'h': 120})
        self.assertEqual([t for t, _ in out], ['rain_man'])
        self.assertIn('비 타율 .333(시즌 .267)', out[0][1])

    def test_ensure_traits_runs_once(self):
        c = SimpleNamespace(pk=17, name='한번', traits=['iron'], flags={})
        first = E.ensure_traits(c)
        again = E.ensure_traits(c)
        self.assertEqual(again, [])
        self.assertEqual(c.traits, ['iron'] + first)
        self.assertTrue(c.flags['cond_rolled'])


@override_settings(ROOKIE_EXTREME_PREVIEW=True, ROOKIE_ENV_ENABLED=True)
class ConditionalTraitFlowTests(TestCase):
    def test_trait_shows_in_the_record_and_is_revealed(self):
        rng = random.Random(77)
        u = User.objects.create(username='cond-flow', is_staff=True)
        c = X.create(u, name='조건부', role='batter', position='SS', style='contact', region='서울', team='lg', rng=rng)
        c.league, c.club, c.age, c.grade = 'kbo1', 'lg', 24, 0
        c.traits, c.traits_seen = ['home_tiger'], []
        c.flags = dict(c.flags, cond_rolled=True, start=2026, trust=50)
        c.pending = {'kind': 'plan', 'event': None, 'intl': [], 'shop': None}           # 비시즌 이벤트 없이 바로 시즌
        c.save()
        X.run_season(c, X.pick_programs(c, rng), 'normal', '', rng, routine='balance')
        while (c.pending or {}).get('kind') == 'decision':
            view = X.decision_view(c) or {}
            X.decide(c, c.pending['what'], (view.get('choices') or [{'key': 'accept'}])[0]['key'], rng)
        s = c.seasons.order_by('-year').first()
        self.assertIn('home_tiger', c.traits_seen)
        self.assertTrue(any('숨은 특성 발견 — 안방 호랑이' in n for n in s.news))
        self.assertIn('home_tiger', s.env.get('revealed', []))

    def test_moment_stats_get_big_game_bonus(self):
        u = User.objects.create(username='october', is_staff=True)
        c = X.create(u, name='가을', role='batter', position='SS', style='contact', region='서울', team='lg', rng=random.Random(4))
        c.traits = ['october']
        base = X._game_stats(c)
        boosted = X._moment_stats(c, {'kind': 'series'})
        self.assertAlmostEqual(boosted['contact'] - base['contact'], 4.0)
        self.assertEqual(X._moment_stats(c, {'kind': 'amateur'})['contact'], base['contact'])
