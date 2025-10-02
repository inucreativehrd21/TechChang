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
    is_deleted = models.BooleanField(default=False)  # Soft delete 필드
    deleted_date = models.DateTimeField(null=True, blank=True)  # 삭제 날짜

    def __str__(self):
            return self.subject

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
        ('active', '진행중'),
        ('finished', '종료됨'),
    ]
    
    title = models.CharField(max_length=100, default="끝말잇기 게임")
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_games')
    create_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
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