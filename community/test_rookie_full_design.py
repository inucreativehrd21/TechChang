"""정식 리메이크 표시 경계·공개 기록·기록 불변·수상 위계를 검증해요."""
from copy import deepcopy
from datetime import datetime, time, timedelta
from types import SimpleNamespace as NS
from django.test import SimpleTestCase, TestCase, override_settings
from django.template.loader import render_to_string
from django.utils import timezone
from . import rookie_clock as Clock, rookie_league as L, rookie_halves as H
from . import rookie_playback as Playback, rookie_matchday_presentation as UI
from .test_rookie_league import player

ON = dict(ROOKIE_FULL_SLOTS='true', ROOKIE_FULL_HALVES='true', ROOKIE_FULL_POSTSEASON='true', ROOKIE_SLOTS_FROM_SEASON='2')

def at(day, hh=20, mm=5):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


@override_settings(**ON)
class FullDesignCalendarTests(SimpleTestCase):
    def test_all_seven_sky_keys_at_exact_boundaries(self):
        day = L.season_bounds(2)[0]
        for hour, minute, key in [(0,0,'dawn'),(10,59,'dawn'),(11,0,'morning'),(12,59,'morning'),
                                  (13,0,'noon'),(15,29,'noon'),(15,30,'afternoon'),(17,59,'afternoon'),
                                  (18,0,'dusk'),(20,0,'night'),(22,0,'main'),(23,0,'dawn')]:
            self.assertEqual(UI.sky_key(at(day,hour,minute)), key)

    def test_calendar_milestones_ornaments_and_cycle(self):
        start = L.season_bounds(2)[0]
        for day, phase, ornament in [(1,'first','opening'),(14,'first',None),(15,'second',None),
                                     (22,'stretch','stretch'),(28,'stretch','stretch'),(29,'post','postseason'),(30,'post','postseason')]:
            now = at(start+timedelta(days=day-1))
            cal = UI.calendar(now)
            self.assertEqual((cal['day'],cal['phase']), (day,phase))
            self.assertEqual(UI.sky(now,cal)['ornament'], ornament)
            self.assertEqual(len([n for n in cal['nodes'] if n['current']]),1)
            self.assertEqual(cal['next_open'], L.season_bounds(3)[0])
        self.assertEqual(UI.calendar(at(start+timedelta(days=30)))['day'],1)

    def test_midnight_keeps_dawn_until_eleven_and_timeline_only_contains_future(self):
        now = at(L.season_bounds(2)[0],23,30)
        data = UI.sky(now,UI.calendar(now))
        self.assertEqual(data['key'],'dawn')
        self.assertEqual(data['timeline'][0]['key'],'morning')
        self.assertTrue(all(n['at']>now.timestamp()*1000 for n in data['timeline']))

    @override_settings(ROOKIE_FULL_HALVES='false',ROOKIE_FULL_SLOTS='false')
    def test_switches_off_keep_legacy_entry_and_no_calendar(self):
        now = at(L.season_bounds(2)[0])
        self.assertIsNone(UI.calendar(now))
        self.assertIsNone(Playback.stadium(NS(retired_at=None), now))

    def test_race_view_does_not_mutate_engine_tables(self):
        rows = [dict(club='lg',name='LG',w=8,l=2,d=0,g=10,mine=True,rank=1),dict(club='nc',name='NC',w=4,l=6,d=0,g=10,mine=False,rank=2)]
        table = {'games':144,'rows':rows}
        halves = {'first':table,'second':table,'per':72,'first_champ':rows[0]}
        before = deepcopy((halves,table))
        views = UI.race_views(halves,table)
        self.assertEqual((halves,table),before)
        self.assertEqual([v['key'] for v in views],['first','second','whole'])
        self.assertEqual(views[0]['rows'][0]['left'],62)
        self.assertTrue(views[0]['rows'][0]['first_champ'])
        self.assertEqual(views[-1]['rows'][0]['left'],134)

    def test_half_award_comes_before_title_but_not_season_mvp(self):
        season=NS(number=2)
        half=NS(pk=1,kind='half',label='전기리그 MVP',league='kbo1',season=season,value='WAR 3.2',order=61)
        title=NS(pk=2,kind='title',label='타격왕',league='kbo1',season=season,value='.320',order=1)
        mvp=NS(pk=3,kind='mvp',label='MVP',league='kbo1',season=season,value='WAR 7.0',order=0)
        fx={'kind':'title','hero':'타격왕','line':'.320','colors':['#4f46e5','#a5b4fc']}
        out=UI.award_fx(fx,[title,half])
        self.assertEqual((out['hero'],out['line'],out['count']),('전기리그 MVP','WAR 3.2','14일의 주인공'))
        self.assertEqual(out['others'],['타격왕'])
        self.assertTrue(out['half'])
        self.assertNotIn('half',fx)
        self.assertEqual(UI.award_fx(fx,[mvp,half]),fx)
        pair=UI.half_awards([half])
        self.assertEqual(pair[0]['award'],half)
        self.assertIsNone(pair[1]['award'])


@override_settings(**ON)
class FullDesignPostTests(TestCase):
    def setUp(self):
        self.s=L.get_season(2)
        self.p=player('디자인선수')
        post=H.build_post(self.p,self.s)
        self.p.club=post['seeds']['first']
        self.p.career.pop('post',None)
        self.p.career['post']=H.build_post(self.p,self.s)
        self.p.save(update_fields=['club','career'])
        self.times=[datetime.fromisoformat(t) for t in self.p.career['post']['at']]

    def test_live_series_only_contains_public_games_and_prioritizes_next_final(self):
        before=deepcopy(self.p.career)
        now=self.times[2]+timedelta(minutes=1)
        md=Playback.stadium(self.p,now)
        self.assertEqual(self.p.career,before)
        self.assertEqual((md['post']['shown'],md['post']['live']),(3,True))
        self.assertEqual(len(md['post']['doc']['rounds'][0]['games']),3)
        self.assertEqual(md['post']['doc']['result'],'')
        self.assertEqual(md['next']['at'],self.times[3])
        self.assertEqual(md['refresh_at'],int(self.times[3].timestamp()*1000)+60000)
        html=render_to_string('community/games/_rookie_matchday.html',{'md':md,'p':self.p})
        self.assertIn('data-sb-live-series',html)
        self.assertIn('3차전 종료',html)
        self.assertNotIn('data-sb-game="4"',html)
        self.assertNotIn('data-sb-champion',html)
        self.assertIn('정규시즌 마지막 경기 돌아보기',html)
        self.assertNotIn('>LIVE<',html)

    def test_completed_and_spectator_views_do_not_invent_championship(self):
        now=self.times[-1]+timedelta(minutes=1)
        md=Playback.stadium(self.p,now)
        html=render_to_string('community/games/_rookie_matchday.html',{'md':md,'p':self.p})
        self.assertNotIn('data-sb-live-series',html)
        self.assertEqual('data-sb-champion' in html,md['post']['won'])
        post=deepcopy(md['post'])
        post['mine']=False
        md['post']=post
        html=render_to_string('community/games/_rookie_matchday.html',{'md':md,'p':self.p})
        self.assertIn('우리 팀의 다음 도전을 기다리며',html)
        self.assertNotIn('data-sb-champion',html)
        self.assertNotIn('data-sb-game-card',html)

    def test_half_awards_hidden_when_feature_is_off_even_with_historical_records(self):
        with override_settings(ROOKIE_FULL_HALVES='false'):
            self.assertIsNone(UI.calendar(at(self.s.end)))
        # 시상식에 새 표시 자료가 없으면 기존 수상 부분만 남아요.
        html=render_to_string('community/games/_rookie_awards.html',{'cur':self.s,'halves':[NS(label='전기리그 MVP')]})
        self.assertNotIn('rk-half-award',html)
