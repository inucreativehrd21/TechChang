# AGENTS.md — Codex 작업 지침 (TechChang)

이 저장소는 Claude Code와 Codex가 함께 씁니다. 프로젝트 규칙의 단일 원본은 `CLAUDE.md` 입니다.

## 시작할 때 읽을 것 (순서대로)

1. `CLAUDE.md` — 기술 스택, 구조, 개발·배포 명령, 핵심 규칙(네임스페이스 `community`, 템플릿 상속 등). **먼저 전부 읽고 따를 것.**
2. 작업 메모리 색인 `C:\Users\user\.claude\projects\c--projects-mysite\memory\MEMORY.md`
   - 한 줄 요약 목록이고, 각 항목이 같은 폴더의 상세 파일(`rookie-lite.md`, `lab-agents.md` 등)을 가리킨다.
   - 작업과 관련된 항목의 상세 파일만 골라 읽을 것. 전부 읽을 필요 없음.
   - 메모리는 **작성 시점의 기록**이다. 파일·함수·플래그 이름을 근거로 쓰기 전에 코드에서 실제로 있는지 확인할 것.
   - 메모리는 저장소 밖 파일이므로 **읽기만** 한다. 수정·삭제·저장소로 복사 금지(서버 접속·운영 정보 포함).

## 로컬 환경 (Windows)

- `python` 은 스텁이라 쓰지 말 것. `py -3.10 manage.py ...` 로 실행 (py 기본 3.12엔 의존성 없음).
- 한글이 든 스크립트를 stdin 파이프로 넘기면 인코딩이 깨진다. 파일로 저장해 실행할 것.
- 커밋 전 `py -3.10 manage.py check` 필수.
- 로컬 실행·스크린샷은 `.claude/skills/run-local` 절차 참고.

## 하지 말 것

- 서버측 Claude API 호출을 늘리거나 `CLAUDE_CLI_FALLBACK` 를 켜지 말 것 (유료 API 과금 정책, 메모리 `api-cost-policy.md`). `crew_work` 를 서버에서 돌리지 말 것.
- `pybo` 네임스페이스·템플릿 경로 사용 금지.
- 디자인 수정 시 `.claude/skills/design-guardrails/` 의 규칙을 따를 것(라이브 토큰은 `premium.css`; `variables.css`/`themes.css` 는 죽은 파일).
- 운영 서버 배포·재시작, 원격 push, DB 마이그레이션 적용은 사용자가 요청할 때만.
- 사용자 변경(커밋 안 된 파일)을 되돌리거나 덮어쓰지 말 것.

## 작업 방식

- 커밋 메시지는 기존 스타일 `type(scope): 한국어 설명` (예: `fix(games): ...`).
- 사용자 대상 문구는 한국어, 해요체.
- 큰 변경 전에 관련 메모리 항목을 읽고, 작업이 끝나면 메모리에 남길 만한 비자명한 결정이 있었는지 사용자에게 알려줄 것(메모리 기록은 Claude 쪽에서 한다).

## 프론트엔드·디자인 공통 절차

- 테크창 화면 디자인·템플릿·CSS 작업에는 `.claude/skills/techchang-ui/SKILL.md`를 읽고 적용한다.
- 공통 스킬이 안내하는 기존 디자인 스킬은 필요한 것만 읽는다. 프로젝트 고유 규칙은 `CLAUDE.md`와 `design-guardrails`를 따른다.
- MCP 등록과 계정 인증은 구분한다. 도구를 실제로 검증하기 전에는 연결 완료라고 보고하지 않는다.
