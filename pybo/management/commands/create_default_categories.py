from django.core.management.base import BaseCommand
from pybo.models import Category

class Command(BaseCommand):
    help = 'Create default categories for PyBo'

    def handle(self, *args, **options):
        # 기본 카테고리 생성
        default_categories = [
            {'name': '일반', 'description': '일반적인 질문과 답변'},
            {'name': 'Python', 'description': 'Python 프로그래밍 관련 질문'},
            {'name': 'Django', 'description': 'Django 웹 프레임워크 관련 질문'},
            {'name': 'JavaScript', 'description': 'JavaScript 관련 질문'},
            {'name': '데이터베이스', 'description': '데이터베이스 관련 질문'},
            {'name': '웹개발', 'description': '웹 개발 전반적인 질문'},
            {'name': '기타', 'description': '기타 개발 관련 질문'},
        ]

        created_count = 0
        for cat_data in default_categories:
            category, created = Category.objects.get_or_create(
                name=cat_data['name'],
                defaults={'description': cat_data['description']}
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created category: {category.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Category already exists: {category.name}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} new categories')
        )