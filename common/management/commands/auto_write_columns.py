"""
HRD / 데이터분석 / 프로그래밍 트렌드 칼럼 자동 작성 커맨드

사용법:
  python manage.py auto_write_columns                   # 3개 주제 전체 작성
  python manage.py auto_write_columns --topic hrd       # HRD만
  python manage.py auto_write_columns --topic data      # 데이터분석만
  python manage.py auto_write_columns --topic coding    # 프로그래밍만
  python manage.py auto_write_columns --dry-run         # 실제 게시 없이 콘솔 출력

서버 cron (매주 화/목 오전 10시, 각 1개 주제):
  0 10 * * 2  .../python manage.py auto_write_columns --topic hrd
  0 10 * * 4  .../python manage.py auto_write_columns --topic data
  0 10 * * 6  .../python manage.py auto_write_columns --topic coding

환경변수:
  ANTHROPIC_API_KEY  - Anthropic API 키 (필수)
"""
import textwrap
from datetime import datetime

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

BOT_USERNAME = 'techchang연구팀'
BOT_DISPLAY_NAME = '테크창 연구팀'

# ────────────────────────────────────────────────────────────
# 주제별 설정
# ────────────────────────────────────────────────────────────
TOPICS = {
    'hrd': {
        'category_name': 'HRD',
        'label': 'HRD 트렌드',
        'system_prompt': (
            '당신은 인천대학교 창의인재개발학과 전공심화연구모임 "테크창"의 HRD 칼럼니스트입니다. '
            'HRD(인적자원개발), 조직학습, 성인교육, 역량개발, 리더십, 교육훈련 분야를 심층 분석하며, '
            '학술적 근거와 현장 사례를 균형 있게 결합하여 독자에게 실질적 인사이트를 제공합니다. '
            '문체는 전문 저널 칼럼 수준으로 격식 있되 읽기 쉽게, 존댓말로 작성합니다.'
        ),
        'topic_hint': 'HRD(인적자원개발), 조직학습, 역량개발, 교육훈련, 인재관리, 리더십, 조직문화',
        'audience': '인적자원개발 관련 학과 학생 및 HRD 실무 초보자',
    },
    'data': {
        'category_name': '데이터분석',
        'label': '데이터분석 트렌드',
        'system_prompt': (
            '당신은 인천대학교 창의인재개발학과 전공심화연구모임 "테크창"의 데이터분석 칼럼니스트입니다. '
            '데이터 분석, AI/ML, 비즈니스 인텔리전스, HR Analytics 분야를 심층 분석하며, '
            '최신 기술 트렌드를 HRD·경영 관점에서 재해석하여 실무자에게 유용한 시각을 제공합니다. '
            '문체는 전문 저널 칼럼 수준으로 격식 있되 읽기 쉽게, 존댓말로 작성합니다.'
        ),
        'topic_hint': '데이터분석, AI/ML, HR Analytics, 비즈니스 인텔리전스, 시각화, 예측 모델',
        'audience': '데이터분석에 관심 있는 학생 및 비전공자 실무 입문자',
    },
    'coding': {
        'category_name': '프로그래밍',
        'label': '코딩 트렌드',
        'system_prompt': (
            '당신은 인천대학교 창의인재개발학과 전공심화연구모임 "테크창"의 테크 칼럼니스트입니다. '
            '프로그래밍 언어, 프레임워크, 개발 방법론, 오픈소스 생태계를 심층 분석하며, '
            'HRD·교육 관점에서 왜 이 기술을 배워야 하는지 맥락을 함께 제공합니다. '
            '문체는 전문 저널 칼럼 수준으로 격식 있되 읽기 쉽게, 존댓말로 작성합니다.'
        ),
        'topic_hint': '프로그래밍 언어, 프레임워크, 개발 도구, DevOps, AI 코딩 도구, 오픈소스',
        'audience': '프로그래밍을 처음 배우는 학생 및 주니어 개발자',
    },
}

# ────────────────────────────────────────────────────────────
# 칼럼 구조 템플릿 (모든 주제 공통)
# ────────────────────────────────────────────────────────────
COLUMN_STRUCTURE = """
칼럼 구조는 아래를 엄격히 따르세요.

출력 형식 (첫 두 줄은 반드시 이 형식이어야 합니다):
TITLE: [칼럼 제목 - 구체적이고 흥미를 끄는 한국어 제목, 30자 이내]
---
[이하 칼럼 본문: 마크다운 형식]

칼럼 본문 구성 (순서 고정):

1. **리드 문단** (헤더 없음, 2~3문장)
   - 독자가 멈추게 만드는 핵심 질문 또는 놀라운 사실로 시작
   - 이번 칼럼에서 다룰 트렌드와 그 중요성을 압축해 제시

2. **## 왜 지금인가** (배경/맥락)
   - 해당 트렌드가 부상한 사회적·기술적 배경
   - 구체적 수치, 연구 결과, 또는 산업 동향을 인용
   - 블록인용(`>`)으로 핵심 데이터나 인사이트를 강조

3. **## [트렌드 핵심 제목]** (본론)
   - 트렌드의 실체, 핵심 개념, 작동 원리를 깊이 있게 설명
   - 필요시 `###` 하위 섹션으로 세분화
   - 실제 사례나 적용 예시 포함

4. **## 현장의 변화** (사례 분석)
   - 국내외 조직/기업/학계의 실제 사례 2~3개
   - 구체적이고 검증 가능한 사례 위주

5. **## 시사점: 우리가 갖춰야 할 것** (실무 적용)
   - 독자 맞춤 실행 가능한 제언 3~5개를 글머리 기호(`-`)로 정리

6. **## 맺음말**
   - 핵심 메시지 재강조 + 독자에게 행동을 촉구하는 마무리 문장

7. **## 참고 자료**
   - 본문에서 인용하거나 근거로 삼은 자료(보고서·논문·기관 통계·기사 등)를 글머리 기호(`-`)로 3~6개 정리
   - 실제로 존재하는 신뢰할 수 있는 출처만 기재 (예: `- LinkedIn Learning, 「2025 Workplace Learning Report」`)
   - **확인되지 않은 구체적 URL이나 허위 통계 출처는 절대 지어내지 말 것.** 불확실하면 기관·보고서의 일반적 명칭 수준으로만 표기
   - 본문에서 언급한 출처와 이 목록이 일치하도록 작성

8. 마지막 구분선 + 서명
   ```
   ---
   *테크창 연구팀 | 인천대학교 창의인재개발학과 전공심화연구모임*
   *본 칼럼은 AI 보조로 작성되었으며, 수치·출처는 참고용입니다.*
   ```

추가 지침:
- 전체 분량: 본문 기준 1,200~1,600자 (참고 자료 제외, 마크다운 문자 기준)
- `#` H1 헤더는 절대 사용하지 않음 (제목은 TITLE: 라인에만)
- `**볼드**`로 핵심 용어 강조, 단 남용 금지
- 반말·구어체 금지, 존댓말로 일관
- 실제로 존재하거나 신뢰할 수 있는 트렌드만 다룰 것
"""


def _get_or_create_bot_user() -> User:
    user, created = User.objects.get_or_create(
        username=BOT_USERNAME,
        defaults={
            'email': 'research@techchang.com',
            'first_name': '연구팀',
            'last_name': '테크창',
            'is_active': True,
        },
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


def _parse_output(raw: str) -> tuple:
    """
    TITLE: [제목]
    ---
    [본문]
    형식에서 제목과 본문을 분리. 파싱 실패시 fallback.
    """
    lines = raw.splitlines()
    title = ''
    body_start = 0

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
    return title or '자동 생성 칼럼', body


def _recent_subjects(topic_key: str, limit: int = 20) -> list:
    """해당 카테고리에서 봇이 이미 작성한 최근 칼럼 제목 목록 (중복 회피용)."""
    from community.models import Question

    topic = TOPICS[topic_key]
    return list(
        Question.objects.filter(
            author__username=BOT_USERNAME,
            category__name=topic['category_name'],
            is_deleted=False,
        ).order_by('-create_date').values_list('subject', flat=True)[:limit]
    )


def _generate_column(topic_key: str, recent_titles: list | None = None) -> dict:
    """Claude Sonnet API를 호출해 칼럼을 생성하고 {subject, content}를 반환."""
    from common.services.claude import ClaudeModel, ask

    topic = TOPICS[topic_key]
    today_str = datetime.now().strftime('%Y년 %m월 %d일')

    avoid_block = ''
    if recent_titles:
        joined = '\n'.join(f'- {t}' for t in recent_titles)
        avoid_block = (
            '\n\n**[이미 다룬 주제 - 반드시 피하세요]**\n'
            '아래는 우리가 이전에 발행한 칼럼 제목입니다. '
            '이들과 핵심 소재·키워드가 겹치지 않는, 완전히 새로운 트렌드를 선정하세요:\n'
            f'{joined}\n'
        )

    user_prompt = (
        f'오늘 날짜: {today_str}\n'
        f'담당 분야: {topic["topic_hint"]}\n'
        f'독자: {topic["audience"]}\n\n'
        f'위 분야에서 현재 가장 주목받고 있는 트렌드나 이슈 하나를 선정하여 '
        f'아래 형식에 맞게 전문 칼럼을 작성해 주세요.'
        f'{avoid_block}\n'
        f'{COLUMN_STRUCTURE}'
    )

    raw_content = ask(
        user_prompt,
        system=topic['system_prompt'],
        model=ClaudeModel.SONNET,
        max_tokens=3000,
    )

    subject, body = _parse_output(raw_content.strip())
    return {'subject': subject, 'content': body}


class Command(BaseCommand):
    help = 'HRD, 데이터분석, 프로그래밍 트렌드 칼럼을 Claude Sonnet으로 자동 작성하여 게시합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--topic',
            choices=['hrd', 'data', 'coding', 'all'],
            default='all',
            help='작성할 주제 (기본: all - 3개 전부)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 게시 없이 생성된 칼럼을 콘솔에만 출력',
        )

    def handle(self, *args, **options):
        from community.models import Category, Question

        topic_arg = options['topic']
        dry_run = options['dry_run']

        target_keys = list(TOPICS.keys()) if topic_arg == 'all' else [topic_arg]

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY-RUN] 실제 게시는 하지 않습니다.\n'))

        bot_user = None if dry_run else _get_or_create_bot_user()

        for key in target_keys:
            topic = TOPICS[key]
            label = topic['label']
            self.stdout.write(f'[{datetime.now():%H:%M:%S}] {label} 칼럼 생성 중 (claude-sonnet-4-6)...')

            recent_titles = _recent_subjects(key)
            if recent_titles:
                self.stdout.write(f'  이미 다룬 주제 {len(recent_titles)}건 회피 적용')

            try:
                result = _generate_column(key, recent_titles)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  오류: {exc}'))
                continue

            subject = result['subject']
            content = result['content']

            self.stdout.write(f'  제목: {subject}')
            self.stdout.write(f'  분량: {len(content)}자')

            if dry_run:
                sep = '=' * 60
                self.stdout.write(sep)
                self.stdout.write(textwrap.shorten(content, width=600, placeholder=' ...'))
                self.stdout.write(sep + '\n')
                continue

            try:
                category = Category.objects.get(name=topic['category_name'])
            except Category.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(
                        f"  카테고리 '{topic['category_name']}' 를 DB에서 찾을 수 없습니다. "
                        'python manage.py loaddata community/fixtures/categories.json 을 실행하세요.'
                    )
                )
                continue

            question = Question.objects.create(
                author=bot_user,
                subject=subject,
                content=content,
                create_date=timezone.now(),
                category=category,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  게시 완료 [{topic["category_name"]}] {subject} (id={question.pk})'
                )
            )

        self.stdout.write(self.style.SUCCESS('\n자동 칼럼 작성 완료.'))
