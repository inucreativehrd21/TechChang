
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect, resolve_url
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone

from ..forms import AnswerForm
from ..models import Question, Answer
from ..utils import ANSWER_DAILY_CAP, answer_points_given, award_answer_points, deduct_points
from common.models import PointHistory

@login_required(login_url='common:login')
def answer_create(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    if request.method == "POST":
        content = request.POST.get('content', '').strip()
        if not content:
            messages.error(request, '댓글 내용을 입력해주세요.')
            return redirect('community:detail', question_id=question.id)
            
        answer = Answer()
        answer.content = content
        answer.author = request.user
        answer.create_date = timezone.now()
        answer.question = question
        answer.save()

        # 답변 작성 포인트 — 하루(한국 시간) 100P 까지(community.utils.award_answer_points)
        got = award_answer_points(request.user, answer)
        if got:
            messages.success(request, f'댓글이 등록되었습니다. (+{got} 포인트)')
        else:
            messages.success(request, f'댓글이 등록되었습니다. 오늘 받을 수 있는 댓글 포인트({ANSWER_DAILY_CAP}P)는 모두 받았어요.')
        return redirect('{}#answer_{}'.format(
            resolve_url('community:detail', question_id=question.id), answer.id))
    
    return redirect('community:detail', question_id=question.id)

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
@require_POST
def answer_delete(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    if request.user != answer.author:
        messages.error(request, '삭제권한이 없습니다')
    else:
        # 작성 때 받은 만큼만 회수 — 하루 상한에 닿아 0P 였던 답변은 지워도 차감하지 않아요
        refund = answer_points_given(answer)
        if refund:
            deduct_points(
                user=request.user,
                amount=refund,
                description=f'답변 삭제 #{answer.pk}: {answer.content[:30]}',
                reason=PointHistory.REASON_ADMIN
            )

        # Soft Delete로 통일 (하드 삭제 대신 is_deleted 플래그 사용)
        answer.is_deleted = True
        answer.deleted_date = timezone.now()
        answer.save()
        messages.success(request, f'답변이 삭제되었습니다. (-{refund} 포인트)' if refund else '답변이 삭제되었습니다.')
    return redirect('community:detail', question_id=answer.question.id)

@login_required(login_url='common:login')
@require_POST
def answer_vote(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    if request.user == answer.author:
        messages.error(request, '본인이 작성한 글은 추천할 수 없습니다')
    elif answer.voter.filter(id=request.user.id).exists():
        messages.warning(request, '이미 추천한 답변입니다')
    else:
        answer.voter.add(request.user)
        messages.success(request, '답변을 추천했습니다')
    return redirect('{}#answer_{}'.format(
                resolve_url('community:detail', question_id=answer.question.id), answer.id))
