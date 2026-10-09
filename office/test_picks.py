from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office.models import ColumnDraft
from office.picks import PICK_SCORE, pick_scores


def column(subject, score, status=ColumnDraft.STATUS_PUBLISHED):
    bot, _ = User.objects.get_or_create(username='techchang연구팀')
    cat, _ = Category.objects.get_or_create(name='HRD')
    q = Question.objects.create(author=bot, category=cat, subject=subject, content='본문', create_date=timezone.now())
    ColumnDraft.objects.create(topic='hrd', subject=subject, status=status, question=q, qa_report={'score': score})
    return q


class PickTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_only_published_columns_at_or_above_threshold(self):
        top = column('추천 칼럼', PICK_SCORE)
        column('기준 미달', PICK_SCORE - 1)
        legacy = column('옛 10점 척도 9점 = 90점', 9)       # 구버전 점수도 환산해 판단
        self.assertEqual(pick_scores(), {top.id: PICK_SCORE, legacy.id: 90})

    def test_home_shows_badge_on_picks_only(self):
        top = column('추천 칼럼입니다', 92)
        column('일반 칼럼입니다', 80)
        res = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0) Chrome/130')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertEqual(html.count('class="tc-pick"'), 2)        # 인기 레일 + 게시글 카드 (일반 칼럼엔 없음)
        self.assertIn('연구팀 편집 심사 92점', html)
        self.assertIn('누구나 무료로 읽을 수 있습니다', html)
        self.assertNotIn('질문하고 답하며 함께 성장하는', html)

    def test_mobile_home_shows_badge(self):
        column('추천 칼럼입니다', 92)
        res = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148')
        self.assertContains(res, 'class="tc-m-pick"')
        self.assertContains(res, 'tc-mh-sub')
