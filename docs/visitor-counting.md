# 방문자 집계 기준

방문 집계는 `common/visitor_tracking.py`의 `VisitorTrackingMiddleware`에서 처리해요.
기존 홈 전용 집계를 옮겨 칼럼·게시판·게임 등으로 바로 들어와도 포함해요.

- 한국 시간(`Asia/Seoul`) 날짜 기준으로 브라우저 세션당 하루 한 번 집계해요.
- GET 요청으로 정상 응답(200)을 받은 HTML 페이지를 대상으로 해요.
- 리다이렉트·오류·POST·HEAD·JSON·다운로드·정적 파일·미디어·API·관리자 경로는 제외해요.
- AJAX·fetch·iframe·prefetch 요청은 요청 헤더로 제외해요. 포트폴리오 raw 뷰는 헤더가 없어도 제외해요.
- 알려진 봇·크롤러·모니터링 도구와 빈 User-Agent는 제외해요. User-Agent 판별은 위조되거나 알려지지 않은 봇까지 보장하지 않아요.
- 기존 `visited_YYYY-MM-DD` 세션 표시와 `DailyVisitor` 테이블을 유지하므로 적용 당일 기존 방문도 중복 집계하지 않아요. 과거 날짜의 세션 표시는 다음 집계 때 정리해요.
- 홈에는 이번 방문을 포함한 숫자를 표시하고, DB에는 응답 렌더링이 성공한 뒤 기록해요. 집계 시 포트폴리오 공용 통계 캐시도 무효화해요.

실제 사람을 식별하는 통계는 아니에요. 다른 기기·브라우저·시크릿 창·쿠키 삭제 시 추가 집계될 수 있고, 같은 세션의 동시 요청도 중복 가능성이 있어요. 누적 방문은 일별 방문 수의 합이에요. 과거 누락 방문을 소급 복구하지 않으므로, 적용 전후 통계 비교 시 집계 범위 변경을 고려해야 해요.

DB 스키마 변경이나 마이그레이션은 필요 없어요. 운영 반영은 별도 배포 시점부터 적용돼요.

검증: `py -3.10 manage.py test common.test_visitor_tracking community.test_site_owner common.test_crawler_access --settings=config.settings.local --noinput`

## 통계 사용처와 호환성

홈·문승현 HTML 포트폴리오·관리자 서버 모니터·방문자 주간/월간 리포트·서버 리포트·연구실 지표는 같은 `DailyVisitor(date, visitor_count)`를 읽어요. `visitors_today`·`visitors_total` 키와 쉼표 표시 형식, `data-tc-stat` 태그는 유지해요. 과거 집계 행과 업로드 HTML 원문을 변경하지 않아요.

포트폴리오 직접 방문은 바깥 상세 페이지 응답에서 집계하고, 이후 raw iframe이 최신 통계를 읽어요. iframe 재요청은 방문을 늘리지 않아요. 다른 회원의 HTML은 기존처럼 통계 치환 없이 표시해요. 기존 통계 캐시는 60초이며, LocMemCache를 사용하는 다른 워커는 기존과 같이 최대 60초 늦게 갱신될 수 있어요.

서버 리포트의 방문자 항목은 한국 날짜(`timezone.localdate(now)`)로 오늘·어제를 조회해요. 기존 UTC 날짜 조회 때문에 한국 시간 00~09시에 다른 화면과 날짜가 어긋날 수 있던 부분을 맞췄어요. 이메일 발송이나 외부 AI 호출을 추가하지 않아요.
