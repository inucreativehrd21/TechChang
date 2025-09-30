"""
카테고리 시스템 초기화 및 설정
- 기존 카테고리 완전 삭제 후 새로 생성
- 데이터 무결성 보장
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from pybo.models import Category, Question
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = '카테고리 시스템을 완전히 초기화하고 새로운 카테고리를 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='기존 데이터 삭제를 강제 실행합니다.',
        )

    def handle(self, *args, **options):
        # 새로운 카테고리 정의
        NEW_CATEGORIES = [
            {
                'name': 'HRD',
                'description': '인적자원개발, 교육, 훈련 관련 질문과 답변을 다룹니다.'
            },
            {
                'name': '데이터분석',
                'description': '데이터 분석, 통계, 머신러닝, 비즈니스 인텔리전스 관련 내용을 다룹니다.'
            },
            {
                'name': '프로그래밍',
                'description': '프로그래밍 언어, 개발 도구, 소프트웨어 개발 관련 질문을 다룹니다.'
            }
        ]

        if not options['force']:
            self.stdout.write(
                self.style.WARNING('⚠️  이 작업은 기존 카테고리를 모두 삭제합니다!')
            )
            confirm = input('계속하시겠습니까? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write('작업이 취소되었습니다.')
                return

        try:
            with transaction.atomic():
                # 1. 기존 질문들을 임시로 기본 카테고리에 할당
                self.stdout.write('📝 기존 질문 데이터 보호 중...')
                
                # 임시 카테고리 생성
                temp_category, created = Category.objects.get_or_create(
                    name='임시',
                    defaults={'description': '마이그레이션용 임시 카테고리'}
                )
                
                # 기존 질문들을 임시 카테고리로 이동
                questions_updated = Question.objects.exclude(category=temp_category).update(
                    category=temp_category
                )
                self.stdout.write(f'   → {questions_updated}개 질문을 임시 카테고리로 이동')

                # 2. 기존 카테고리 삭제 (임시 제외)
                self.stdout.write('🗑️  기존 카테고리 삭제 중...')
                deleted_count = Category.objects.exclude(name='임시').delete()[0]
                self.stdout.write(f'   → {deleted_count}개 카테고리 삭제됨')

                # 3. 새 카테고리 생성
                self.stdout.write('✨ 새 카테고리 생성 중...')
                created_categories = []
                for cat_data in NEW_CATEGORIES:
                    category = Category.objects.create(**cat_data)
                    created_categories.append(category)
                    self.stdout.write(f'   ✅ {category.name}: {category.description}')

                # 4. 기존 질문들을 새 카테고리에 분배
                self.stdout.write('🔄 질문 카테고리 재할당 중...')
                questions = Question.objects.filter(category=temp_category)
                
                if questions.exists():
                    # 기본적으로 첫 번째 카테고리(HRD)에 할당
                    default_category = created_categories[0]  # HRD
                    questions.update(category=default_category)
                    self.stdout.write(f'   → {questions.count()}개 질문을 "{default_category.name}"에 할당')

                # 5. 임시 카테고리 삭제
                temp_category.delete()
                self.stdout.write('🧹 임시 카테고리 정리 완료')

                # 6. 결과 요약
                self.stdout.write('\n' + '='*50)
                self.stdout.write(self.style.SUCCESS('✅ 카테고리 시스템 초기화 완료!'))
                self.stdout.write('\n📊 현재 카테고리 현황:')
                
                for category in Category.objects.all():
                    question_count = category.question_set.count()
                    self.stdout.write(f'   • {category.name}: {question_count}개 질문')
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ 오류 발생: {str(e)}')
            )
            raise