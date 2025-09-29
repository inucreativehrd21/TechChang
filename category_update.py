from pybo.models import Category, Question
from django.db import transaction

# 기존 질문들의 카테고리 정보 저장
questions_mapping = []
for question in Question.objects.select_related('category').all():
    old_category = question.category.name
    if old_category in ['Python', 'Django', 'JavaScript', '웹개발']:
        new_category = '프로그래밍'
    elif old_category in ['데이터베이스']:
        new_category = '데이터분석'
    elif old_category in ['강좌', '공지사항']:
        new_category = 'HRD'
    else:
        new_category = '프로그래밍'
    questions_mapping.append((question.id, new_category))

print(f"총 {len(questions_mapping)}개의 질문 매핑 완료")

# 기존 카테고리 삭제
Category.objects.all().delete()

# 새 카테고리 생성
hrd_category = Category.objects.create(name='HRD', description='인적자원개발, 교육, 훈련 관련 질문')
data_category = Category.objects.create(name='데이터분석', description='데이터 분석, 통계, 머신러닝 관련 질문')
programming_category = Category.objects.create(name='프로그래밍', description='프로그래밍 언어, 개발, 코딩 관련 질문')

category_map = {'HRD': hrd_category, '데이터분석': data_category, '프로그래밍': programming_category}

# 질문들의 카테고리 업데이트
updated_count = 0
for question_id, new_category_name in questions_mapping:
    try:
        question = Question.objects.get(id=question_id)
        question.category = category_map[new_category_name]
        question.save()
        updated_count += 1
    except Question.DoesNotExist:
        continue

print(f"카테고리 교체 완료! {updated_count}개 질문 업데이트됨")
print(f"- HRD: {Category.objects.get(name='HRD').question_set.count()}개 질문")
print(f"- 데이터분석: {Category.objects.get(name='데이터분석').question_set.count()}개 질문")
print(f"- 프로그래밍: {Category.objects.get(name='프로그래밍').question_set.count()}개 질문")