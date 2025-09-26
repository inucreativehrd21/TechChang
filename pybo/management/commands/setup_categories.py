from django.core.management.base import BaseCommand
from pybo.models import Category, Question

class Command(BaseCommand):
    help = '기본 카테고리를 생성하고 기존 질문들에 기본 카테고리를 할당합니다.'

    def handle(self, *args, **options):
        # 기본 카테고리 생성
        categories = [
            {'name': '질문답변', 'description': '일반적인 질문과 답변을 위한 게시판'},
            {'name': '자유게시판', 'description': '자유로운 주제의 토론을 위한 게시판'},
            {'name': '강좌', 'description': '학습 자료와 강의를 위한 게시판'},
            {'name': '공지사항', 'description': '중요한 공지사항을 위한 게시판'},
        ]

        default_category = None
        for category_data in categories:
            category, created = Category.objects.get_or_create(
                name=category_data['name'],
                defaults={'description': category_data['description']}
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"카테고리 '{category.name}'이 생성되었습니다.")
                )
            else:
                self.stdout.write(f"카테고리 '{category.name}'이 이미 존재합니다.")
            
            # 첫 번째 카테고리를 기본 카테고리로 설정
            if category_data['name'] == '질문답변':
                default_category = category

        # 카테고리가 없는 기존 질문들에 기본 카테고리 할당
        questions_without_category = Question.objects.filter(category__isnull=True)
        count = questions_without_category.count()
        
        if count > 0 and default_category:
            questions_without_category.update(category=default_category)
            self.stdout.write(
                self.style.SUCCESS(f"{count}개의 질문에 기본 카테고리가 할당되었습니다.")
            )
        
        self.stdout.write(self.style.SUCCESS("카테고리 초기화가 완료되었습니다."))