from django.core.management.base import BaseCommand
from pybo.models import Question


class Command(BaseCommand):
    help = '앨범 카테고리 질문에 대한 갤러리 뷰를 위한 확장 지원'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-sample',
            action='store_true',
            help='앨범 카테고리 샘플 데이터 생성',
        )

    def handle(self, *args, **options):
        from pybo.models import Category
        from django.contrib.auth.models import User
        
        # 앨범 카테고리 생성
        album_category, created = Category.objects.get_or_create(
            name='앨범',
            defaults={
                'description': '사진과 이미지를 공유하는 갤러리 공간입니다. 추억을 함께 나누어요!'
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ 앨범 카테고리 생성됨: {album_category.name}')
            )
        else:
            self.stdout.write(
                self.style.NOTICE(f'📂 앨범 카테고리 이미 존재: {album_category.name}')
            )
            
        # 자유게시판 카테고리도 생성
        free_category, created = Category.objects.get_or_create(
            name='자유게시판',
            defaults={
                'description': '자유로운 주제로 소통하는 게시판입니다.'
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ 자유게시판 카테고리 생성됨: {free_category.name}')
            )
        else:
            self.stdout.write(
                self.style.NOTICE(f'📂 자유게시판 카테고리 이미 존재: {free_category.name}')
            )

        if options['create_sample']:
            # 관리자 사용자 확인
            admin_user = User.objects.filter(is_superuser=True).first()
            if not admin_user:
                self.stdout.write(
                    self.style.ERROR('❌ 관리자 사용자를 찾을 수 없습니다. 먼저 슈퍼유저를 생성해주세요.')
                )
                return
                
            # 샘플 앨범 게시물 생성
            sample_album_post = Question.objects.create(
                subject='📸 테크창 활동 사진 모음',
                content='''안녕하세요! 테크창 활동 사진들을 공유합니다.

**이미지 업로드 방법:**
1. 질문 작성 시 하단의 "이미지 업로드" 버튼 클릭
2. 사진 선택 후 업로드
3. 내용에 설명 추가

여러분의 소중한 추억도 함께 나누어 주세요! 🎉''',
                author=admin_user,
                category=album_category
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'✅ 앨범 샘플 게시물 생성됨: {sample_album_post.subject}')
            )
            
        self.stdout.write(
            self.style.SUCCESS('🎉 앨범 및 자유게시판 카테고리 설정 완료!')
        )