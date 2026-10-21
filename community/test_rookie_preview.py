"""장면 미리보기의 운영 차단과 PC·모바일 공용 연출을 검증한다."""
from django.test import TestCase, override_settings
from django.contrib.staticfiles import finders

from community import rookie_card as K

from community.models import LiteCareer, RookiePlayer


@override_settings(DEBUG=True)
class RookiePreviewTests(TestCase):
    def get_preview(self, query='', mobile=False):
        ua = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'
              if mobile else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130')
        return self.client.get('/rookie/preview/' + query, HTTP_USER_AGENT=ua)

    @override_settings(DEBUG=False)
    def test_preview_unavailable_in_production(self):
        self.assertEqual(self.get_preview('?scene=chain').status_code, 404)

    def test_scene_preview_does_not_create_players(self):
        before = (LiteCareer.objects.count(), RookiePlayer.objects.count())
        for scene in ('opening', 'season', 'awaken', 'awaken_fail', 'homerun', 'strikeout', 'loss', 'award', 'chain'):
            self.assertEqual(self.get_preview('?scene=' + scene).status_code, 200)
        self.assertEqual((LiteCareer.objects.count(), RookiePlayer.objects.count()), before)

    def test_shared_effects_wait_for_the_same_queue(self):
        response = self.get_preview('?scene=chain')
        self.assertContains(response, 'data-rl-mfx style="--tr: 1.6s" hidden')
        self.assertContains(response, 'window.rlFxChain = true;', count=1)
        self.assertTemplateUsed(response, 'community/games/_lite_awaken_fx.html')
        self.assertTemplateUsed(response, 'community/games/_lite_moment_fx.html')
        self.assertTemplateUsed(response, 'community/games/_lite_award_fx.html')

    def test_full_edition_uses_its_available_scenes(self):
        response = self.get_preview('?edition=full&scene=chain')
        self.assertTemplateUsed(response, 'community/games/_lite_awaken_fx.html')
        self.assertTemplateUsed(response, 'community/games/_lite_award_fx.html')
        self.assertTemplateNotUsed(response, 'community/games/_lite_moment_fx.html')
        self.assertNotContains(response, 'scene=homerun')

    def test_mobile_uses_mobile_shell_and_shared_scene(self):
        response = self.get_preview('?scene=award', mobile=True)
        self.assertTemplateUsed(response, 'base_mobile.html')
        self.assertTemplateUsed(response, 'community/games/_lite_award_fx.html')

    def test_unknown_scene_is_safe_to_open(self):
        response = self.get_preview('?scene=missing')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['scene'], 'opening')

    def test_all_ten_uniforms_render_with_real_static_assets(self):
        response = self.get_preview('?scene=cards&all=1')
        self.assertEqual(len(response.context['uniform_gallery']), 10)
        for code in K.KBO_TRIM:
            asset = f'img/rookie/uniforms/{code}.webp'
            self.assertIsNotNone(finders.find(asset))
            self.assertContains(response, '/static/' + asset)
        self.assertEqual((LiteCareer.objects.count(), RookiePlayer.objects.count()), (0, 0))

    def test_card_personalization_and_export_share_the_uniform(self):
        for shot in ('', '&shot=card', '&shot=og', '&shot=story'):
            response = self.get_preview('?scene=cards&club=lg&player_name=김새별&number=99' + shot)
            self.assertContains(response, '/static/img/rookie/uniforms/lg.webp')
            self.assertContains(response, '김새별')
            self.assertContains(response, '>99</text>')
            self.assertContains(response, 'rookie-card.css')
            if shot:
                self.assertTemplateUsed(response, 'community/games/lite_card_shot.html')

    def test_full_and_mobile_share_the_same_card(self):
        for mobile in (False, True):
            response = self.get_preview('?edition=full&scene=cards&club=hanwha', mobile=mobile)
            self.assertContains(response, '/static/img/rookie/uniforms/hanwha.webp')
            self.assertTemplateUsed(response, 'community/games/_lite_retire.html')

    def test_foreign_clubs_share_matching_kbo_uniform(self):
        from django.template.loader import render_to_string
        from types import SimpleNamespace
        palette = K._palette('mlb', 'nyy')
        html = render_to_string('community/games/_lite_retire.html',
                                {'c': SimpleNamespace(name='김새별', number=7), 'card': {'palette': palette}})
        self.assertIn('/static/img/rookie/uniforms/doosan.webp', html)
        self.assertNotIn('uniforms/nyy.webp', html)
        response = self.get_preview('?scene=cards&club=nyy')
        card = response.context['uniform_preview']['card']
        self.assertEqual(card['peak_short'], 'MLB')
        self.assertEqual(card['best']['league'], 'MLB')
        self.assertContains(response, '실버슬러거')
