# pybo/management/commands/initialize_categories.py

from django.core.management.base import BaseCommand
from pybo.models import Category

class Command(BaseCommand):
    help = '초기 카테고리 생성 (HRD, 데이터분석, 프로그래밍, 자유게시판)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='기존 카테고리를 모두 삭제하고 재생성'
        )

    def handle(self, *args, **options):
        if options['force']:
            Category.objects.all().delete()
            self.stdout.write(self.style.WARNING('✅ 기존 카테고리 모두 삭제됨'))

        categories = [
            'HRD',
            '데이터분석',
            '프로그래밍',
            '자유게시판',
        ]

        for name in categories:
            obj, created = Category.objects.get_or_create(name=name)
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ 카테고리 생성: {name}'))
            else:
                self.stdout.write(self.style.NOTICE(f' 이미 존재: {name}'))

        self.stdout.write(self.style.SUCCESS('🎉 카테고리 초기화 완료'))
