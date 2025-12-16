
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from ..forms import QuestionForm
from ..models import Question

@login_required(login_url='common:login')
def question_create(request):
    if request.method == 'POST':
        form = QuestionForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                question = form.save(commit=False)
                question.author = request.user  # author 속성에 로그인 계정 저장
                question.create_date = timezone.now()
                question.save()
                messages.success(request, '게시글이 성공적으로 등록되었습니다.')
                return redirect('community:index')
            except Exception as e:
                messages.error(request, f'게시글 저장 중 오류가 발생했습니다: {str(e)}')
                print(f"Question creation error: {e}")  # 서버 로그용
        else:
            messages.error(request, '폼 유효성 검사에 실패했습니다. 입력 내용을 확인해주세요.')
    else:
        form = QuestionForm()
    context = {'form': form}
    return render(request, 'community/question_form.html', context)

@login_required(login_url='common:login')
def question_modify(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    if request.user != question.author:
        messages.error(request, '수정권한이 없습니다')
        return redirect('community:detail', question_id=question.id)
    if request.method == "POST":
        form = QuestionForm(request.POST, request.FILES, instance=question)
        if form.is_valid():
            question = form.save(commit=False)
            question.modify_date = timezone.now()  # 수정일시 저장
            question.save()
            return redirect('community:detail', question_id=question.id)
    else:
        form = QuestionForm(instance=question)
    context = {'form': form}
    return render(request, 'community/question_form.html', context)

@login_required(login_url='common:login')
def question_delete(request, question_id):
    """질문 안전 삭제 (Soft Delete)"""
    question = get_object_or_404(Question, pk=question_id, is_deleted=False)
    
    # 권한 검증
    if request.user != question.author:
        messages.error(request, '삭제권한이 없습니다')
        return redirect('community:detail', question_id=question.id)
    
    if request.method == 'POST':
        # Soft delete 실행
        question.is_deleted = True
        question.deleted_date = timezone.now()
        question.save()
        messages.success(request, '질문이 삭제되었습니다.')
        return redirect('community:index')
    
    # GET 요청시 확인 페이지 표시
    context = {'question': question}
    return render(request, 'community/question_delete_confirm.html', context)

@login_required(login_url='common:login')
def question_vote(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    if request.user == question.author:
        messages.error(request, '본인이 작성한 글은 추천할수 없습니다')
    else:
        question.voter.add(request.user)
    return redirect('community:detail', question_id=question.id)