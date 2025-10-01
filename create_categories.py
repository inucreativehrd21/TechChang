#!/usr/bin/env python
import os
import sys

# Django 설정
if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    
    import django
    django.setup()
    
    from pybo.models import Category
    
    # 앨범 카테고리 생성
    album_category, created = Category.objects.get_or_create(
        name='앨범',
        defaults={'description': '사진과 이미지를 공유하는 갤러리 공간입니다.'}
    )
    
    if created:
        print("✅ 앨범 카테고리가 성공적으로 생성되었습니다.")
    else:
        print("📂 앨범 카테고리가 이미 존재합니다.")
    
    # 자유게시판 카테고리 생성
    free_category, created = Category.objects.get_or_create(
        name='자유게시판',
        defaults={'description': '자유로운 주제로 소통하는 게시판입니다.'}
    )
    
    if created:
        print("✅ 자유게시판 카테고리가 성공적으로 생성되었습니다.")
    else:
        print("📂 자유게시판 카테고리가 이미 존재합니다.")
    
    # 모든 카테고리 출력
    print("\n현재 등록된 카테고리:")
    for category in Category.objects.all():
        print(f"- {category.name}: {category.description}")