from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=25, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'pybo_category'

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

    class Meta:
        db_table = 'pybo_question'

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

    class Meta:
        db_table = 'pybo_answer'

class Comment(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    create_date = models.DateTimeField()
    modify_date = models.DateTimeField(null=True, blank=True)
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.CASCADE)
    answer = models.ForeignKey(Answer, null=True, blank=True, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='comments/', blank=True, null=True)  # 이미지 첨부

    class Meta:
        db_table = 'pybo_comment'
        ordering = ['create_date']  # 오래된 댓글부터 표시 (최신 댓글이 아래로)


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
        db_table = 'pybo_wordchaingame'
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
        db_table = 'pybo_wordchainentry'
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
        db_table = 'pybo_wordchainchatmessage'
        ordering = ['create_date']

    def __str__(self):
        return f"{self.game.title} - {self.author.username}: {self.message[:20]}"

# ========== 틱택토 게임 ==========
class TicTacToeGame(models.Model):
    """틱택토 게임 (3x3 오목)"""
    STATUS_CHOICES = [
        ('waiting', '대기중'),
        ('playing', '진행중'),
        ('finished', '종료'),
    ]
    
    title = models.CharField(max_length=200, verbose_name='게임 제목')
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_tictactoe_games', verbose_name='생성자')
    player_x = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tictactoe_x', verbose_name='플레이어 X')
    player_o = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tictactoe_o', verbose_name='플레이어 O')
    current_turn = models.CharField(max_length=1, choices=[('X', 'X'), ('O', 'O')], default='X', verbose_name='현재 턴')
    board_state = models.JSONField(default=list, verbose_name='보드 상태')  # 3x3 배열
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='waiting', verbose_name='상태')
    winner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='won_tictactoe_games', verbose_name='승자')
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    start_date = models.DateTimeField(null=True, blank=True, verbose_name='시작일')
    end_date = models.DateTimeField(null=True, blank=True, verbose_name='종료일')
    
    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        # 보드 초기화
        if not self.board_state:
            self.board_state = [['', '', ''], ['', '', ''], ['', '', '']]
        super().save(*args, **kwargs)
    
    class Meta:
        db_table = 'pybo_tictactoegame'
        verbose_name = '틱택토 게임'
        verbose_name_plural = '틱택토 게임 목록'
        ordering = ['-create_date']


# ========== 숫자야구 게임 ==========
class NumberBaseballGame(models.Model):
    """숫자야구 게임"""
    DIFFICULTY_CHOICES = [
        ('normal', '일반 (10회 시도, 시간 무제한)'),
        ('hard', '하드 (7회 시도, 5분 제한)'),
    ]

    STATUS_CHOICES = [
        ('playing', '진행중'),
        ('won', '성공'),
        ('giveup', '포기'),
        ('timeout', '시간초과'),
    ]

    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='baseball_games', verbose_name='플레이어')
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='normal', verbose_name='난이도')
    secret_number = models.CharField(max_length=4, verbose_name='정답 숫자')  # 4자리 숫자
    attempts = models.IntegerField(default=0, verbose_name='시도 횟수')
    max_attempts = models.IntegerField(default=10, verbose_name='최대 시도 횟수')
    time_limit = models.IntegerField(default=0, verbose_name='시간 제한 (초)')  # 0이면 무제한
    time_elapsed = models.IntegerField(default=0, verbose_name='경과 시간 (초)')
    consecutive_misses = models.IntegerField(default=0, verbose_name='연속 실패 횟수')  # 하드모드 페널티용
    inactivity_limit = models.IntegerField(default=0, verbose_name='비활동 제한 (초)')  # 0이면 무제한, 하드모드용
    last_activity_time = models.DateTimeField(null=True, blank=True, verbose_name='마지막 활동 시간')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='playing', verbose_name='상태', db_index=True)
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='생성일', db_index=True)
    end_date = models.DateTimeField(null=True, blank=True, verbose_name='종료일')

    def __str__(self):
        return f"{self.player.username}의 숫자야구 게임 ({self.attempts}회 시도)"

    class Meta:
        db_table = 'pybo_numberbaseballgame'
        verbose_name = '숫자야구 게임'
        verbose_name_plural = '숫자야구 게임 목록'
        ordering = ['-create_date']
        indexes = [
            models.Index(fields=['player', 'status'], name='bb_player_status_idx'),
            models.Index(fields=['player', '-create_date'], name='bb_player_date_idx'),
        ]


class NumberBaseballAttempt(models.Model):
    """숫자야구 시도 기록"""
    game = models.ForeignKey(NumberBaseballGame, on_delete=models.CASCADE, related_name='attempt_records', verbose_name='게임')
    guess_number = models.CharField(max_length=4, verbose_name='추측 숫자')
    strikes = models.IntegerField(verbose_name='스트라이크')
    balls = models.IntegerField(verbose_name='볼')
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='시도 시간')
    
    def __str__(self):
        return f"{self.guess_number} - {self.strikes}S {self.balls}B"
    
    class Meta:
        db_table = 'pybo_numberbaseballattempt'
        verbose_name = '숫자야구 시도'
        verbose_name_plural = '숫자야구 시도 기록'
        ordering = ['create_date']


# ========== 방명록 ==========
class GuestBook(models.Model):
    """포스트잇 스타일 방명록"""
    COLOR_CHOICES = [
        ('#fff475', '노란색'),
        ('#ff7eb9', '핑크색'),
        ('#7afcff', '하늘색'),
        ('#c7f0bd', '연두색'),
        ('#ffc891', '주황색'),
        ('#d9b3ff', '보라색'),
    ]

    FONT_CHOICES = [
        ('Gungsuh', '궁서체'),
        ('Nanum Gothic', '나눔고딕'),
        ('Nanum Myeongjo', '나눔명조'),
        ('Nanum Pen Script', '나눔손글씨'),
        ('Jua', '주아체'),
        ('Do Hyeon', '도현체'),
        ('Black Han Sans', '검은고딕'),
    ]

    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='guestbook_entries', verbose_name='작성자')
    content = models.TextField(max_length=200, verbose_name='내용')
    color = models.CharField(max_length=7, choices=COLOR_CHOICES, default='#fff475', verbose_name='색상')
    font_family = models.CharField(max_length=50, choices=FONT_CHOICES, default='Gungsuh', verbose_name='글꼴')
    position_x = models.IntegerField(default=0, verbose_name='X 위치')
    position_y = models.IntegerField(default=0, verbose_name='Y 위치')
    rotation = models.FloatField(default=0, verbose_name='회전 각도')  # -5 ~ 5 정도
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='작성일', db_index=True)
    modify_date = models.DateTimeField(auto_now=True, verbose_name='수정일')

    def __str__(self):
        return f"{self.author.username}의 방명록 ({self.create_date.strftime('%Y-%m-%d')})"

    class Meta:
        db_table = 'pybo_guestbook'
        verbose_name = '방명록'
        verbose_name_plural = '방명록 목록'
        ordering = ['-create_date']
        indexes = [
            models.Index(fields=['-create_date'], name='gb_create_date_idx'),
        ]


# ========== 2048 게임 ==========
class Game2048(models.Model):
    """2048 게임"""
    DIFFICULTY_CHOICES = [
        ('normal', '일반 (시간 무제한)'),
        ('hard', '하드 (비활동 시간 제한)'),
    ]

    STATUS_CHOICES = [
        ('playing', '진행중'),
        ('won', '승리'),
        ('lost', '패배'),
        ('timeout', '시간초과'),
    ]

    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='game2048_records', verbose_name='플레이어')
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='normal', verbose_name='난이도')
    board_state = models.JSONField(default=list, verbose_name='보드 상태')  # 4x4 배열
    score = models.IntegerField(default=0, verbose_name='점수')
    best_score = models.IntegerField(default=0, verbose_name='최고 점수', db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='playing', verbose_name='상태', db_index=True)
    moves = models.IntegerField(default=0, verbose_name='이동 횟수')
    inactivity_limit = models.IntegerField(default=0, verbose_name='비활동 제한 (초)')  # 0이면 무제한
    last_activity_time = models.DateTimeField(null=True, blank=True, verbose_name='마지막 활동 시간')
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='생성일', db_index=True)
    end_date = models.DateTimeField(null=True, blank=True, verbose_name='종료일')

    def __str__(self):
        return f"{self.player.username}의 2048 게임 - {self.score}점"

    def save(self, *args, **kwargs):
        # 보드 초기화 (빈 4x4 배열)
        if not self.board_state:
            self.board_state = [[0]*4 for _ in range(4)]
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'pybo_game2048'
        verbose_name = '2048 게임'
        verbose_name_plural = '2048 게임 기록'
        ordering = ['-create_date']
        indexes = [
            models.Index(fields=['player', 'status'], name='g2048_player_status_idx'),
            models.Index(fields=['player', '-best_score'], name='g2048_player_best_idx'),
            models.Index(fields=['player', '-create_date'], name='g2048_player_date_idx'),
        ]


# ========== 지뢰찾기 게임 ==========
def get_default_board_state():
    """지뢰찾기 보드 상태 기본값"""
    return {
        'mines': [],  # 지뢰 위치 [[row, col], ...]
        'revealed': [],  # 공개된 칸 [[row, col], ...]
        'flagged': [],  # 깃발 꽂은 칸 [[row, col], ...]
    }

class MinesweeperGame(models.Model):
    """지뢰찾기 게임"""
    DIFFICULTY_CHOICES = [
        ('easy', '쉬움 (9x9, 10개)'),
        ('medium', '보통 (16x16, 40개)'),
        ('hard', '어려움 (16x30, 99개)'),
    ]

    STATUS_CHOICES = [
        ('playing', '진행중'),
        ('won', '승리'),
        ('lost', '패배'),
    ]

    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='minesweeper_games', verbose_name='플레이어')
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='easy', verbose_name='난이도')
    rows = models.IntegerField(default=9, verbose_name='행 수')
    cols = models.IntegerField(default=9, verbose_name='열 수')
    mines_count = models.IntegerField(default=10, verbose_name='지뢰 수')
    board_state = models.JSONField(default=get_default_board_state, verbose_name='보드 상태')  # mines, revealed, flagged
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='playing', verbose_name='상태', db_index=True)
    time_elapsed = models.IntegerField(default=0, verbose_name='소요 시간 (초)')
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='생성일', db_index=True)
    end_date = models.DateTimeField(null=True, blank=True, verbose_name='종료일')

    def __str__(self):
        return f"{self.player.username}의 지뢰찾기 ({self.difficulty})"

    def save(self, *args, **kwargs):
        # 보드 초기화 확인
        if not self.board_state or not isinstance(self.board_state, dict):
            self.board_state = get_default_board_state()
        # 키가 없으면 추가
        if 'mines' not in self.board_state:
            self.board_state['mines'] = []
        if 'revealed' not in self.board_state:
            self.board_state['revealed'] = []
        if 'flagged' not in self.board_state:
            self.board_state['flagged'] = []
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'pybo_minesweepergame'
        verbose_name = '지뢰찾기 게임'
        verbose_name_plural = '지뢰찾기 게임 기록'
        ordering = ['-create_date']
        indexes = [
            models.Index(fields=['player', 'status'], name='ms_player_status_idx'),
            models.Index(fields=['player', 'difficulty', '-time_elapsed'], name='ms_player_diff_time_idx'),
        ]
