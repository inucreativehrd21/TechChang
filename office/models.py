from django.contrib.auth.models import User
from django.db import models


class Meeting(models.Model):
    """주간 편집회의 1회분. transcript 는 [{agent, round, text}] 목록."""
    STATUS_OPEN = 'open'          # 관리자 결정 대기
    STATUS_CLOSED = 'closed'      # 모든 안건 결정됨
    STATUS_CHOICES = [(STATUS_OPEN, '결정 대기'), (STATUS_CLOSED, '결정 완료')]

    week_start = models.DateField(db_index=True, verbose_name='회의 주차(월요일)')
    held_at = models.DateTimeField(auto_now_add=True, verbose_name='개최일시')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    briefing = models.TextField(blank=True, verbose_name='팀장 지표 브리핑')
    transcript = models.JSONField(default=list, verbose_name='회의록')
    snapshot = models.JSONField(default=dict, verbose_name='수집 데이터 스냅샷')
    summary = models.TextField(blank=True, verbose_name='결론 요약')
    # 공개 연구실에 보여 줄 요약. summary 는 운영 지표(CTR·평균순위)와 내부 판단이 섞인
    # 관리 문서라 그대로 내보낼 수 없다. 독자에게 "무엇을 쓰기로 했는지"만 전한다.
    public_summary = models.TextField(blank=True, verbose_name='공개용 요약')

    class Meta:
        ordering = ['-held_at']
        verbose_name = '편집회의'
        verbose_name_plural = '편집회의'

    def __str__(self):
        return f'{self.week_start} 편집회의'

    @property
    def pending_count(self):
        return self.decisions.filter(chosen_key='').count()


class Decision(models.Model):
    """회의 안건 하나. options 는 [{key, title, detail, proposed_by}] — 관리자가 하나를 고른다."""
    KIND_COLUMN = 'column'     # topic 필드로 hrd/data/coding 구분
    KIND_SERIES = 'series'
    KIND_DEV = 'dev'
    KIND_OPS = 'ops'           # 서버·보안 — 공개 페이지에는 노출하지 않음
    KIND_CHOICES = [
        (KIND_COLUMN, '칼럼 주제'), (KIND_SERIES, '시리즈 방향'),
        (KIND_DEV, '개발·개선'), (KIND_OPS, '운영·보안'),
    ]

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='decisions')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, db_index=True)
    topic = models.CharField(max_length=10, blank=True, db_index=True, verbose_name='칼럼 분야 키')
    question = models.CharField(max_length=300, verbose_name='안건')
    options = models.JSONField(default=list)
    chosen_key = models.CharField(max_length=20, blank=True, db_index=True)
    chosen_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    chosen_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, verbose_name='관리자 메모')
    # 공개용 한 줄 소개. options[].detail 은 "프레임 중복을 피함" 처럼 편집 회의 내부
    # 판단이라 독자에게는 의미가 없다. 무엇을 다루는 글인지만 남긴다.
    public_note = models.CharField(max_length=300, blank=True, verbose_name='공개용 소개')
    consumed_at = models.DateTimeField(null=True, blank=True, verbose_name='칼럼에 반영된 시각')

    class Meta:
        ordering = ['meeting', 'kind', 'id']

    def __str__(self):
        return f'[{self.get_kind_display()}] {self.question}'

    @property
    def chosen(self):
        for o in self.options:
            if o.get('key') == self.chosen_key:
                return o
        return None

    @property
    def is_public(self):
        return self.kind != self.KIND_OPS


class ColumnDraft(models.Model):
    """연구팀이 제작한 칼럼 1편의 작업 기록. 발행되면 question 이 채워진다."""
    STATUS_PUBLISHED = 'published'
    STATUS_HOLD = 'hold'          # 편집 심사 미달 → 운영자 검수 대기
    STATUS_REVISING = 'revising'  # 운영자 코멘트 반영 재작성 진행 중
    STATUS_REJECTED = 'rejected'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PUBLISHED, '발행'), (STATUS_HOLD, '검수 대기'), (STATUS_REVISING, '재작성 중'),
        (STATUS_REJECTED, '반려'), (STATUS_FAILED, '실패'),
    ]

    topic = models.CharField(max_length=10, db_index=True)
    brief = models.CharField(max_length=300, blank=True, verbose_name='회의에서 정한 주제')
    decision = models.ForeignKey(Decision, null=True, blank=True, on_delete=models.SET_NULL, related_name='drafts')
    subject = models.CharField(max_length=200, blank=True)
    content = models.TextField(blank=True, verbose_name='최종 본문(마크다운)')
    chart_path = models.CharField(max_length=300, blank=True, verbose_name='차트 이미지 (media 상대경로)')
    check_report = models.JSONField(default=dict, verbose_name='팩트체크 보고')
    qa_report = models.JSONField(default=dict, verbose_name='편집 심사 결과')
    chart_note = models.CharField(max_length=300, blank=True, verbose_name='시각화 결과·사유')
    admin_note = models.TextField(blank=True, verbose_name='운영자 수정 지시')
    revisions = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, db_index=True)
    question = models.OneToOneField('community.Question', null=True, blank=True, on_delete=models.SET_NULL, related_name='office_draft')
    # 연재 회차 원고면 채운다(office.series_pipeline). target_question 은 리메이크 대상 — 발행 시 그 글을 제자리 갱신
    series_key = models.CharField(max_length=20, blank=True, db_index=True, verbose_name='연재 시리즈 키')
    episode_number = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='연재 회차')
    target_question = models.ForeignKey('community.Question', null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name='+', verbose_name='리메이크 대상 글')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.topic}] {self.subject or self.brief}'

    @property
    def qa_score(self):
        """편집 심사 총점(100점). 구버전 레코드는 10점 척도라 100점으로 환산해 보여 준다."""
        v = self.qa_report.get('score')
        if v is None:
            return None
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None
        return v * 10 if v <= 10 else v

    @property
    def qa_verdict(self):
        return self.qa_report.get('verdict', '')

    @property
    def qa_fatal(self):
        return self.qa_report.get('fatal') or []

    @property
    def rubric_rows(self):
        """[(항목명, 1~5점)] — 관리 화면 표시용."""
        from office.pipeline import RUBRIC
        if self.qa_report.get('rubric') == 'series':
            from office.series_pipeline import SERIES_RUBRIC as RUBRIC
        scores = self.qa_report.get('scores') or {}
        return [(desc.split(' — ')[0], scores.get(k)) for k, (_, desc) in RUBRIC.items() if scores.get(k) is not None]


class WorkLog(models.Model):
    """에이전트 활동 한 줄. 연구실 페이지 말풍선과 관리자 작업 로그의 원천."""
    agent = models.CharField(max_length=10, db_index=True)
    action = models.CharField(max_length=40, db_index=True)   # meeting/draft/chart/check/qa/publish/hold ...
    text = models.CharField(max_length=300)
    # 공개 연구실에 보여 줄 문장. 원문(text)에는 운영자 지시문·점수·정비 내역이 섞여 있어
    # 그대로 내보낼 수 없다. publiclog 가 걸러 다듬은 결과만 여기에 채운다.
    # 페이지가 폴링하므로 조회 때마다 만들지 않고, 만들어 둔 것을 읽기만 한다.
    public_text = models.CharField(max_length=300, blank=True, default='', verbose_name='공개용 문장')
    draft = models.ForeignKey(ColumnDraft, null=True, blank=True, on_delete=models.CASCADE, related_name='logs')
    meeting = models.ForeignKey(Meeting, null=True, blank=True, on_delete=models.CASCADE, related_name='logs')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.agent}: {self.text}'


class Task(models.Model):
    """정비반 작업 카드 — 편집회의 결정·로그 지적사항·수동 등록을 한 백로그로 모은다.

    흐름: backlog → (이슈 생성) → approved → working → pr_open → done
    패치는 서버에서 git worktree 안에서만 만들고, 운영 코드와 배포는 건드리지 않는다.
    """
    SRC_MEETING = 'meeting'
    SRC_FINDING = 'finding'
    SRC_MANUAL = 'manual'
    SRC_CHOICES = [(SRC_MEETING, '편집회의 결정'), (SRC_FINDING, '로그 지적사항'), (SRC_MANUAL, '직접 등록')]

    KIND_DEV = 'dev'
    KIND_OPS = 'ops'
    KIND_BUG = 'bug'
    KIND_CHORE = 'chore'
    KIND_CHOICES = [(KIND_DEV, '개발·개선'), (KIND_OPS, '운영·보안'), (KIND_BUG, '버그'), (KIND_CHORE, '정리')]

    ST_BACKLOG = 'backlog'        # 등록됨, 운영자 확인 대기
    ST_APPROVED = 'approved'      # 운영자 승인 — 패치 대기
    ST_WORKING = 'working'        # 서버에서 패치 생성 중
    ST_PR = 'pr_open'             # PR 생성됨 (CI·머지는 사람)
    ST_DONE = 'done'
    ST_REJECTED = 'rejected'
    ST_FAILED = 'failed'
    ST_CHOICES = [
        (ST_BACKLOG, '접수'), (ST_APPROVED, '승인'), (ST_WORKING, '작업 중'),
        (ST_PR, 'PR 열림'), (ST_DONE, '완료'), (ST_REJECTED, '반려'), (ST_FAILED, '실패'),
    ]

    source = models.CharField(max_length=10, choices=SRC_CHOICES, default=SRC_MANUAL, db_index=True)
    decision = models.ForeignKey(Decision, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    finding = models.ForeignKey('common.LogFinding', null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')

    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, verbose_name='배경·완료 조건')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_DEV, db_index=True)
    priority = models.CharField(max_length=2, default='P2', db_index=True)   # P1 급함 / P2 보통 / P3 나중
    status = models.CharField(max_length=10, choices=ST_CHOICES, default=ST_BACKLOG, db_index=True)

    triage = models.JSONField(default=dict, verbose_name='분류 결과(담당·난이도·완료조건)')
    hints = models.JSONField(default=list, verbose_name='관련 파일 후보')
    plan = models.JSONField(default=dict, verbose_name='원인·수정 계획')
    result = models.JSONField(default=dict, verbose_name='패치·검증 결과')
    attempts = models.PositiveSmallIntegerField(default=0)

    issue_number = models.PositiveIntegerField(null=True, blank=True)
    issue_url = models.URLField(blank=True)
    branch = models.CharField(max_length=120, blank=True)
    pr_url = models.URLField(blank=True)
    note = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['priority', '-created_at']
        verbose_name = '정비 작업'
        verbose_name_plural = '정비 작업'

    def __str__(self):
        return f'[{self.priority}] {self.title}'

    @property
    def is_open(self):
        return self.status in (self.ST_BACKLOG, self.ST_APPROVED, self.ST_WORKING, self.ST_FAILED)

    @property
    def step_rows(self):
        """관리 화면용: 단계별 진행 [(이름, 상태)]"""
        r = self.result or {}
        done = lambda k: 'ok' if r.get(k) else ''
        return [('조사', done('plan')), ('패치', done('edits')), ('검증', done('verify')), ('PR', 'ok' if self.pr_url else '')]


class StageRun(models.Model):
    """칼럼 제작·회의의 단계별 산출물 기록 (내부 전용 — 공개 페이지에 내보내지 않는다).

    ColumnDraft 는 최종본만 담아, 평론·1차 심사·초고·자료집이 덮어써져 사라졌다.
    단계마다 한 줄씩 쌓아 무엇이 어떻게 바뀌었는지 남긴다. 기록은 메인 스레드만 한다
    (office.recorder.StageRecorder) — 병렬 단계의 워커는 결과만 돌려준다.
    """
    run_id = models.UUIDField(db_index=True)
    draft = models.ForeignKey(ColumnDraft, null=True, blank=True, on_delete=models.CASCADE, related_name='stages')
    question = models.ForeignKey('community.Question', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='+')
    meeting = models.ForeignKey(Meeting, null=True, blank=True, on_delete=models.CASCADE, related_name='stages')
    seq = models.PositiveSmallIntegerField()
    stage = models.CharField(max_length=40, db_index=True)
    agent = models.CharField(max_length=10, blank=True)
    # 에이전트 간 메시지(의뢰·반려·자료집·메모·이의·판정)면 보낸 쪽·받는 쪽과 종류
    sender = models.CharField(max_length=10, blank=True)
    recipient = models.CharField(max_length=10, blank=True)
    kind = models.CharField(max_length=20, blank=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, default='ok')   # ok|failed|skipped|degraded
    output = models.JSONField(default=dict)
    text_digest = models.CharField(max_length=64, blank=True)
    seconds = models.FloatField(default=0)
    calls = models.JSONField(default=list)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['run_id', 'seq']
        verbose_name = '제작 단계 기록'
        verbose_name_plural = '제작 단계 기록'

    def __str__(self):
        return f'{self.stage}#{self.seq} ({self.agent or "-"}, {self.status})'


class VerifiedFact(models.Model):
    """검증 원장 — 검증관이 웹에서 원문을 대조한 주장(office.ledger).

    같은 통계가 칼럼마다 다시 나오는데, 매번 처음부터 확인하면 판정이 흔들린다(같은 수치가 한 번은
    verified, 다음엔 unverifiable). 확인한 사실과 근거 URL 을 쌓아 다음 팩트체크에 함께 보여 준다.
    """
    claim = models.CharField(max_length=500, verbose_name='주장')
    claim_key = models.CharField(max_length=200, db_index=True, verbose_name='중복 판별 키')
    status = models.CharField(max_length=15, db_index=True)       # verified|wrong|outdated
    note = models.TextField(blank=True)
    urls = models.JSONField(default=list)
    method = models.CharField(max_length=20, blank=True, verbose_name='확인 방법')
    times_seen = models.PositiveIntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen']
        verbose_name = '검증 원장'
        verbose_name_plural = '검증 원장'

    def __str__(self):
        return f'[{self.status}] {self.claim[:60]}'


class ColumnDigest(models.Model):
    """칼럼 지도의 한 칸 — 칼럼별 소주제·키워드·요약(office.digest).

    칼럼이 발행·수정되면 저장 신호(office.signals)가 본문 해시를 비교해, 바뀌었으면 백그라운드로
    update_column_map 을 띄워 다시 만든다. 관리자 '칼럼 지도' 페이지(office:column_map)가 이 표를 읽는다.
    """
    question = models.OneToOneField('community.Question', on_delete=models.CASCADE, related_name='digest')
    subtopic = models.CharField(max_length=60, verbose_name='소주제')
    keywords = models.JSONField(default=list, verbose_name='키워드')
    summary = models.TextField(verbose_name='요약')
    content_hash = models.CharField(max_length=40, verbose_name='요약한 본문의 해시')
    source = models.CharField(max_length=20, default='lab', verbose_name='작성 경로')   # lab|import
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '칼럼 지도 항목'
        verbose_name_plural = '칼럼 지도 항목'

    def __str__(self):
        return f'[{self.subtopic}] {self.question_id}'
