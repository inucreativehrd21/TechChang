import os
import openai
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from pybo.models import Question, Answer

class Command(BaseCommand):
    help = 'Generate AI answers for questions without recent activity'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days without activity to trigger AI response (default: 7)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=5,
            help='Maximum number of AI answers to generate (default: 5)'
        )

    def handle(self, *args, **options):
        # OpenAI API 키 확인
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key:
            self.stdout.write(
                self.style.ERROR('OPENAI_API_KEY not found in settings')
            )
            return

        # OpenAI 클라이언트 초기화
        client = openai.OpenAI(api_key=api_key)

        days_threshold = options['days']
        max_answers = options['limit']
        
        # AI 사용자 생성 또는 가져오기
        ai_user, created = User.objects.get_or_create(
            username='AI_Assistant',
            defaults={
                'email': 'ai@pybo.com',
                'first_name': 'AI',
                'last_name': 'Assistant'
            }
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Created AI user: {ai_user.username}')
            )

        # 일정 기간 동안 답변이 없는 질문 찾기
        cutoff_date = timezone.now() - timedelta(days=days_threshold)
        questions_without_recent_answers = Question.objects.filter(
            create_date__lt=cutoff_date,
            answer__isnull=True
        ).exclude(
            # 이미 AI 답변이 있는 질문 제외
            answer__is_ai=True
        )[:max_answers]

        count = 0
        for question in questions_without_recent_answers:
            try:
                # ChatGPT에게 답변 요청
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {
                            "role": "system",
                            "content": "당신은 프로그래밍 Q&A 커뮤니티의 도움이 되는 AI 어시스턴트입니다. 질문에 대해 정확하고 도움이 되는 답변을 한국어로 제공해주세요. 답변은 친근하고 이해하기 쉽게 작성해주세요."
                        },
                        {
                            "role": "user",
                            "content": f"질문: {question.subject}\n\n내용: {question.content}\n\n이 질문에 대해 도움이 되는 답변을 작성해주세요."
                        }
                    ],
                    max_tokens=1000,
                    temperature=0.7
                )

                ai_answer_content = response.choices[0].message.content
                
                # AI 답변을 데이터베이스에 저장
                ai_answer = Answer.objects.create(
                    author=ai_user,
                    question=question,
                    content=f"{ai_answer_content}\n\n---\n*이 답변은 AI에 의해 자동 생성되었습니다.*",
                    create_date=timezone.now(),
                    is_ai=True
                )

                count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Generated AI answer for question: "{question.subject[:50]}..."'
                    )
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Failed to generate answer for question "{question.subject[:50]}...": {str(e)}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully generated {count} AI answers')
        )