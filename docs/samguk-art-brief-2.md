# 테크창 삼국지 — 디자인 의뢰서 2차 (Codex용, 2026-11-19)

1차 의뢰서는 [samguk-art-brief.md](samguk-art-brief.md)(초상 기준 3장·★4·★3 70장·지도·문장·공용 그림), 규칙서는 [samguk-design.md](samguk-design.md)에 있다.
엔진과 화면 골격이 모두 돌아간다. 이번 의뢰는 **골격 화면 위에 디자인을 입히는 일**과 **나머지 그림**이다.

## 지켜야 할 것 (기능이 깨지지 않게)

- **폼은 그대로 둔다.** 모든 행동은 `<form method="post">` 한 번이다. `action` 주소, `name` 속성(`kind`, `seq`, `city`, `from`, `to`, `officers`, `troops`, `by`, `target`, `gold`, `mode`, `series`, `what`, `how`, `user`, `slot`, `code`, `building`, `decor`, `entry`, `back`), hidden 입력(특히 `seq`), `{% csrf_token %}`을 지우거나 이름을 바꾸지 않는다. 겉모양과 배치는 마음대로 바꿔도 된다.
- **판정은 서버가 한다.** 화면이 값을 계산해서 보여 주는 것은 괜찮지만, 결과를 화면에서 만들어 내면 안 된다.
- 프로젝트 가드레일(`design-guardrails`, `techchang-ui` 스킬)을 따른다. 라이브 토큰은 `premium.css`(인디고 `#4f46e5`, 라이트 전용)이고, `variables.css`·`themes.css`는 로드되지 않는 파일이다.
- 스타일은 새 파일 `static/css/samguk.css`(접두사 `sg-`)에 모은다. 템플릿에는 `{% block extra_css %}`로 연결한다.
- 모바일 판은 `base_mobile.html`(56px 헤더 + 70px 하단 탭바)을 상속한다. 본문 조각(`_*_body.html`)은 PC·모바일이 같이 쓰고, 감싸는 파일만 다르다.

## 화면 목록

| 화면 | 주소 | 템플릿(본문 조각) | 기기 | 상태(`data-step` 등) |
|---|---|---|---|---|
| 오늘의 천하 | `/samguk/` | `samguk/_home_body.html` + 판 `samguk/_board.html` | PC·모바일 | `data-step`: guest / faction / tutorial_prompt / start / play |
| 튜토리얼 | `/samguk/tutorial/` | `samguk/_tutorial_body.html` + `_board.html` | PC·모바일 | 안내 말풍선 `sg-hint` |
| 순위 | `/samguk/ranking/` | `samguk/_ranking_body.html` | PC·모바일 | 진행 중 / 닫힘 |
| 천하인 기보 | `/samguk/replay/<날짜>/` | `samguk/_replay_body.html` | PC·모바일 | 행동마다 `data-kind` |
| 장원 | `/samguk/manor/`, `/samguk/manor/<번호>/` | `samguk/_manor_body.html` | **PC 전용** | 내 장원 / 남의 장원(`data-owner`) |
| 도감 | `/samguk/codex/` | `samguk/_codex_body.html` | **PC 전용** | 카드 `is-unknown` / `is-seen` / `is-recruited`, 외전 `is-gaiden`, 기연 `is-giyeon` |
| 객잔 | `/samguk/inn/` | `samguk/_inn_body.html` | **PC 전용** | 손님 `is-picked`, 나그네 `sg-traveler` |
| 모바일 안내 | 장원 쪽 주소를 모바일로 열 때 | `samguk/_pc_only_body.html` | 모바일 | "PC에서 이용해 주세요" |

### 오늘의 천하 판(`_board.html`)에서 쓸 수 있는 값

- 도시 카드 `sg-city`: `data-city`(코드), `data-x`·`data-y`(지도 좌표 0~1000, 1차 의뢰서의 지도와 같은 좌표), `data-owner`(me / none / yellow / 군벌 코드 / boss), 클래스 `is-mine`·`is-near`.
- **지도 위에 도시를 얹는 배치를 권한다.** 지금은 카드 목록이지만 좌표가 들어 있으니, 지도 그림 위에 절대 위치로 도시 점을 찍고 카드는 누르면 열리는 패널로 바꾸면 된다. 모바일은 지도를 축소해 보여 주고 카드 목록을 아래에 두는 방식을 권한다.
- 장수 `sg-officer`: `data-code`(초상 파일명), `data-tier`(테두리 색).
- 상단 상태 `sg-status`: 군령(남은 수/전체, 활동 보너스), 금, 군량, 점수, 정세.
- 전설 이벤트 `sg-legend`: `data-event`(nanman, rift 등), `data-city`. 소문을 못 들은 이벤트는 제목이 `???`다.

### 연출 자리

| 연출 | 언제 | 데이터 |
|---|---|---|
| 일기토 | 출정 결과에 `duel`이 있을 때 | `SamgukAction.result.duel` = {att, def, winner} |
| 천하통일 | 다음 날 순위가 닫혀 1위가 됐을 때 | 순위 화면 `day.winner` |
| 도감 첫 등록 | 등용·객잔 영입 직후 메시지 | 메시지 문구 "도감에 올랐어요" |
| 시공의 틈 | 판에 `rift` 이벤트가 있을 때 | `data-event="rift"`. **진지한 톤**으로, 실존 위인이 나오는 장면이다 |

야구 각성 연출처럼 이펙트만 쓰고, 그림으로 상황을 그리지는 않는다. 이건 운영자가 이전에 정한 원칙이다.

## 그림 작업

### 작업 5 — 외전·기연 초상 27장

본편과 같은 그림체로 그리고 테두리만 다르게 한다(외전 / 기연 전용). 파일 규격은 1차와 같다(`static/samguk/officer/<코드>.webp` + `160/`).
기연 장수는 **그 나라·그 시대의 복식을 고증한다**. 삼국지 복식으로 통일하지 않는다. 실존 위인은 존중하는 어조로 그린다.

| 코드 | 이름 | 묶음 | 나라·시대 | 외형 메모 |
|---|---|---|---|---|
| `menghuo` | 맹획 | 외전 | 남만 | 남만 왕, 짐승 가죽과 깃털 장식, 기개 있는 얼굴 |
| `zhurong` | 축융 | 외전 | 남만 | 맹획의 아내, 날아가는 칼(비도), 불꽃 같은 기세 |
| `huatuo` | 화타 | 외전 | 후한 말 | 노년 의원, 약초 바구니 |
| `simahui` | 사마휘 | 외전 | 후한 말 | 온화한 은사, 은은한 미소(수경 선생) |
| `huangyueying` | 황월영 | 외전 | 후한 말 | 지혜로운 여인, 공구·설계도 |
| `zuoci` | 좌자 | 외전 | 후한 말 | 장난기 어린 도사, 지팡이 |
| `guanlu` | 관로 | 외전 | 삼국 | 점술가, 점괘 도구, 깊은 눈 |
| `yuji` | 우길 | 외전 | 후한 말 | 신비로운 노도사, 흰옷 |
| `dongcheon` | 동천왕 | 기연(동이) | 고구려 3세기 | 고구려 왕의 복식, 위엄 |
| `milu` | 밀우 | 기연(동이) | 고구려 3세기 | 결사대를 이끈 무장 |
| `yuyu` | 유유 | 기연(동이) | 고구려 3세기 | 결연한 충신(거짓 항복 일화) |
| `eulpaso` | 을파소 | 기연(동이) | 고구려 2세기 말 | 소박한 재상, 곡식 자루 |
| `seokuro` | 석우로 | 기연(동이) | 신라 3세기 | 신라 장군, 바다 배경 |
| `goi` | 고이왕 | 기연(동이) | 백제 3세기 | 백제 왕의 복식 |
| `himiko` | 히미코 | 기연(동이) | 왜 3세기 | 여왕, 제사장 분위기 |
| `eulji` | 을지문덕 | 기연(시공) | 고구려 7세기 | 지략가 장수 |
| `yangmanchun` | 양만춘 | 기연(시공) | 고구려 7세기 | 성을 지키는 성주 |
| `gyebaek` | 계백 | 기연(시공) | 백제 7세기 | 결연한 장군 |
| `kimyusin` | 김유신 | 기연(시공) | 신라 7세기 | 화랑 출신 대장군 |
| `gwanggaeto` | 광개토대왕 | 기연(시공) | 고구려 4~5세기 | 정복 군주, 개마무사 |
| `gangamchan` | 강감찬 | 기연(시공) | 고려 11세기 | 문관 출신 명장 |
| `yisunsin` | 이순신 | 기연(시공) | 조선 16세기 | 조선 수군 장수, 바다. 가장 존중하는 어조로 |
| `musashi` | 미야모토 무사시 | 기연(시공) | 일본 17세기 | 두 자루 칼의 검객 |
| `yoshitsune` | 미나모토노 요시쓰네 | 기연(시공) | 일본 12세기 | 젊은 무장, 기마 |
| `kenshin` | 우에스기 겐신 | 기연(시공) | 일본 16세기 | 두건을 쓴 무장 |
| `shingen` | 다케다 신겐 | 기연(시공) | 일본 16세기 | 투구 장식의 무장 |
| `yukimura` | 사나다 유키무라 | 기연(시공) | 일본 17세기 | 붉은 갑옷 무장 |

### 작업 6 — 장원 그림

| 항목 | 내용 |
|---|---|
| 장원 전경 1장 | 고정 자리 8칸(건물 5 + 장식 3)이 보이는 한 장. PC 가로 화면 기준 |
| 건물 5종 × 단계 | 본채 1~5, 객잔 1~3, 정자 0~3, 서고 0~3, 연무장 0~3. 0단계(아직 없음)는 빈 터 그림 |
| 장식 6종 | 정원·연못·깃발·석등·대나무·매화 |
| 장수 배치 칸 12개 | 이름과 순서는 아래 표. 배치된 장수는 초상(또는 반신)을 칸에 얹는다 |
| 지나가는 거지 | 화면 아래를 걸어 지나가는 캐릭터(몇 프레임 또는 CSS 이동) + 말풍선. 우스꽝스럽되 비하하지 않게, 이름표 "지나가는 거지" |
| 객잔 장면 | 객잔 화면 머리 그림 1장, 나그네 그림 1장 |

배치 칸 순서는 `community/samguk_manor.py`의 `PLACE_SLOTS`와 같다. 본채 단계가 오를수록 앞에서부터 열리고, 해당 건물을 지어야 그 칸이 열린다.

| 순서 | 칸 | 필요한 건물 |
|---|---|---|
| 1 | `front1` | 본채 |
| 2 | `front2` | 본채 |
| 3 | `pavilion1` | 정자 |
| 4 | `training1` | 연무장 |
| 5 | `front3` | 본채 |
| 6 | `library1` | 서고 |
| 7 | `pavilion2` | 정자 |
| 8 | `training2` | 연무장 |
| 9 | `library2` | 서고 |
| 10 | `training3` | 연무장 |
| 11 | `pavilion3` | 정자 |
| 12 | `front4` | 본채 |

칸 좌표는 그림을 그린 쪽(Codex)이 정해서 `static/samguk/manor/slots.json`(`{"front1": [x, y], ...}`, 0~1000)으로 넘겨 주면 화면에서 쓴다.

## 확인 방법

- 로컬: `py -3.10 manage.py runserver` → 관리자(staff) 계정으로 `/samguk/`. 공개 전에는 운영진만 들어간다.
- 모바일 확인은 `force_version=mobile` 쿠키나 모바일 UA로 본다. 장원 쪽 주소는 안내 카드가 떠야 정상이다.
- 화면을 바꾼 뒤 `py -3.10 manage.py test --noinput community.test_samguk`로 폼·흐름이 깨지지 않았는지 확인한다. 화면 흐름 테스트(`test_pages_flow`, `test_manor_pages` 등)가 있다.
