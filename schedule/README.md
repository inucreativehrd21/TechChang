# 며칠 (schedule) — 사이트에 붙여 쓰는 일정 모듈

월간 달력, 하루 화면, 개인 일정(나만 보기), 커뮤니티 일정(운영진 등록), 사이트 피드(연구실 칼럼 공개 등), 기상청 날씨(선택), 캘린더 앱 구독(ICS)을 제공하는 Django 앱이다.

**현재 상태: 테크창에 연결하기 전.** `INSTALLED_APPS`·`urls`·상단 바에 등록하지 않았다. 아래 "연결하기"를 따르면 붙는다.

## 독립 원칙

- 다른 앱(`community`, `office`, `common`)을 import 하지 않는다. 사이트 기능과의 연결은 `settings.SCHEDULE` 의 점 경로로만 한다.
- 템플릿은 호스트의 `base.html`(PC)·`base_mobile.html`(모바일)을 상속한다. 쓰는 블록: `title`, `meta_description`, `meta_robots`, `extra_css`, `content`, `script`.
- 모바일 화면은 `templates/schedule/mobile/` 에 있다. 테크창의 모바일 로더(`common.mobile_loader`)가 자동으로 고른다.
- 설정과 URL에서 빼면 사이트에서 흔적 없이 떨어진다(테이블까지 지우려면 `migrate schedule zero`).

## 연결하기 (테크창)

1. `config/settings/base.py`
   ```python
   INSTALLED_APPS = [
       ...
       'office.apps.OfficeConfig',
       'schedule.apps.ScheduleConfig',
       ...
   ]

   SCHEDULE = {
       'FIRST_WEEKDAY': 6,                                       # 일요일 시작
       'FEED_PROVIDERS': ['office.calendar_feed.lab_schedule'],  # 연구실 일정
       'KMA_SERVICE_KEY': os.environ.get('KMA_SERVICE_KEY', ''), # 비우면 날씨 표시 꺼짐
       'KMA_REG_ID': os.environ.get('KMA_REG_ID', '11B10101'),
       'WEATHER_REGION': os.environ.get('KMA_REGION_LABEL', '서울'),
       'CALENDAR_NAME': '테크창 며칠',
   }
   ```
2. `config/urls.py` — `community` 의 루트 include 보다 **위에** 둔다.
   ```python
   path('calendar/', include('schedule.urls')),
   ```
3. `python manage.py migrate` (테이블 2개: `schedule_event`, `schedule_weathersnapshot`)
4. 상단 바 `templates/navbar_modern.html` 의 "며칠" 링크 2곳(PC 메뉴, 접힘 메뉴)을 `{% url 'schedule:month' %}` 로 바꾸고 외부 링크 아이콘과 보라색(`#7c3aed`) 아이콘을 뺀다(단일 인디고 규칙). 모바일은 `templates/base_mobile.html` 헤더에 달력 아이콘 링크를 하나 둔다(하단 탭바는 5칸 유지).
5. (선택) 날씨 — `.env` 에 `KMA_SERVICE_KEY`, `KMA_REG_ID` 를 넣고 crontab 에 추가:
   ```
   10 6,18 * * *  cd ~/projects/mysite && ~/venvs/mysite/bin/python manage.py schedule_weather
   ```
   화면은 저장된 스냅샷만 읽는다(요청마다 기상청을 부르지 않는다). 날씨를 보여 주는 곳엔 "기상청 단기예보" 출처가 함께 나온다.
6. 확인: `/calendar/`, `/calendar/day/<YYYY-MM-DD>/`, `/calendar/feed/community.ics`

## 주소

| 경로 | 화면 |
|---|---|
| `/calendar/` | 이번 달 (`schedule:month`) |
| `/calendar/<년>/<월>/` | 해당 달 (`schedule:month_at`, 검색 제외) |
| `/calendar/day/<YYYY-MM-DD>/` | 하루 (`schedule:day`) |
| `/calendar/new/?date=` | 일정 추가 (로그인) |
| `/calendar/event/<id>/` · `edit/` · `delete/` | 상세·수정·삭제 |
| `/calendar/feed/community.ics` | 구독용 iCalendar (커뮤니티 일정 + 공개 피드, 개인 일정 제외) |

## 권한

- 개인 일정: 등록한 사람만 보고 고친다. 남이 주소로 들어오면 404.
- 커뮤니티 일정: 누구나(비로그인 포함) 본다. 운영진(`is_staff`)만 등록하고, 운영진·등록자가 고친다. 일반 회원이 공개 범위를 조작해 보내도 개인 일정으로 저장된다.

## 사이트 기능을 달력에 얹기 (피드)

`(start: date, end: date, user) -> Iterable[schedule.feeds.FeedItem]` 함수를 만들고 점 경로를 `FEED_PROVIDERS` 에 넣는다. 예: `office/calendar_feed.py`.

| 필드 | 뜻 |
|---|---|
| `key` | 겹치지 않는 식별자 (ICS UID 로도 쓴다) |
| `title`, `start_date`, `end_date`, `time` | 표시 내용 |
| `icon` | Font Awesome 클래스 (`fa-feather` 등) |
| `url`, `note` | 링크, 보조 설명 |
| `public` | `False` 면 ICS 공개 구독에서 뺀다 |
| `listed` | `False` 면 달력 칸에만 그리고 '다가오는 일정' 요약에선 뺀다 (매주 반복 안내 등) |

피드 함수가 예외를 내도 달력은 그대로 뜬다(로그 `schedule.feeds` 에 남는다).

## 테스트

연결 전에는 사이트 CI 의 `manage.py test` 에서 자동으로 건너뛴다. 모듈만 검증할 때(사이트 설정 없이 최소 설정으로):

```bash
py -3.10 manage.py test schedule.tests --settings=schedule.testing.settings
```

연결한 뒤에는 사이트 테스트에 함께 돈다. 연구실 피드는 `office/test_calendar_feed.py`.

## 디자인 규칙

`.claude/skills/design-guardrails` 를 따른다 — 인디고 `#4f46e5` 하나, 라이트 전용, Pretendard 고정, 페이지 전용 CSS 는 접두사로 범위를 나눈다(`static/schedule/schedule.css`, 모든 클래스 `mc-`, 토큰은 `.mc-root` 안). 반경은 패널 16px / 버튼·입력 12px / 일정 칩 6px. 일정 종류는 색만으로 구분하지 않는다(범례 이름 + 채움 방식 + 아이콘). 인라인 스크립트가 없어 CSP 를 강제(enforce)해도 그대로 동작한다.
