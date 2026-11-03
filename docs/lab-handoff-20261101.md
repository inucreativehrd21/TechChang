# 연구실 고도화 마무리 인계 (2026-11-01, Codex 작업용)

다음 세션의 Codex가 이 문서만 읽고 **두 작업을 함께 마무리**할 수 있게 정리했어요. 두 작업은 연구실 그래픽(Codex)과 칼럼 파이프라인 B안 개편(Claude)이에요. 모든 변경은 `main` 작업 트리에 **커밋되지 않은 채** 섞여 있어요. 커밋·push·배포는 사용자가 요청할 때만 해요.

## 1. 한눈에 보기

| 작업 | 상태 | 남은 일 | 근거 문서 |
|---|---|---|---|
| A. 연구실 그래픽(고정 시점 plate, 8명) | 구현·PC/모바일 검증 완료 | 커밋 분리, 운영 배포 전 실기기 확인 | [lab-graphic-final-review.md](lab-graphic-final-review.md), [lab-graphic-credits.md](lab-graphic-credits.md), [lab-graphic-handoff.md](lab-graphic-handoff.md) |
| B. 연구실 모델 프로필 A/B 기반(Codex 10/30~31) | 구현·회귀 통과, B는 선택형 | 아래 C와 함께 커밋 | [lab-upgrade-implementation.md](lab-upgrade-implementation.md) |
| C. B안 구조 개편(Claude 10/31~11/01) | 구현·회귀 통과, 후속 4차까지 실행 | 4차 보류 원인 검토, 남은 사례 파일럿은 보류 | [lab-orchestration-research-20261031.md](lab-orchestration-research-20261031.md), §9 |

운영 서버는 아직 이 변경을 하나도 받지 않았어요. 기본 프로필은 `OFFICE_MODEL_PROFILE=a`이고, B안은 환경변수나 `--profile b`로만 켜져요.

## 2. C. B안 구조 개편 — 무엇을 바꿨나

배경: B안 파일럿에서 글이 늘 보류되고, 한 편이 Codex 5시간 한도의 절반 가까이를 썼어요. 원인 분석과 외부 근거(논문·오픈소스)는 [lab-orchestration-research-20261031.md](lab-orchestration-research-20261031.md)에 있어요.

| 변경 | 파일 | 적용 범위 |
|---|---|---|
| B 독립 검증·중재 Astra high → **Sol high**, 설계도 근거 수집은 Sol medium(`purpose='gather'`) | `office/model_router.py`, `office/services.py`, `office/blueprint.py` | B |
| 버전 번호를 통계로 오판하던 문제(LTS인 5.2, 5.2 문서, QuerySet API reference 5.2, x.y.z) | `office/evidence.py` | 전 프로필 |
| 코드 예제 정적 점검(파싱 실패·클래스 밖 test 메서드) | `office/code_check.py`, `pipeline.precheck_draft` | 전 프로필 |
| 코드 예제 실행 검증(임시 앱·메모리 SQLite, 별도 프로세스, 90초) | `office/code_check.py`, `office_publish._code_facts` | `OFFICE_CODE_RUN=1`일 때만 |
| 장르별 구조: 코딩=튜토리얼(어디서 막히나·판단 기준·동작 원리·실행 예제·자주 하는 실수·체크리스트), 그 외=기존 데이터 틀. 기획서가 `genre`를 고르고, 없으면 원고 소제목 → 분야 기본값 순 | `office/genres.py`, `pipeline.py`, `office_publish.py`, `office_revise.py`, `remake_column.py`(데이터 고정), `similarity.py` | **전 프로필** |
| 단정·일반화 문장 기계 점검(항상·반드시·가장·흔한 소개글·현장에서는) | `office/quality.py` | 전 프로필 |
| 조기 보류: 첫 사실 검증에서 실제 결함 6건 이상 또는 첫 심사 65점 미만이면 수정 없이 운영자 검수 | `pipeline.early_hold`, `office_publish.py` | B |
| 실행당 Codex 입력 상한 | `office/run_context.py` | B(`OFFICE_RUN_MAX_CODEX_TOKENS`, 기본 1,000,000, 0=끔) |
| 원장 대조 사실 관문: 웹 대신 원장(확인된 인용 + 코드가 받은 문서 문단 + 실행 결과)과 대조. 인용은 발췌 안에 있어야 함(구두점·생략 부호·문장 이어 붙이기 허용). 원장 밖 주장은 `out_of_ledger`로 '좁히거나 삭제' 수정 대상 | `office/grounded.py`, `pipeline.step_check(evidence=...)` | B(`OFFICE_GROUNDED_CHECK`, 기본 켬) |
| 근거 문서 묶음: 원장·회의 근거·원고의 공식 문서 URL을 코드가 받아 문단으로 나누고, 코드 식별자마다 문단을 먼저 확보한 뒤 3만 자까지 선택 | `office/sources.py` | B(`OFFICE_SOURCE_FETCH`, 기본 켬) |
| 설계도 근거 수집도 원장 대조로(받은 문서가 없을 때만 예전 웹 수집) | `office/blueprint._grounded`, `grounded.verify_claims` | B |
| 사실 관문 웹 확인 기본 끔 | `grounded.GROUNDED_WEB_MAX` | B(`OFFICE_GROUNDED_WEB_MAX`, 기본 0) |
| 패치 검사: 근거 없는 새 수치·새 단정·코드 손상 편집을 하나씩 거절 | `office/patching.py`(`unsupported`, `patch_revise(pack=...)`) | B 편집 심사 패치 |
| `strip_visual_block`이 코드 블록 들여쓰기를 지우던 기존 결함 수정 | `office/pipeline.py` | **전 프로필**(운영 재작성 경로 포함) |
| 실행 근거(URL 없음)를 계약 검사에서 인정 | `office/research_contract.py`, `evidence._check_item` | B |

새 테스트: `office/test_code_check.py`, `test_genres.py`, `test_grounded.py`, `test_sources.py`, 그리고 `test_evidence.py`·`test_patching.py`·`test_model_router.py`에 추가한 테스트예요. 마지막 회귀는 office·common 561개 통과, Django check 통과, `makemigrations --check` 변경 없음, `git diff --check` 통과예요.

### 환경변수

| 이름 | 기본 | 뜻 |
|---|---|---|
| `OFFICE_MODEL_PROFILE` | `a` | `legacy`·`a`·`b` |
| `OFFICE_CODE_RUN` | 꺼짐 | 본문 코드 실행. 모델이 쓴 코드를 실행하므로 **운영 서버에서는 켜지 않기**(OS 수준 격리 아님) |
| `OFFICE_GROUNDED_CHECK` | 켬 | B 사실 관문을 원장 대조로. `0`이면 예전 웹 검증 |
| `OFFICE_SOURCE_FETCH` | 켬 | 공식 문서를 코드가 받기(https·공인 IP·예약 도메인 제외·10초·2MB·최대 6개) |
| `OFFICE_GROUNDED_WEB_MAX` | 0 | 원장 밖 주장 중 웹으로 확인할 개수 |
| `OFFICE_RUN_MAX_CODEX_TOKENS` | 1,000,000 | 실행당 Codex 입력 상한 |
| `OFFICE_GENRES` | 꺼짐 | 장르별 구조 사용. 첫 배포에서는 기존 데이터 틀 유지, B 파일럿에서는 켬 |

## 3. 파일럿 기록 (같은 주제: Django select_related/prefetch_related, 임시 DB·비공개)

| 실행 | Codex 입력 | 시간·호출 | 설계도 확인 | 첫 사실 관문 | 첫 심사 | 최종 |
|---|---:|---|---|---|---|---|
| B 조정 전 (`b-pipeline-trial`) | 약 155만 | 1,611초·24회 | — | 틀림 4·확인 불가 5 | 75 major(1회 수정 뒤) | 예산 소진 보류 |
| v2 (`-v2`, Astra) | 118만 | 1,321초·15회 | 7/14 | 틀림 8·확인 불가 2 | 65 major | 수정 1회 뒤 보류 |
| v3 1차 (`-v3-select-run1`) | 136만 | 1,119초·14회 | 9/14 | 맞음 12·틀림 3·확인 불가 9 | — | Codex 상한으로 보류 |
| v3 2차 (`-v3-select-run2`) | **25만** | 872초·12회 | 12/14 | 맞음 19·틀림 2·원장 밖 3 | 70 major(편집 지적 6) | 패치 뒤 틀림 0·원장 밖 4로 보류 |
| v3 3차 (`-v3-select`) | **15만** | 752초·11회 | 10/14 | 맞음 18·틀림 4·확인 불가 3 | **80**(치명: 검증 미완료) | 패치 뒤 틀림 1·원장 밖 4로 보류 — §8 |
| v3 4차 (`-v3-select`, 이전 3차는 `-run3`으로 보존) | **19만** | 739초·12회 | 기록 참조 | 맞음 17·틀림 1·확인 불가 4 | 78 major | 패치 뒤 틀림 2·확인 불가 2로 보류 — §9 |

모든 기록은 `logs/lab-upgrade-eval/`(git 무시 대상)에 있어요. 실행 스크립트는 `tmp/lab_upgrade_trial_v3.py select|atomic|data`, 원장 대조 재생은 `tmp/replay_grounded.py`(`--corpus`면 모델 호출 없이 문서만 받음)예요.

2차에서 확인한 남은 결함 두 가지(패치가 테스트 코드 들여쓰기를 깨뜨림, 테스트 도구 문단 선택 누락)는 고친 뒤 3차를 돌렸어요.

## 4. 운영 반영 전에 사용자가 정해야 할 것

| 결정 | 선택지 | 권장 |
|---|---|---|
| 장르 틀이 **전 프로필**에 적용됨 — 배포하면 A 프로필의 코딩 칼럼도 튜토리얼 구조로 바뀜 | 그대로 / `genres`를 B에서만 / 환경변수로 켜고 끄기 | 환경변수 스위치를 두고 첫 배포는 끔. B 파일럿 통과 뒤 켜기 |
| 운영 프로필 | A 유지 / B 전환 | 같은 주제 통과 + `atomic`·`data` 사례 파일럿 뒤 결정 |
| 서버에서 외부 문서 받기(`sources.py`) | 허용 / 끔 | B를 켤 때만 허용. 처리방침 영향은 없지만(개인정보 아님) 서버 외부 요청이 늘어요 |
| 코드 실행 검증 | 로컬 파일럿만 / 서버 | 로컬만. 서버에서 필요하면 별도 샌드박스(`codex sandbox` 등) 검토 |

## 5. Codex가 이어서 할 일 (순서)

1. **§8의 '바로 할 일'**: 운영 영향 점검(읽기 전용)과 같은 주제의 4차 파일럿 1회. 보류라면 `stages.json`의 `reverify` 결과에서 원인을 분류해요. 기계적 결함이면 고치고 1회만 재실행해요. 편집 판단이 문제라면 사용자에게 보고하고 멈춰요.
2. **남은 사례 파일럿**: `atomic`(다른 코딩 주제), `data`(통계 주제. 장르·버전 수정이 통계 대조를 느슨하게 만들지 않았는지 확인). 각 편이 Codex 약 25만 토큰을 써요. 한 번에 하나씩, 예약 칼럼 준비 시간(13시·22시)을 피해서 돌려요.
3. **장르 스위치**: §4 결정에 따라 `OFFICE_GENRES` 같은 스위치를 둘지 정해요. 둔다면 `genres.genre_for`에서 꺼짐일 때 `'data'`를 돌려주는 것으로 충분해요. 테스트를 추가해요.
4. **연재·리메이크 경로**: `office/series_pipeline.py`와 `remake_column.py`는 원장 대조·장르를 쓰지 않아요(연재는 `series_catalog`의 자체 틀). 연재에도 적용할지는 별도 판단이에요.
5. **문서 정리**
   - CLAUDE.md가 가리키는 `docs/lab-architecture-review-20261024.md`가 **저장소에 없어요**. 이 문서를 만들거나 참조를 이 인계 문서로 바꿔요(사용자 확인 후).
   - `docs/lab-upgrade-implementation.md`의 B 설명은 일부만 Sol high로 고쳤어요. 끝에 "2026-11-01 개편은 lab-orchestration-research 참고" 한 줄을 넣어요.
6. **커밋 분리(사용자 요청 시)**: 아래 묶음을 권장해요. 커밋마다 `py -3.10 manage.py check`와 관련 테스트를 돌려요.
   - ① 구독 어댑터·모델 라우팅(Codex): `common/services/claude.py`·`codex.py`·`subscriptions.py`, `office/model_router.py`, `office/services.py`, `evaluate_subscriptions.py`, `test_model_router.py`
   - ② B안 기반(Codex): `research_contract.py`, `quantities.py`, `delta_review.py`, `review_batch.py`, `run_context.py`, `adjudication.py`, `publishing.py`, `research_eval.py`, `lab_metrics.py`, `lab_quality_report.py`, `recorder.py`, `review_protocol.py`, `schedule.py`, `agents.py`, `hold_meeting.py`, 관련 테스트
   - ③ B안 구조 개편(Claude): `genres.py`, `grounded.py`, `sources.py`, `code_check.py`, `evidence.py`, `quality.py`, `patching.py`, `pipeline.py`, `blueprint.py`, `office_publish.py`, `office_revise.py`, `remake_column.py`, `similarity.py`, 새 테스트 4개와 수정 테스트
   - ④ 연구실 그래픽(Codex): `templates/office/*`(`_studio.html`, `_home_content.html`, `mobile/office.html`, `office.html`), `office/views.py`, `office/live.py`, `static/css/lab-studio.css`, `static/js/lab-*.js`, `static/img/lab/`, `static/vendor/three/`(되돌리기용 — 삭제 여부는 사용자 결정), `test_live.py`
   - ⑤ 문서: `docs/lab-*.md`
   - **넣지 않는 것**: `.claude/settings.local.json`, `.claude/skills/*`(사용자 로컬), `.agents/`(확인 후), `tmp/`, `output/`, `scratchpad/`, `.codex-attachments/`, `logs/`. `tmp`·`output`·`scratchpad`·`.codex-attachments`는 `.gitignore`에 없으니 `git add`할 때 경로를 명시해요.
   - 파일이 여러 묶음에 걸치면(예: `pipeline.py`에 Codex B 기반과 Claude 개편이 섞임) 한 커밋으로 합치고 메시지에 둘 다 적어요. 부분 스테이징(`git add -p`)은 쓰지 않아요.
7. **배포(사용자 요청 시)**: 메모리의 배포 규칙대로 해요. 서버 HEAD와 origin/main 차이를 확인하고, `git pull`한 뒤 restart는 한 번에 모아서 해요. 마이그레이션은 없어요. 그래픽은 `collectstatic`이 필요해요. B를 켜지 않으면 서버 동작 변화는 §4의 전 프로필 변경(장르·단정 점검·코드 정적 점검·버전 판정)과 그래픽이에요.

## 6. 지켜야 할 것

- 검증 기준을 낮추거나 확인 불가를 통과로 바꾸지 않아요. 유료 API와 서버 `crew_work`로 우회하지 않아요(CLAUDE.md 비용 정책).
- 파일럿은 실제 구독 사용량을 써요. 한 번에 하나씩 돌리고, Codex 한도 경고가 나오면 멈춰요.
- 작업 트리의 다른 변경을 되돌리거나 덮어쓰지 않아요. Claude 메모리 파일은 읽기만 해요.

## 7. 검증 명령

```text
py -3.10 manage.py check
py -3.10 manage.py test office common
py -3.10 manage.py makemigrations --check --dry-run
git diff --check
py -3.10 -u tmp/lab_upgrade_trial_v3.py select|atomic|data      # 실사용(구독)
py -3.10 -u tmp/replay_grounded.py --corpus                       # 문서 받기만(토큰 0)
```

## 8. v3 3차 결과 (2026-11-01, `logs/lab-upgrade-eval/b-pipeline-trial-v3-select/`)

| 항목 | 결과 |
|---|---|
| Codex 입력 / 시간 / 호출 | **152,084토큰** / 752초 / 11회(기획 지표 웹 79k, 설계도 원장 대조 26k, 사실 관문 22k, 재검증 25k) |
| 설계도 | 주장 14개 중 10개 확인. 문서 5개를 코드로 받음 |
| 코드 실행 | 테스트 4개 전부 통과 |
| 첫 사실 관문 | 맞음 18·틀림 4·확인 불가 3. 틀림은 모두 실제 과잉 일반화("접근할 때마다 조회", "보통 select_related를 권함", ".all()에만 대응") |
| 첫 편집 심사 | **80점(발행 기준선)**, 항목 점수 structure 5·depth 4·evidence 4·logic 3·readability 4·visual 4. 치명 결함은 '독립 검증 미완료' 하나뿐 |
| 패치 뒤 재검증 | 맞음 20·틀림 1·원장 밖 4 → 보류 |

**보류의 주원인은 기존 코드 결함이었어요.** `pipeline.strip_visual_block`이 원고를 빈 줄로 나눈 뒤 덩어리마다 `strip()`해서, 코드 블록 안에서 빈 줄 뒤에 오는 4칸 들여쓴 줄(`class Meta:`, `def test_…`)의 들여쓰기를 지웠어요. 연속 빈 줄도 합쳤어요.
- 이 함수는 B 패치 직전과 A/legacy 재작성 경로에서 도판을 다시 만들 때 호출돼요.
- 그래서 수정본의 코드가 깨지고 실행 근거가 사라졌어요. 그 결과 실행 결과에 기대던 주장 4개가 '원장 밖'이 됐어요.
- 패치 검사(코드 손상 거절)가 막지 못한 이유도 같아요. 비교 기준인 원고가 이미 이 함수를 거쳐 깨져 있었어요.
- 2차 파일럿의 '패치가 tests.py를 깨뜨림'도 같은 원인이었어요.

고친 것(회귀 561개 통과):
- `strip_visual_block`이 코드 블록을 통째로 보존하고, 문단 앞 공백(중첩 목록)도 지켜요. 테스트를 추가했어요.
- 버전 범위 표기(`Django>=5.2,<5.3`)를 통계 수치로 잡던 오판도 고쳤어요.

### Codex가 바로 할 일

1. **운영 영향 점검(읽기 전용):** 이 결함은 운영 중인 A/legacy 재작성에도 있어요. 운영 DB에서 발행된 코딩 칼럼과 연재 회차 본문에 `office.code_check.static_issues`를 돌려, 파이썬 블록이 파싱되지 않는 글 목록을 사용자에게 보고해요. 고칠지는 사용자 결정이고, 운영 DB 쓰기는 하지 않아요.
2. **같은 주제로 4차 파일럿 1회:** `py -3.10 -u tmp/lab_upgrade_trial_v3.py select`. 직전 기록 폴더는 `-run3`으로 이름을 바꿔 보존해요. 기대 결과는 패치 뒤 코드 실행 유지 → 실행 근거 회복 → 사실 관문 통과 → 재심 수리예요. 통과하면 §5의 2번(`atomic`·`data`)으로 넘어가요. 다시 보류되면 `reverify`의 비통과 주장을 분류해 보고해요.
3. 그다음은 §5 순서대로 진행해요.

## 9. Codex 후속 점검 (2026-11-01)

- 운영 DB에서 `ColumnDraft(status=published, topic=coding)`에 연결된 공개 질문 7편과 공개 연재 회차 10편을 읽기 전용으로 가져와 현재 `office.code_check.static_issues`로 검사했어요. 파이썬 블록 35개 중 연재 7편(질문 #118)에서 2개가 파싱되지 않았어요. 각각 함수 중간의 `else:`부터 시작하는 발췌와 본문을 생략한 `if form.is_valid():` 발췌라서, 이 결과만으로 들여쓰기 손상으로 분류하지 않아요. 운영 DB는 수정하지 않았어요.
- `OFFICE_GENRES` 스위치를 추가했어요. 기본값은 꺼짐(기존 데이터 틀)이고 파일럿 스크립트만 켜요. 첫 배포는 A 프로필·장르 스위치 끔·코드 실행 끔을 유지해요.
- 오래된 `docs/lab-architecture-review-20261024.md` 참조를 이 문서로 교체했고, `docs/lab-upgrade-implementation.md`에 개편 문서 링크를 추가했어요.
- 같은 주제 4차 파일럿(`logs/lab-upgrade-eval/b-pipeline-trial-v3-select/`): 739초·12회, Codex 입력 191,506토큰. 첫 사실 관문은 맞음 17·틀림 1·확인 불가 4, 첫 심사는 78점 major(치명: 검증 미완료). 패치 3건 적용·1건 거절 뒤 재검증은 맞음 18·틀림 2·확인 불가 2로 보류됐어요. 코드 실행은 초안·수정본 모두 “모델과 테스트가 함께 있는 코드 예제 없음”이었어요. 독립 실행 스크립트의 실제 출력이 원고에 없는데 편집 패치도 이를 채우지 못했고, `select_related`의 JOIN 설명과 `prefetch_related` 뒤 필터 호출 설명에도 검증 지적이 남았어요. 이번 실행에는 앞선 들여쓰기 손상이 재발했다는 증거가 없어요.
- 4차 보류는 실행 검증 범위와 집필·편집 결과가 함께 걸린 문제예요. 단순한 한 줄 코드 결함으로 확인되지 않았으므로 추가 재실행과 `atomic`·`data` 파일럿은 인계 기준에 따라 보류해요. 운영 프로필은 A로 유지해요.

## 10. 후속 (2026-11-02~03, Claude)

### 운영 장애: 배포 restart 가 재검수를 죽임
- 11-02 23:56 배포(`git pull` 45f40f2) 뒤 `systemctl restart mysite` 가 관리 화면이 띄운 `office_revise --draft 53` 을 예원 평론 직후 SIGKILL 했어요. 관리 화면 작업(`office.jobs.spawn`)은 `start_new_session` 이어도 mysite cgroup 안이라 `KillMode=mixed` 재시작에 함께 죽어요. 원고는 '재작성 중'에 멈췄고 11-03 10:00 HRD 공개가 건너뛰어졌어요.
- 복구: 본문은 끝날 때만 저장돼 76점판이 보존돼 있었어요. SSH(웹 밖)에서 같은 지시로 다시 돌렸고(66점, 다시 만든 그림 설명이 평서체가 돼 치명 결함), 운영자 지시로 그 한 문장을 76점판 문장으로 되돌리고 참고 자료 PDF 주소의 공백을 인코딩해 관리자 검수 후 발행했어요(질문 #131, 백업 `~/backups/draft53-20261103/`).
- 재발 방지: `jobmail.recover_orphans` — `office_release`(크론 10분)가 프로세스 없고 15분 기록 없는 '재작성 중' 원고를 검수 대기로 되돌리고 같은 지시로 재심을 하루 한 번 예약해요. **배포 restart 전에는 `pgrep -af "manage.py office_"` 로 진행 중 작업을 확인해요.**

### 튜토리얼 실행 근거 우선 (B·`OFFICE_GENRES` 켬일 때만)
- 예제 형식 고정: 집필 지침이 `# 앱/models.py`·보조 모듈·`# 앱/tests.py` 블록을 요구하고, 혼자 실행하는 스크립트(`settings.configure` 등)를 금지해요. `code_check.format_issues` 가 자동 점검에서 잡아요.
- 먼저 실행: `office_publish._run_first` — 형식 결함·실행 실패 테스트가 있으면 사실 검증 전에 한 번 고치고 다시 실행해요.
- 실행기 확장: 보조 모듈(`services.py`)·`from . import services`·앱 경로 `mock.patch("shop.services.x")`(임시 앱을 본문 앱 이름으로)·설명이 붙은 '잘못된 예' 블록 제외.
- 패치 규칙: 근거 없는 문장을 '필자의 추론'·'~로 보입니다'로 약하게 바꾸는 편집을 거절해요(`patching.HEDGE`).

### atomic 파일럿 (`logs/lab-upgrade-eval/b-pipeline-trial-v3-atomic*`)

| 실행 | Codex 입력 | 코드 실행 | 첫 심사 | 패치 뒤 재검증 |
|---|---:|---|---|---|
| 1차(`-run1`) | 19만 | 8개 중 6 오류(보조 모듈 누락) | 66 major, 치명 2 | 맞음 14·틀림 1·원장 밖 6 |
| 2차(`-run2`, 보조 모듈 지원) | 29만 | 안 됨(혼자 실행 스크립트) | 72 major, 치명 1 | 맞음 19·틀림 1·원장 밖 4 |
| 3차(형식 고정·먼저 실행·패치 규칙) | 23만 | 16개 중 14 오류(실행기 빈틈 3개) | 75 major, 치명 1 | 맞음 15·틀림 3·원장 밖 6 |

3차 뒤 실행기 빈틈을 고치고 세 원고를 모델 호출 없이 다시 실행하면 1차 8/8·3차 14/14 통과, 2차는 형식 결함 2건으로 '먼저 고치기' 대상이 돼요. 남은 편집 문제(동작 원리 과잉 일반화, 문서에 없는 상식 전제)는 실행 근거가 생긴 뒤 다시 측정해요.
