from django.core.management.base import BaseCommand
from pybo.models import Category, Question


class Command(BaseCommand):
    help = '기존 카테고리들을 HRD/데이터분석/프로그래밍으로 통합하고 나머지를 정리합니다'

    def handle(self, *args, **options):
        # 1) 새 카테고리 준비
        target_names = ['HRD', '데이터분석', '프로그래밍']
        targets = {}
        for name in target_names:
            obj, created = Category.objects.get_or_create(
                name=name,
                defaults={'description': f'{name} 관련 질문'}
            )
            targets[name] = obj
            if created:
                self.stdout.write(f'새 카테고리 생성: {name}')

        # 2) 매핑 규칙 정의 (없으면 기본 HRD)
        mapping = {
            '질문답변': 'HRD',
            '자유게시판': 'HRD',
            '강좌': 'HRD',
            '공지사항': 'HRD',
            '일반': 'HRD',
            'Python': '프로그래밍',
            'Django': '프로그래밍',
            'JavaScript': '프로그래밍',
            '웹개발': '프로그래밍',
            '데이터베이스': '데이터분석',
            '기타': 'HRD',
        }

        # 3) 모든 질문을 순회하며 카테고리 재지정
        updated = 0
        total = Question.objects.count()
        for q in Question.objects.select_related('category').all():
            old_name = q.category.name if q.category_id else None
            new_name = mapping.get(old_name, 'HRD')
            new_cat = targets[new_name]
            if q.category_id != new_cat.id:
                q.category = new_cat
                q.save(update_fields=['category'])
                updated += 1
        self.stdout.write(f'질문 {total}건 중 {updated}건 카테고리 업데이트')

        # 4) 타깃 3개 외 카테고리 정리 (질문 없는 것만 삭제)
        removed = 0
        for cat in Category.objects.exclude(name__in=target_names):
            if cat.question_set.count() == 0:
                cat.delete()
                removed += 1
        self.stdout.write(f'빈 카테고리 {removed}건 삭제')

        self.stdout.write(self.style.SUCCESS('카테고리 교체가 완료되었습니다!'))