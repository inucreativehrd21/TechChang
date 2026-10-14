"""프리미엄 칼럼 — 최종 편집 심사 90점 이상(office.picks). 발행 기준(필수 수정·치명 결함 없음)과 따로 간다."""
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office.models import ColumnDraft, StageRun, WorkLog
from office.picks import PREMIUM_SCORE, final_scores, premium_scores


def column(subject, score, status=ColumnDraft.STATUS_PUBLISHED):
    bot, _ = User.objects.get_or_create(username='techchang연구팀')
    cat, _ = Category.objects.get_or_create(name='HRD')
    q = Question.objects.create(author=bot, category=cat, subject=subject, content='본문', create_date=timezone.now())
    ColumnDraft.objects.create(topic='hrd', subject=subject, status=status, question=q, qa_report={'score': score})
    return q


def remade(q, score, stage='applied', verdict='minor', later=1):
    r = StageRun.objects.create(run_id=uuid.uuid4(), question=q, seq=1, stage=stage, agent='editor',
                                output={'score': score, 'verdict': verdict})
    StageRun.objects.filter(pk=r.pk).update(created_at=timezone.now() + timedelta(hours=later))


class PremiumTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_only_published_columns_at_or_above_threshold(self):
        top = column('프리미엄 칼럼', PREMIUM_SCORE)
        column('발행은 됐지만 프리미엄 아님', PREMIUM_SCORE - 1)
        column('보류된 원고', 95, status=ColumnDraft.STATUS_HOLD)
        legacy = column('옛 10점 척도 9점 = 90점', 9)       # 구버전 점수도 환산해 판단
        self.assertEqual(premium_scores(), {top.id: PREMIUM_SCORE, legacy.id: 90})

    def test_final_score_follows_the_last_applied_version(self):
        up = column('발행 70 → 갱신 93', 70)
        down = column('발행 82 → 갱신 68', 82)
        remade(up, 93)
        remade(down, 68)
        old = column('옛 리메이크 통과', 60)
        remade(old, 95, stage='final', verdict='accept')       # 예전 리메이크는 통과 final 만 남았다
        rejected = column('리메이크 미달', 91)
        remade(rejected, 50, stage='final', verdict='major')   # 반영 안 됨 — 원래 점수 유지
        self.assertEqual(final_scores()[down.id], 68)
        self.assertEqual(premium_scores(), {up.id: 93, old.id: 95, rejected.id: 91})

    def test_home_shows_premium_badge_only_on_premium(self):
        column('프리미엄 칼럼입니다', 92)
        column('발행됐지만 90 미만', 89)
        res = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0) Chrome/130')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertEqual(html.count('class="tc-pick"'), 2)        # 인기 레일 + 게시글 카드 (일반 칼럼엔 없음)
        self.assertIn('연구팀 편집 심사 92점 — 프리미엄 칼럼(90점 이상)', html)
        self.assertIn('누구나 무료로 읽을 수 있습니다', html)
        self.assertNotIn('질문하고 답하며 함께 성장하는', html)

    def test_mobile_home_shows_badge(self):
        column('프리미엄 칼럼입니다', 92)
        res = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148')
        self.assertContains(res, 'class="tc-m-pick"')
        self.assertContains(res, '프리미엄</span>')
        self.assertContains(res, 'tc-mh-sub')

    def test_detail_page_badge(self):
        top = column('프리미엄 상세', 93)
        plain = column('일반 상세', 72)
        for ua in ('Mozilla/5.0 (Windows NT 10.0) Chrome/130',
                   'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'):
            self.assertContains(self.client.get(f'/{top.id}/', HTTP_USER_AGENT=ua), '프리미엄 칼럼 · 93점')
            self.assertNotContains(self.client.get(f'/{plain.id}/', HTTP_USER_AGENT=ua), '프리미엄 칼럼 ·')

    def test_publish_log_scores_count_and_latest_wins(self):
        bot, _ = User.objects.get_or_create(username='techchang연구팀')
        cat, _ = Category.objects.get_or_create(name='HRD')
        legacy = Question.objects.create(author=bot, category=cat, subject='옛 칼럼', content='본문', create_date=timezone.now())
        WorkLog.objects.create(agent='editor', action='publish', text=f'리메이크 반영(제자리 갱신): 옛 칼럼 (id={legacy.id}, 91점)')
        manual = column('수동 갱신', 70)
        w = WorkLog.objects.create(agent='editor', action='publish',
                                   text=f'리메이크 반영(제자리 갱신): 수동 갱신 (id={manual.id}, 68점·필수 수정 0건)')
        WorkLog.objects.filter(pk=w.pk).update(created_at=timezone.now() + timedelta(hours=1))
        f = final_scores()
        self.assertEqual((f[legacy.id], f[manual.id]), (91, 68))
        self.assertIn(legacy.id, premium_scores())

    def test_pre_reform_remake_scores_do_not_count(self):
        from office.picks import REVIEW_REFORM
        before = timezone.make_aware(REVIEW_REFORM) - timedelta(days=2)
        bot, _ = User.objects.get_or_create(username='techchang연구팀')
        cat, _ = Category.objects.get_or_create(name='HRD')

        def logged(subject, text, at):
            q = Question.objects.create(author=bot, category=cat, subject=subject, content='본문', create_date=timezone.now())
            w = WorkLog.objects.create(agent='editor', action='publish', text=text.format(id=q.id))
            WorkLog.objects.filter(pk=w.pk).update(created_at=at)
            return q

        old_remake = logged('옛 리메이크', '리메이크 반영(제자리 갱신): 옛 리메이크 (id={id}, 98점)', before)
        old_original = logged('개편 전 새 글', '발행: 개편 전 새 글 (id={id}, 100점)', before)
        new_remake = logged('개편 후 리메이크', '리메이크 반영(제자리 갱신): 개편 후 리메이크 (id={id}, 92점)', timezone.now())
        f = final_scores()
        self.assertNotIn(old_remake.id, f)                      # 후한 옛 심사 — 다시 심사받기 전엔 프리미엄 아님
        self.assertEqual((f[old_original.id], f[new_remake.id]), (100, 92))
        self.assertEqual(set(premium_scores()), {old_original.id, new_remake.id})

    def test_series_remake_draft_before_reform_does_not_count(self):
        from office.picks import REVIEW_REFORM
        q = column('연재 2편', 60)
        d = ColumnDraft.objects.create(topic='coding', subject='연재 2편', status=ColumnDraft.STATUS_PUBLISHED,
                                       target_question=q, qa_report={'score': 91})
        ColumnDraft.objects.filter(pk=d.pk).update(created_at=timezone.make_aware(REVIEW_REFORM) - timedelta(days=1))
        ColumnDraft.objects.filter(question=q).update(created_at=timezone.make_aware(REVIEW_REFORM) - timedelta(days=30))
        self.assertEqual(final_scores()[q.id], 60)               # 옛 연재 리메이크 91점은 빼고 원래 점수
        self.assertNotIn(q.id, premium_scores())
