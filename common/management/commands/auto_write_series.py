"""
연재 칼럼(시리즈) 자동 작성 커맨드

단편 칼럼(auto_write_columns)과 달리, 미리 짜둔 목차를 따라 회차를 순서대로 발행한다.
각 회차 생성 시 이전 회차들의 요약을 프롬프트에 넣어 연속성을 유지한다.

사용법:
  python manage.py auto_write_series                    # 다음 미발행 회차 1개 발행
  python manage.py auto_write_series --series django    # 특정 시리즈 지정
  python manage.py auto_write_series --episode 3        # 특정 회차 강제 (재작성/보충)
  python manage.py auto_write_series --dry-run          # 게시 없이 콘솔 출력

서버 cron (격주 월요일 오전 10시 예시 — 홀수 주만 실행하도록 주 번호로 게이팅):
  0 10 * * 1  [ $(( ($(date +\%s) / 604800) \% 2 )) -eq 0 ] && .../python manage.py auto_write_series

환경변수:
  ANTHROPIC_API_KEY  - Anthropic API 키 (필수)
"""
import textwrap
from datetime import datetime

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

BOT_USERNAME = 'techchang연구팀'

# ────────────────────────────────────────────────────────────
# 시리즈 정의 (여기에 새 시리즈를 추가하면 됨)
# ────────────────────────────────────────────────────────────
SERIES = {
    'django': {
        'slug': 'django-for-vibe-coders',
        'title': 'AI가 짜준 Django, 이제 알고 씁니다',
        'subtitle': '바이브코딩으로 만든 코드를 눈높이로 통역해드립니다',
        'description': (
            'AI로 앱은 만들어봤지만 코드가 왜 돌아가는지는 모르는 입문자를 위해, '
            'Django가 만들어준 코드를 한 줄씩 통역하는 연재.'
        ),
        'category_name': '프로그래밍',
        'audience': (
            '바이브코딩(AI로 코드 생성)으로 결과물은 만들어봤지만, '
            '그 코드가 왜 동작하는지·왜 깨지는지는 모르는 코딩 입문자'
        ),
        'system_prompt': (
            '당신은 인천대학교 창의인재개발학과 전공심화연구모임 "테크창"의 테크 칼럼니스트입니다. '
            '이 연재의 독자는 Cursor·Claude·Copilot 같은 AI 도구로 코드를 "짜본" 적은 있지만, '
            '프레임워크의 동작 원리는 모르는 완전 초보입니다. '
            '핵심 톤은 "AI가 방금 짜준 이 코드가 무슨 뜻인지 통역해준다"입니다. '
            '문법 정의부터 나열하지 말고, 독자가 이미 마주친 코드/에러에서 출발해 역방향으로 설명하세요. '
            '전문 용어는 반드시 일상 비유로 풀고, 존댓말로 친근하되 정확하게 작성합니다.'
        ),
    },
}

# ────────────────────────────────────────────────────────────
# 시리즈별 목차 (회차 순서 = 발행 순서)
#   no        : 회차 번호 (0 = 오리엔테이션)
#   title     : 회차 제목
#   focus     : 이 회차가 통역할 핵심 개념
#   code_hook : 'AI가 짜준 코드' 소재 (본문 출발점)
#   site_demo : 이 사이트에서 확인할 실제 예제
# ────────────────────────────────────────────────────────────
OUTLINES = {
    'django': [
        {'no': 0, 'title': '오리엔테이션: 우리가 만들 것',
         'focus': '이 연재의 목표와 전체 지도, 완주 후 얻는 것',
         'code_hook': 'AI에게 "게시판 만들어줘" 했을 때 나오는 폴더 구조 미리보기',
         'site_demo': '지금 보고 있는 이 게시판(테크창)이 완성본'},
        {'no': 1, 'title': 'Django는 대체 뭘 대신 해주나',
         'focus': '프레임워크가 자동으로 해주는 일 = 우리가 안 짜도 되는 코드',
         'code_hook': 'django-admin startproject 실행 후 생긴 파일들',
         'site_demo': '프로젝트 폴더 구조(config/, community/)'},
        {'no': 2, 'title': 'URL 한 줄의 정체 (라우팅)',
         'focus': '주소창 URL과 실행되는 코드가 어떻게 연결되는가',
         'code_hook': "urls.py의 path('question/', views.list) 한 줄",
         'site_demo': '질문 목록 페이지 주소'},
        {'no': 3, 'title': '뷰 = "요청 들어오면 뭐 할지"',
         'focus': '함수 하나가 하나의 화면을 책임진다는 개념',
         'code_hook': 'def index(request): 로 시작하는 뷰 함수',
         'site_demo': '게시글 목록이 뜨는 과정'},
        {'no': 4, 'title': '템플릿 = HTML에 데이터 끼우기',
         'focus': '고정 HTML에 변하는 데이터를 꽂는 원리',
         'code_hook': '{{ question.subject }} 와 {% for %} 태그',
         'site_demo': '질문 리스트가 반복 출력되는 화면'},
        {'no': 5, 'title': '모델 = AI가 만든 표(테이블)의 실체',
         'focus': '데이터베이스 테이블 = 파이썬 클래스라는 발상',
         'code_hook': 'class Question(models.Model): 정의',
         'site_demo': '질문 하나가 DB에 저장되는 구조'},
        {'no': 6, 'title': '마이그레이션 = "DB야, 나 바뀌었어"',
         'focus': '모델을 고치면 왜 migrate를 또 해야 하는가',
         'code_hook': 'makemigrations / migrate 명령과 그 결과',
         'site_demo': '필드 하나 추가해보는 실습'},
        {'no': 7, 'title': '폼과 CSRF = 글쓰기가 되는 원리',
         'focus': '입력 → 저장까지의 흐름과 보안 토큰의 정체',
         'code_hook': '{% csrf_token %} 와 POST 요청 처리',
         'site_demo': '질문 등록 폼'},
        {'no': 8, 'title': '로그인은 어떻게 나를 "기억"하나',
         'focus': '세션과 인증 — 새로고침해도 로그인이 유지되는 이유',
         'code_hook': '@login_required 데코레이터와 세션 쿠키',
         'site_demo': '이 사이트 로그인/로그아웃'},
        {'no': 9, 'title': '정리 + 내 손으로 기능 하나 추가하기',
         'focus': '지금까지 배운 조각을 합쳐 작은 기능을 직접 완성',
         'code_hook': '종합 미션: 조회수/좋아요 같은 작은 기능 붙이기',
         'site_demo': '독자가 직접 만들어 Q&A에 공유'},
    ],
}

# ────────────────────────────────────────────────────────────
# 회차 공통 구조 템플릿 (모든 회차가 동일한 골격 → 연재 일관성)
# ────────────────────────────────────────────────────────────
EPISODE_STRUCTURE = """
회차 구조는 아래 골격을 엄격히 따르세요. 모든 회차가 같은 구조여야 독자가 리듬을 익힙니다.

출력 형식 (첫 두 줄은 반드시 이 형식):
TITLE: [회차 제목 - 아래 지정 제목을 그대로 사용하거나 자연스럽게 다듬어 30자 이내]
---
[이하 본문: 마크다운]

본문 구성 (순서 고정):

1. **🎬 지난 이야기** (0편이면 이 섹션 생략, 헤더 없이 2~3문장)
   - 이전 회차 요약을 한 문단으로. 처음 온 독자도 따라올 수 있게.

2. **😵 이런 적 있죠?** (리드, 헤더 없음)
   - 바이브코딩 중 실제로 겪는 상황이나 에러로 시작해 독자를 끌어당김
   - 이번 회차에서 풀어줄 궁금증을 질문형으로 제시

3. **## 🤖 AI가 짜준 코드**
   - 실제로 AI에게 시킬 법한 프롬프트 한 줄 + 그 결과로 나오는 코드 블록
   - 코드는 짧게(5~15줄), 이 사이트의 실제 코드에서 따온 느낌으로

4. **## 🔍 한 줄씩 통역** (본론)
   - 위 코드를 초보 눈높이로 한 조각씩 해설. 이 회차의 핵심.
   - 전문 용어는 반드시 일상 비유로 풀 것 (예: "URL 라우팅 = 건물 안내판")
   - 필요시 `###` 하위 섹션 사용

5. **## ⚠️ 자주 깨지는 지점**
   - 초보가 이 부분에서 실제로 만나는 에러 1~2개와 원인·해결을 예방주사처럼
   - 블록인용(`>`)으로 에러 메시지 예시를 보여주면 좋음

6. **## 🎮 직접 해보기**
   - 이 사이트(테크창)에서 확인할 것 또는 따라 할 작은 미션 1개
   - "막히면 Q&A 게시판에 질문하세요" 로 커뮤니티 참여 유도

7. **## ⏭️ 다음 편 예고**
   - 다음 회차에서 다룰 내용을 한 문장 클리프행어로

8. 마지막 구분선 + 서명
   ```
   ---
   *📚 시리즈: {series_title} · {episode_label}*
   *테크창 연구팀 | 인천대학교 창의인재개발학과 전공심화연구모임*
   *본 칼럼은 AI 보조로 작성되었으며, 코드·예시는 학습용입니다.*
   ```

추가 지침:
- 전체 분량: 본문 기준 1,400~1,900자 (단편 칼럼보다 조금 길고 풍부하게)
- `#` H1 헤더 금지 (제목은 TITLE: 라인에만)
- 반말 금지, 존댓말 일관. 다만 딱딱하지 않고 친근하게.
- 코드 블록은 ```python / ```html 등 언어를 명시
- 실제로 동작하는 정확한 코드만. 지어낸 API·존재하지 않는 문법 금지.
"""


def _get_or_create_bot_user() -> User:
    user, created = User.objects.get_or_create(
        username=BOT_USERNAME,
        defaults={'email': 'research@techchang.com', 'first_name': '연구팀',
                  'last_name': '테크창', 'is_active': True},
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


def _parse_output(raw: str) -> tuple:
    """TITLE: / --- / 본문 형식에서 제목·본문 분리. 실패 시 fallback."""
    lines = raw.splitlines()
    title, body_start = '', 0
    for i, line in enumerate(lines):
        if line.startswith('TITLE:'):
            title = line[6:].strip()[:200]
        elif line.strip() == '---' and title:
            body_start = i + 1
            break
    if not title:
        for line in lines:
            stripped = line.lstrip('#').strip()
            if stripped:
                title = stripped[:200]
                break
    body = '\n'.join(lines[body_start:]).lstrip('\n')
    return title or '연재 칼럼', body


def _previous_summaries(series_obj, limit: int = 4) -> str:
    """직전 회차들의 제목 + 앞부분을 요약 블록으로 만들어 연속성 컨텍스트 제공."""
    episodes = list(series_obj.published_episodes)[-limit:]
    if not episodes:
        return ''
    parts = []
    for ep in episodes:
        snippet = textwrap.shorten(ep.content.replace('\n', ' '), width=220, placeholder=' …')
        parts.append(f'- {ep.episode_number}편 「{ep.subject}」: {snippet}')
    return (
        '\n\n**[이전 회차 요약 - 반드시 이어지도록 작성하세요]**\n'
        '아래는 지금까지 발행한 회차입니다. "지난 이야기" 섹션에서 자연스럽게 이어받고, '
        '이미 설명한 개념은 반복하지 말고 전제로 활용하세요:\n' + '\n'.join(parts) + '\n'
    )


def _generate_episode(series_key: str, series_obj, outline: dict) -> dict:
    from common.services.claude import ClaudeModel, ask

    cfg = SERIES[series_key]
    no = outline['no']
    total = len(OUTLINES[series_key]) - 1  # 0편 제외한 본편 최대 번호
    episode_label = '0편 · 오리엔테이션' if no == 0 else f'{no}편 (총 {total}편 중)'

    structure = EPISODE_STRUCTURE.format(series_title=cfg['title'], episode_label=episode_label)

    user_prompt = (
        f'시리즈: {cfg["title"]} — {cfg["subtitle"]}\n'
        f'독자: {cfg["audience"]}\n\n'
        f'이번 회차: {no}편 「{outline["title"]}」\n'
        f'이 회차가 통역할 핵심: {outline["focus"]}\n'
        f'출발점이 될 코드 소재: {outline["code_hook"]}\n'
        f'이 사이트에서 확인할 예제: {outline["site_demo"]}\n'
        f'{_previous_summaries(series_obj)}'
        f'\n위 내용으로 아래 형식에 맞춰 회차를 작성하세요.\n{structure}'
    )

    raw = ask(user_prompt, system=cfg['system_prompt'], model=ClaudeModel.SONNET, max_tokens=4000)
    subject, body = _parse_output(raw.strip())
    return {'subject': subject, 'content': body}


class Command(BaseCommand):
    help = '연재 칼럼(시리즈)의 다음 회차를 Claude로 자동 작성해 발행합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--series', choices=list(SERIES.keys()), default='django',
                            help='발행할 시리즈 키 (기본: django)')
        parser.add_argument('--episode', type=int, default=None,
                            help='특정 회차 강제 지정 (기본: 다음 미발행 회차)')
        parser.add_argument('--dry-run', action='store_true',
                            help='게시 없이 생성 결과만 콘솔 출력')

    def handle(self, *args, **options):
        from community.models import Category, ColumnSeries, Question

        key = options['series']
        cfg = SERIES[key]
        outlines = OUTLINES[key]
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY-RUN] 실제 게시는 하지 않습니다.\n'))

        try:
            category = Category.objects.get(name=cfg['category_name'])
        except Category.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"카테고리 '{cfg['category_name']}' 없음."))
            return

        # 시리즈 레코드 확보 (없으면 생성)
        series_obj, created = ColumnSeries.objects.get_or_create(
            slug=cfg['slug'],
            defaults={'title': cfg['title'], 'subtitle': cfg['subtitle'],
                      'description': cfg['description'], 'audience': cfg['audience'],
                      'category': category, 'total_episodes': len(outlines)},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'시리즈 생성: {series_obj.title}'))

        # 발행할 회차 결정
        target_no = options['episode'] if options['episode'] is not None else series_obj.next_episode_number
        outline = next((o for o in outlines if o['no'] == target_no), None)
        if outline is None:
            self.stdout.write(self.style.SUCCESS(
                f'발행할 회차가 없습니다. (요청 회차 {target_no} · 총 {len(outlines)}편 완결)'))
            return

        self.stdout.write(f'[{datetime.now():%H:%M:%S}] {target_no}편 「{outline["title"]}」 생성 중...')

        try:
            result = _generate_episode(key, series_obj, outline)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'  오류: {exc}'))
            return

        self.stdout.write(f'  제목: {result["subject"]}')
        self.stdout.write(f'  분량: {len(result["content"])}자')

        if dry_run:
            sep = '=' * 60
            self.stdout.write(sep)
            self.stdout.write(textwrap.shorten(result['content'], width=800, placeholder=' ...'))
            self.stdout.write(sep + '\n')
            return

        bot_user = _get_or_create_bot_user()
        question = Question.objects.create(
            author=bot_user,
            subject=result['subject'],
            content=result['content'],
            create_date=timezone.now(),
            category=category,
            series=series_obj,
            episode_number=target_no,
        )
        self.stdout.write(self.style.SUCCESS(
            f'  발행 완료 [{cfg["title"]}] {target_no}편 (id={question.pk})'))
