from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=25, unique=True)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.name

class Question(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='author_question')
    subject = models.CharField(max_length=200)
    content = models.TextField()
    create_date = models.DateTimeField()
    modify_date = models.DateTimeField(null=True, blank=True)
    voter = models.ManyToManyField(User, related_name='voter_question')  # 추천인 추가
    view_count = models.PositiveIntegerField(default=0)  # 조회수 추가
    category = models.ForeignKey(Category, on_delete=models.PROTECT)  # 카테고리 필수
    image = models.ImageField(upload_to='questions/', blank=True, null=True)  # 이미지 첨부
    file = models.FileField(upload_to='question_files/', blank=True, null=True)  # 파일 첨부
    is_deleted = models.BooleanField(default=False)  # Soft delete 필드
    deleted_date = models.DateTimeField(null=True, blank=True)  # 삭제 날짜
    is_locked = models.BooleanField(default=False, help_text="회원 전용 글 (로그인 필요)")  # 글 잠금 기능

    def __str__(self):
            return self.subject

    @property
    def filename(self):
        """파일명만 반환"""
        if self.file:
            import os
            return os.path.basename(self.file.name)
        return None

class Answer(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='author_answer')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    content = models.TextField()
    create_date = models.DateTimeField()
    modify_date = models.DateTimeField(null=True, blank=True)
    voter = models.ManyToManyField(User, related_name='voter_answer')
    is_ai = models.BooleanField(default=False)  # AI가 생성한 답변인지 표시
    image = models.ImageField(upload_to='answers/', blank=True, null=True)  # 이미지 첨부
    is_deleted = models.BooleanField(default=False)  # Soft delete 필드
    deleted_date = models.DateTimeField(null=True, blank=True)  # 삭제 날짜

class Comment(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    create_date = models.DateTimeField()
    modify_date = models.DateTimeField(null=True, blank=True)
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.CASCADE)
    answer = models.ForeignKey(Answer, null=True, blank=True, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='comments/', blank=True, null=True)  # 이미지 첨부


# 끝말잇기 게임 모델
class WordChainGame(models.Model):
    """끝말잇기 게임 세션"""
    STATUS_CHOICES = [
        ('waiting', '대기중'),
        ('active', '진행중'),
        ('finished', '종료됨'),
    ]

    title = models.CharField(max_length=100, default="끝말잇기 게임")
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_games')
    participants = models.ManyToManyField(User, related_name='wordchain_games', blank=True)
    max_participants = models.IntegerField(default=4, help_text="최대 참가자 수")
    create_date = models.DateTimeField(auto_now_add=True)
    start_date = models.DateTimeField(null=True, blank=True, help_text="게임 시작 시간")
    end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    current_turn = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='current_turn_games', help_text="현재 차례인 사용자")
    participant_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-create_date']
    
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"
    
    @property
    def last_word(self):
        """마지막 단어 반환"""
        last_entry = self.entries.order_by('-create_date').first()
        return last_entry.word if last_entry else None
    
    @property
    def expected_first_char(self):
        """다음에 입력해야 할 첫 글자"""
        last_word = self.last_word
        return last_word[-1] if last_word else None

    def get_next_turn(self):
        """다음 차례 사용자 반환"""
        participants_list = list(self.participants.all().order_by('id'))
        if not participants_list:
            return None

        if not self.current_turn:
            # 첫 턴은 생성자
            return self.creator if self.creator in participants_list else participants_list[0]

        try:
            current_index = participants_list.index(self.current_turn)
            next_index = (current_index + 1) % len(participants_list)
            return participants_list[next_index]
        except ValueError:
            return participants_list[0]

    def advance_turn(self):
        """턴을 다음 사용자로 넘김"""
        self.current_turn = self.get_next_turn()
        self.save()

    def can_join(self, user):
        """사용자가 참가 가능한지 확인"""
        if self.status != 'waiting':
            return False, "이미 시작되었거나 종료된 게임입니다."
        if self.participants.count() >= self.max_participants:
            return False, "참가자가 꽉 찼습니다."
        if self.participants.filter(id=user.id).exists():
            return False, "이미 참가 중입니다."
        return True, "참가 가능"

    def can_start(self, user):
        """게임을 시작할 수 있는지 확인"""
        if user != self.creator:
            return False, "방장만 게임을 시작할 수 있습니다."
        if self.status != 'waiting':
            return False, "이미 시작되었거나 종료된 게임입니다."
        if self.participants.count() < 2:
            return False, "최소 2명 이상의 참가자가 필요합니다."
        return True, "시작 가능"


class WordChainEntry(models.Model):
    """끝말잇기 게임의 개별 단어 항목"""
    game = models.ForeignKey(WordChainGame, on_delete=models.CASCADE, related_name='entries')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    word = models.CharField(max_length=50)
    create_date = models.DateTimeField(auto_now_add=True)
    is_valid = models.BooleanField(default=True)  # 단어의 유효성
    
    class Meta:
        ordering = ['create_date']
        unique_together = ['game', 'word']  # 같은 게임에서 중복 단어 방지
    
    def __str__(self):
        return f"{self.game.title} - {self.word} ({self.author.username})"


class WordChainChatMessage(models.Model):
    """끝말잇기 게임 내 채팅 메시지"""
    game = models.ForeignKey(WordChainGame, on_delete=models.CASCADE, related_name='chat_messages')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    create_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['create_date']

    def __str__(self):
        return f"{self.game.title} - {self.author.username}: {self.message[:20]}"