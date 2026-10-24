# Claude → Codex 구독 폴백

Claude Code 구독을 우선 사용하고 **명시적인 사용량 한도 오류만** Codex 구독으로 넘겨요.
인증·설정·시간 초과·출력 해석 오류는 공급자 전환으로 숨기지 않아요.
AI 응답 호출 단위로 전환하므로, 이미 끝난 집필이나 검증 결과를 처음부터 다시 만들지 않아요.

## 설정

```dotenv
CLAUDE_BACKEND=cli
CLAUDE_CLI_FALLBACK=false
AI_ALLOW_PAID_API=false
AI_FALLBACK_BACKEND=codex_cli
CODEX_MODEL=gpt-6.1-sol
CODEX_REASONING_EFFORT=medium
CODEX_HOME=/absolute/private/path/to/codex-auth
CODEX_CLI_BIN=/absolute/path/to/codex
CODEX_CLI_TIMEOUT=1200
CODEX_LOCK_TIMEOUT=1200
```

`AI_ALLOW_PAID_API`는 기본적으로 꺼져 있어요. 구독 폴백을 선택한 동안에는 이 값을 켜거나
예전 `CLAUDE_CLI_FALLBACK`을 켜도 유료 API 경로로 넘어가지 않아요.
이 제한은 **API 키 과금 경로**에 적용돼요. ChatGPT 계정에 별도로 구매한 크레딧이나
자동 충전이 설정되어 있는지는 계정의 사용량·결제 설정에서 따로 확인해야 해요.

## 서버 로그인

설치된 CLI에서 `CODEX_HOME`을 위와 같이 지정한 상태로 실행해요.

```bash
codex login --device-auth
codex login status
```

서버에서 직접 인증해요. 개발 PC와 같은 `auth.json`을 공유하지 않아요.
인증 저장소는 저장소 밖에 두고 디렉터리 700, 인증 파일 600으로 제한해요.
CLI가 갱신한 인증 파일을 유지하고, 매 실행마다 옛 복사본으로 덮어쓰지 않아요.

실행 어댑터는 먼저 ChatGPT 로그인 여부를 확인해요. 로그인하지 않았거나 API 키 인증이면
모델 요청을 시작하지 않아요. CLI 사용자 설정·프로젝트 지침·셸·브라우저 자동화·앱·플러그인·
하위 에이전트는 끄고, 요청에 따라 내장 웹 검색·열람만 켜요. 임시 작업 폴더와 읽기 전용
샌드박스를 사용하며 DB·메일·API 비밀키를 자식 프로세스에 전달하지 않아요.

## 공급자 상태와 예약 작업

`office.AiProviderState`가 공급자별 재확인 시각과 실패 종류를 저장해요.
0013 마이그레이션은 기존 Claude 한도 기록 중 아직 유효한 것을 옮겨요.
LocMem 캐시를 사용하지 않으므로 cron·웹 프로세스가 같은 상태를 봐요.

- Claude가 한도 중이어도 Codex를 확인할 수 있으면 예약 작업은 진행해요.
- 둘 다 사용 불가일 때만 더 먼저 확인할 수 있는 공급자의 시각까지 미뤄요.
- 정확한 초기화 시각을 알 수 없으면 한도는 30분 뒤 재확인해요. 확정 해제 시각은 아니에요.
- Claude 복구 확인은 한 워커만 맡고, Codex 실행은 프로세스 간 잠금으로 직렬화해요.
- 뒤늦게 끝난 성공이 다른 워커의 새 실패 기록을 지우지 않도록 revision을 비교해요.
- 로그·회의 메일은 실제 사용한 모델과 `cli`(Claude)/`codex_cli`를 구분해요.

## 비공개 품질 비교

```bash
python manage.py evaluate_subscriptions --backend claude --output-dir logs/eval-claude
python manage.py evaluate_subscriptions --backend codex --effort medium --output-dir logs/eval-codex-medium
python manage.py evaluate_subscriptions --backend codex --effort high --output-dir logs/eval-codex-high
```

Windows 로컬에서는 `python` 대신 `py -3.10 -X utf8`을 사용해요.
`--cases decision,factcheck`처럼 일부 항목만 실행할 수 있어요.
고정 입력 12건과 실제 연구원 역할 지침을 사용하고, DB·메일·공개 원고를 변경하지 않아요.
완료한 동일 입력은 재사용하고, 한도·인증 실패가 발생하면 나머지 호출은 중단해요.
각 항목의 응답 원문·자동 점검·토큰·시간과 `summary.json`을 비공개 파일로 남겨요.
`--recheck-only`를 붙이면 기존 응답만 다시 검사하며 모델 사용량은 들지 않아요.

자동 점검 통과는 Sonnet과의 품질 동등성을 뜻하지 않아요. 작성 모델을 가리고 원문을
비교해 문체·근거·수치·논리·실행 가능성을 검토해야 해요. 웹 항목은 실제 원문 열람 여부도
확인해요. 마지막으로 실제 칼럼 파이프라인을 `office_publish --topic coding --dry-run`으로
검증하고 기존 심사·보완·발행 기준을 유지해요. `--prepare`는 자동 공개 대기 상태를
만들 수 있으므로 비공개 비교에 사용하지 않아요.

OCI의 고정 입력 12건에서 Claude는 11건, Codex medium·high는 각각 12건을 통과했어요.
Claude의 미통과 항목은 두 선택지 요청에 세 개를 제시한 경우예요. 이 수치는 형식·필수 조건의
기초 검사이며 모델 성능의 순위나 동등성을 보장하지 않아요. 긴 웹 조사를 포함한 high 제작
시험은 Plus 한도를 소진해 끝나지 않았어요. 기본값은 medium이며 실제 제작의 심사 기준은
낮추지 않아요. 두 구독 모두 한도이면 API 과금 없이 보류하고 다음 확인 시각에 재시도해요.

## 적용 순서

1. 관련 회귀 테스트, Django check, 마이그레이션 일치 검사를 통과해요.
2. 운영과 분리된 코드 경로에서 ARM64 CLI·구독 로그인·선택 모델·도구 정책을 확인해요.
3. 고정 입력 비교와 실제 제작의 dry-run 결과를 검토해요.
4. 운영 DB 백업과 변경 파일 백업 후 0013 마이그레이션을 적용해요.
5. 외부 처리자가 OpenAI로 추가되는 만큼 개인정보 처리방침의 위탁·국외 이전 안내도
   실제 계정·데이터 처리 설정에 맞춰 개정한 뒤 운영 트래픽에 사용해요.
6. 검증한 설정을 적용하고 한 작업에서 실제 폴백·메일·예약 상태를 확인한 뒤 확대해요.

2026-10-22 공고한 처리방침은 2026-10-29 시행이에요. 개인정보를 넣지 않는 콘텐츠 자동화는
먼저 적용하고, `send_log_report`의 마스킹한 로그에 대한 Codex 폴백은 해당 처리방침이
시행된 뒤에만 자동으로 허용해요. 그 전에는 Claude 구독만 사용하며, 분석 실패가 리포트
발송을 막지는 않아요. `allow_codex=False`는 API 경로를 열지 않으면서 특정 호출의 전환을 막아요.

마이그레이션 전에 폴백을 켜면 실행이 실패해요. 웹 프로세스가 이미 실행 중이면 코드와
설정 반영을 위해 필요한 재시작을 한 번에 모으고, cron은 다음 프로세스부터 읽어요.

## 롤백

`AI_FALLBACK_BACKEND`만 비우고 `CLAUDE_BACKEND=cli`, `CLAUDE_CLI_FALLBACK=false`,
`AI_ALLOW_PAID_API=false`는 유지해요. Claude 구독 전용·실패 시 보류로 돌아가요.
새 테이블은 그대로 두어도 되므로 데이터 삭제나 역방향 마이그레이션은 필요하지 않아요.
구독 사용량이나 모델 접근을 늘리기 위해 API 키를 넣는 방식으로 복구하지 않아요.

## 공식 자료

- [비대화형 실행과 JSONL·Schema](https://learn.chatgpt.com/docs/non-interactive-mode)
- [구독 로그인·기기 인증](https://learn.chatgpt.com/docs/auth)
- [인증 유지와 동시 사용 주의](https://learn.chatgpt.com/docs/auth/ci-cd-auth)
- [모델 선택과 접근](https://learn.chatgpt.com/docs/models)
