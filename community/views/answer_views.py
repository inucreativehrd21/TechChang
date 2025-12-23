
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect, resolve_url
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from ..forms import AnswerForm
from ..models import Question, Answer
from common.models import Profile, PointHistory

@login_required(login_url='common:login')
def answer_create(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    if request.method == "POST":
        form = AnswerForm(request.POST, request.FILES)
        if form.is_valid():
            answer = form.save(commit=False)
            answer.author = request.user  # author 속성에 로그인 계정 저장
            answer.create_date = timezone.now()
            answer.question = question
            answer.save()
            
            # 답변 작성 포인트 지급 (20포인트)
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.points += 20
            profile.save()
            
            # 포인트 히스토리 기록
            PointHistory.objects.create(
                user=request.user,
                amount=20,
                reason=PointHistory.REASON_ADMIN,
                description=f'답변 작성: {answer.content[:30]}'
            )
            
            messages.success(request, '답변이 등록되었습니다. (+20 포인트)')
            return redirect('{}#answer_{}'.format(
                resolve_url('community:detail', question_id=question.id), answer.id))
    else:
        form = AnswerForm()
    context = {'question': question, 'form': form}
    return render(request, 'community/question_detail.html', context)

@login_required(login_url='common:login')
def answer_modify(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    if request.user != answer.author:
        messages.error(request, '수정권한이 없습니다')
        return redirect('community:detail', question_id=answer.question.id)
    if request.method == "POST":
        form = AnswerForm(request.POST, request.FILES, instance=answer)
        if form.is_valid():
            answer = form.save(commit=False)
            answer.modify_date = timezone.now()
            answer.save()
            return redirect('{}#answer_{}'.format(
                resolve_url('community:detail', question_id=answer.question.id), answer.id))
    else:
        form = AnswerForm(instance=answer)
    context = {'answer': answer, 'form': form}
    return render(request, 'community/answer_form.html', context)

@login_required(login_url='common:login')
def answer_delete(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    if request.user != answer.author:
        messages.error(request, '삭제권한이 없습니다')
    else:
        # 포인트 차감 (작성 시 지급된 20포인트 회수)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.points = max(0, profile.points - 20)
        profile.save()
        
        # 포인트 히스토리 기록
        PointHistory.objects.create(
            user=request.user,
            amount=-20,
            reason=PointHistory.REASON_ADMIN,
            description=f'답변 삭제: {answer.content[:30]}'
        )
        
        answer.delete()
        messages.success(request, '답변이 삭제되었습니다. (-20 포인트)')
    return redirect('community:detail', question_id=answer.question.id)

@login_required(login_url='common:login')
def answer_vote(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    if request.user == answer.author:
        messages.error(request, '본인이 작성한 글은 추천할수 없습니다')
    else:
        answer.voter.add(request.user)
    return redirect('{}#answer_{}'.format(
                resolve_url('community:detail', question_id=answer.question.id), answer.id))