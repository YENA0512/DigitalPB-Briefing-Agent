# CLAUDE.md

Claude Code가 이 저장소에서 작업할 때 **항상 먼저 읽는 파일**입니다.
단계별 작업 지시는 `WORKPLAN.md`에 있습니다.

---

## 1. 프로젝트

**디지털PB 브리핑 Agent** — KB스타뱅킹 자산관리 투자홈의 브리핑 카드 문구를
LangGraph Agent가 생성하고, 현업 담당자가 승인해 노출하는 구조.

사내 6주 AI엘리트교육 개인 프로젝트. **완성품이 아니라 핵심 기능이 동작하는 프로토타입**이 목표.
최종발표 **2026-10-17**.

> **2026-10-12 기획 개정.** 카드 1장 → 채팅형 브리핑으로 범위를 키웠다.
> 출처 표기·문구 길이·근거 구성이 바뀌었다. 바뀐 이유는 `docs/PLAN_2610.md`.

### 문제 정의

> 투자 콘텐츠 담당자가 브리핑 문구를 관리할 때, **엑셀 수기 작성 → 개발자 하드코딩 반영**을
> 거쳐야 해서 문구를 자주 갱신하기 어렵고 개인화 수준을 높이기도 어렵습니다.

| 지표 | 값 | 출처 |
|---|---|---|
투자홈 **MAU** | **130,843명** | 2026-08 |
투자 브리핑 카드 **일평균 노출** | **9,623건** | 일평균 PV |
브리핑 문구 | **41개 케이스 고정** | 현업 정의서 |
**케이스당 평균 고객** | **약 3,191명** | MAU ÷ 41 |
문구 수정 → 개발 반영 | **최소 7일** | 담당자 엑셀 → 개발 하드코딩 |

> 하루 **9,623번** 노출되는 자리에, **7일 전에 확정된 문장**이 걸려 있습니다.
> 같은 케이스에 묶인 **3,191명**은 어제도 오늘도 같은 문장을 봅니다.

**이 네 숫자가 발표 30점 항목(현업 문제 정의)의 핵심이다.** 추정치가 섞여 있으면
그렇다고 밝히되 공란으로 두지 말 것 — 채점 기준이 "구체적인 수치·상황·빈도"다.

### 기대 효과

> 투자홈이 지향하는 **역동성과 개인화**를, 사람이 감당할 수 있는 범위 안에서 한 단계 끌어올립니다.
> 담당자는 문구 관리 시간을 콘텐츠 기획에 쓰고, 고객은 자산 변화의 '이유'를 알게 됩니다.
> **단, 투자권유는 하지 않습니다. 설명과 안내까지가 범위입니다.**

### 현재 운영 방식 (= 대체 대상)

- 41개 케이스 문구를 담당자가 엑셀로 작성 → 개발자가 소스에 하드코딩
- 카드 4종(국내/글로벌 시황 · 환율 · 투자 콘텐츠 · 개인 브리핑) 중 **랜덤 1택**
- 갱신 주기가 길어 당일 시황 반영 불가, 문구에 근거 없음

---

## 2. 운영 구조 — Batch / Runtime 2계층

```
[Batch]  매일 장 마감 후 (18:00)
   Agent 문구 생성 → 3축 Validation → 어드민 검수(HITL) → 승인분만 서빙 큐 적재

[Runtime] 고객 투자홈 진입
   승인된 케이스 문구 선택 → 고객 수치 슬롯 치환 → 카드 노출   ※ LLM 호출 없음
```

**금소법상 투자 문구는 사람 책임 하에 노출되어야 하므로 고객 요청 경로에 LLM이 없습니다.**
검수 단위는 고객이 아니라 **케이스**입니다. 41건을 검수하면 전 고객에게 나갑니다.

### ⚠️ 채팅형 UI 는 연출이다 — Runtime 에 LLM 은 없다

2026-10 개정으로 화면이 **AI 와 대화하는 형태**가 됐지만, 모델을 부르는 것이
아니다. Batch 에서 승인된 JSON 을 **순차로 펼쳐 보여주는 것**이다.
한 번에 다 보여주면 정보량에 압도되고 순차로 펼치면 읽힌다 — UX 선택이고
아키텍처 변경이 아니다. 여기에 실시간 응답을 넣으면 책임 구조가 깨진다.

---

## 3. 아키텍처

### 그래프

```
START → diagnose
          ↓ 조건부 엣지 · 리스트 반환 → 병렬 fan-out
   search_daily / search_weekly / search_monthly / search_market / search_news
          ↓ fan-in (evidence reducer가 병합)
        generate            카드 선택 + 문구 생성
          ↓ 고정 병렬
   review_compliance / review_grounding / review_format
          ↓ fan-in
        aggregate
          ↓ 조건부 엣지 · 문자열 반환 → 택1
   optimize ──┐      fallback      match_contents → finalize → END
              └→ 3개 review로 복귀 (Feedback Loop, 최대 3회)
```

`human_review`(HITL)는 `match_contents` 와 `finalize` 사이에 들어갈 자리가
비어 있습니다. 미구현.

`add_conditional_edges`의 **반환 타입이 동작을 가릅니다.**

| 반환 | 동작 | 사용처 |
|---|---|---|
| 리스트 `["a","b"]` | 해당 노드 **병렬 실행** | `route_after_diagnose` |
| 문자열 `"a"` | **택1** | `route_after_review` |

### 패턴 선택 근거 (발표 때 설명해야 하는 부분)

| 구간 | 패턴 | 이유 |
|---|---|---|
| diagnose → search | Routing + Parallel | 검색 대상이 고정이고 상호 독립 |
| search → generate | Chaining | generate가 검색 결과를 입력으로 사용 |
| generate → review | Parallel (Jury) | 규제 위반 / 할루시네이션 / 형식 위반은 서로 다른 실패 유형 |
| review → optimize | Evaluator-Optimizer | 지적사항 반영 후 재심사 |
| human_review | Human-in-the-Loop | `interrupt()` + `Command(resume)` |

### State

```python
class BriefingState(TypedDict):
    portfolio: dict; profile: dict; recent_views: list      # 입력
    metrics: dict; change_type: str; gap_type: str          # 진단 = 라우팅 키
    market: dict                                            # 실시간 시황 (market_tool)
    case_id: str                                            # 41케이스 판정 결과
    evidence: Annotated[list, operator.add]                 # 근거 — Validation 대상
    contents: list                                          # KB Think 링크 — 대상 아님
    selected_card: str; selection_reason: str
    card_scores: dict; draft: str
    reviews: Annotated[list, keep_latest_round]             # ★ 현재 회차만
    review_history: Annotated[list, operator.add]           # ★ 전 회차 누적
    revision: int
    card_spec: dict; fallback_used: bool
    logs: Annotated[list, operator.add]
```

### ★ `reviews` 의 reducer 는 `operator.add` 가 아니다

`operator.add` 로 두면 **그 칸을 비울 수 없어서 Feedback Loop 이 성립하지 않는다.**
`operator.add(["실패기록"], []) == ["실패기록"]` 이므로 노드가 `reviews: []` 를
반환해도 누적분이 남고, 1회차 실패기록 때문에 2회차가 전부 통과해도
`all(passed)` 가 False 다. **반려된 문구는 영원히 되살아나지 못한다.**

`keep_latest_round` 는 각 심사 결과에 박힌 `revision` 을 보고 스스로 이전
회차를 버린다. 노드가 "비워야 한다"를 기억할 필요가 없다 — 기억에 의존하는
규칙은 언젠가 빠뜨린다. 감사 추적은 `review_history` 가 따로 보존한다.

구현·자기검증 → `src/reducers.py`, 회귀 → `tests/test_loop.py` 5번

**`evidence`와 `contents`를 절대 합치지 마세요.**
KB Think 교양 콘텐츠가 시황 판단의 근거로 인용되면 사고입니다.
grounding 심사는 `evidence`만 검증합니다.

### 출력물 — 카드 스펙 JSON

Agent의 산출물은 **JSON**입니다. 뷰어/목업은 이 JSON을 받아 그리는 역할일 뿐이고,
JSON이 어떻게 만들어졌는지 몰라야 합니다. 둘을 섞지 마세요.

```json
{
  "case_id": "CASE19",
  "card_type": "personal_briefing",
  "selected_over": ["domestic_market", "fx", "content"],
  "selection_reason": "하락 · 최대비중 42% · 해외시황 +0.59%",
  "card_scores": {"personal_briefing": 6.32, "domestic_market": 3.09},

  "advice":         "…839,000원 감소했어요 [portfolio]. …번졌어요 [일간-261012].",
  "advice_display": "…839,000원 감소했어요. …번졌어요 ①.",
  "advice_plain":   "…839,000원 감소했어요. …번졌어요.",
  "sources": [
    {"marker": "①", "doc": "일간-261012", "kind": "리포트",
     "title": "반도체 투심 위축에 코스피 급락", "summary": "…",
     "publisher": "KB Think", "date": "2026-10-12", "url": "https://kbthink.com/…"}
  ],
  "서브조언": "…", "버튼명": "…",
  "end_service": {"name": "자산분석 진단 확인하기", "link": "window.navi…"},

  "metrics": {"delta": -839000, "rate": -0.91, "max_weight": 0.42},
  "contributions": [{"name": "KODEX 반도체", "delta": -624000, "weight": 0.42}],
  "market": {"국내": {...}, "해외": {...}, "환율": {...}, "region_used": "해외"},

  "news":     [{"title": "…", "url": "…", "publisher": "세계일보", "matched": "KODEX 반도체"}],
  "contents": [{"title": "…", "url": "…", "summary": "…", "section": "재테크 TIP"}],

  "review": {"compliance": {...}, "grounding": {...}, "format": {...}},
  "review_rounds": 1, "fallback_used": false
}
```

`selected_over`는 **랜덤 방식과의 차이를 보여주는 데모 핵심 필드**입니다. 지우지 마세요.

### ★ 내부 표기와 대고객 표기를 섞지 마세요

| 칸 | 용도 | `[portfolio]` | 출처 코드 |
|---|---|---|---|
`advice` | 검수 화면 · 감사 추적 · grounding 심사 | 있음 | `[일간-261012]` |
`advice_display` | **고객 노출** | **없음** | `①②③` |
`sources` | 고객이 누르는 출처 칩 | — | 제목·발행처·URL |

출처 코드는 grounding 심사가 **대조할 수 있는 라벨**이어서 생긴 것이고 고객이
읽을 이유가 없습니다. `[portfolio]`는 자체 계산값이라 출처가 없으므로
**고객 화면에서 완전히 지웁니다** — 붙여도 고객에게 아무 정보를 주지 않습니다.

변환은 `src/sources.py` 한 곳에서만 합니다. 노드가 직접 문자열을 자르면
심사용 문구와 노출용 문구가 갈립니다.

### 근거 3층

```
market_tool   숫자   코스피 -3.39% · 원/달러 1,333원          [시장-^KS11]
retriever     해설   반도체 업종에 차익 실현이 번졌다            [일간-261012]
news_tool     사건   '반도체 약세' 코스피 6,500 내줘 (MBC뉴스)   [뉴스-1]
```

고객이 알고 싶은 것은 "얼마나 변했나"가 아니라 **"왜 변했나"** 입니다.
금액은 이미 화면에서 봅니다. 뉴스가 그 "왜"에 가장 가깝습니다.

뉴스는 **보유 종목 비중 순**으로 찾습니다 — 비중이 큰 종목이 변동 설명력도
큽니다. 종목명을 그대로 검색하면 `KODEX` 같은 상품 브랜드가 검색을 망치므로
섹터 어휘로 번역합니다(`news_tool.query_for`).

## 4. Rule / LLM 경계

규제 영역이라 **추적 가능해야 하는 판단은 전부 Rule**입니다.

| 영역 | 담당 | 이유 |
|---|---|---|
| 41케이스 판정, 수익률·비중 계산 | **Rule** | 동일 입력 → 동일 출력이 보장돼야 함 |
| 금지어 매칭, 글자수 검사, 슬롯 유효성 | **Rule** | 결정적 판정, LLM 불필요 |
| 문구 생성, 톤 조정, 재작성 | **LLM** | 표현의 다양성이 목적 |
| 애매한 표현의 투자권유 여부 2차 판정 | **LLM** | Rule이 거른 뒤 남은 회색지대만 |
| 콘텐츠 태그 번역 | **LLM** | 상황 → 현업 해시태그 어휘 매핑 |

---

## 5. 파일

```
src/
  reducers.py          ★ Feedback Loop 을 성립시키는 reducer + 자기검증
  briefing_agent.py    메인 LangGraph — 15노드
  sources.py           ★ 내부 태그 → 대고객 출처 칩 (①②③ + 링크)
  case_router.py       41케이스 판정. 전 조합 커버리지 41/41 검증
  market_tool.py       시황 Tool (Yahoo Finance) — 지수·환율·VIX 7종
  news_tool.py         뉴스 Tool (Google News RSS) — 보유 종목·섹터 기사
  retriever.py         리포트 벡터 검색 + 키워드 폴백
  prompts.py           프롬프트 분리 — 코드에 하드코딩하지 않는다
  llm.py               LLM 래퍼. 예외를 밖으로 던지지 않고 호출 수를 센다
  content_matcher.py   KB Think 콘텐츠 스코어링 매칭
  config.py            .env 로딩 · 문구 길이 한도 · 키 없으면 USE_LLM 을 내린다
data/
  cases_41.json        41케이스 원문 + 서비스 8종 + 슬롯/글자수 제한
  kbthink_contents.json 콘텐츠 50건 + 태그 19종 (목데이터, 2026-10 최신화)
  reports/             시황 목 리포트 8건 — frontmatter 에 url·summary
tests/test_loop.py     루프 회귀 6종
lab/pattern_lab.py     패턴 비교 — chaining / parallel / reducer 없는 버그 / orchestrator
demo/
  viewer.html          채팅형 좌우 비교 뷰어 (데이터 인라인, 단일 파일)
  build_viewer.py      output/approved/*.json → viewer.html 주입
code/                  교육과정 노트북 21개 (참고용, 원본 보존)
```

실행: `./run_local.sh agent` — `USE_LLM=false`면 API 키 없이 전체 흐름이 돕니다.
`USE_LLM = False` 경로는 **끝까지 유지하세요.** 발표장에서 네트워크가 막혀도
데모가 돌아야 합니다. **Rule 생성 경로도 3축을 통과해야 합니다** — 태그 없는
문구나 길이를 벗어난 문구를 내면 전건 폴백됩니다(실제로 그랬습니다).

### 41케이스 축

```
투자자산상태(4) × 최근접속일시(3) × 총금액변동(4) × 단기시장전망(6) = 288조합
  → 유의미한 조합만 압축해 41케이스
```

| 축 | 값 |
|---|---|
| 투자자산상태 | `X>X` `X>O` `O>X` `O>O` |
| 최근접속일시 | 동일일자 / 1~30일 / 30일 초과 |
| 총금액변동 | 증가 / 감소 / 변동없음(±0.5%) / 급등·급락(±30%) |
| 단기시장전망 | 국내·해외 × 좋음·보통·나쁨 |

압축 규칙 = 판정 로직:
- 자산이 없거나 상태가 바뀌면 나머지 축 무의미 → CASE1~8
- 오늘 이미 봤으면 변동을 말할 게 없음 → CASE9
- 급등·급락이면 개인 변동폭이 커서 시장전망을 쓰지 않음 → CASE23~26, 40, 41

슬롯: `{days}` `{diffAmt}` `{curAmt}` — 단 `curAmt`는 41건 전체에서 사용 0회
글자수: **원본** 상세조언 13~74자 · 서브조언 14~18자 · 버튼명 11~15자

### ⚠️ 13~74자는 카드 UI 제약이지 설계 제약이 아니다

채팅형으로 가면서 **생성 문구는 `.env`의 `ADVICE_MIN_LEN`/`ADVICE_MAX_LEN`
(기본 40~220자 · 6문장)** 을 따릅니다. 74자로는 "변동 + 기여 + 원인"이
들어가지 않아 LLM 이 계속 글자수로 반려됐습니다(실측 4라운드 후 폴백).
한도를 올린 뒤 **LLM 호출이 23→15회로 줄고 폴백이 사라졌습니다.**

**폴백 문구에는 여전히 원본 제한이 적용됩니다**(`ORIGINAL_MIN`/`ORIGINAL_MAX`).
현업이 그 틀에서 쓴 문장이기 때문입니다.

---

## 6. 보안 제약 — 반드시 지킬 것

GitHub **Public Repo**로 제출합니다.

- **사내 실데이터 절대 금지.** 포트폴리오·고객정보는 `MOCK_PORTFOLIOS`만 사용
- **사내 전문거래 실연동 금지.** Tool 시그니처와 Mock 응답만 정의
- **API 키를 코드에 쓰지 말 것.** `.env` + `python-dotenv`, `.gitignore`에 `.env` 포함
- 커밋 전 `git diff`로 키·사번·고객번호·내부 URL 유출 확인
- 사내 시스템 캡처 이미지는 저장소에 넣지 말 것 (발표자료에만 사용)
- 리포트/시황은 공개 자료 수동 수집분 또는 생성한 목데이터만

---

## 6-2. 공개 저장소 마스킹 (2026-10-12 적용)

`data/cases_41.json` 의 **문구 41건은 그대로** 둡니다 — 식별자가 아니고
데모 품질에 필요합니다. 내부 시스템 식별자만 가렸습니다.

| 항목 | 공개본 |
|---|---|
서비스 화면ID | `SVC_A` ~ `SVC_G` (+`SVC_E_ALT`) |
앱 네비게이션 | `window.navi.navigate('/mquics?page={service_id}', …)` |
내부 분석태그 | `상품_디지털PB_투자브리핑_SVC_*` |
정의서 파일명 | 제거 |

- **복원 맵은 `data/_service_id_map.local.json`.** `.gitignore` 에 있고
  **절대 커밋하지 않습니다.** 사내 반입 시 이 파일로 되돌립니다
- **새 서비스를 추가할 때 실제 화면ID 를 쓰지 말 것.** `SVC_*` 를 쓰고
  매핑만 로컬 파일에 추가합니다
- 커밋 전 확인: `D0[0-9]{5}` · `mquics?page=D` · 사내 엑셀 파일명 · API 키

## 7. 개발 규칙

### 반드시

- **fan-in 되는 State 칸에는 반드시 reducer.** 없으면 `InvalidUpdateError: Can receive only one value per step`
- **루프를 도는 칸은 `operator.add` 를 쓰지 말 것.** 비울 수가 없다.
  `reviews: []` 를 반환해도 아무 일도 일어나지 않는다 — 이게 "처방"이라고 적혀
  있었지만 처방이 아니었다. 회차를 보고 스스로 버리는 reducer
  (`keep_latest_round`)를 쓰고, 이력은 별도 칸(`review_history`)에 남긴다
- **심사 결과에는 반드시 `revision` 을 박을 것.** reducer 가 그 값으로 회차를
  가른다. 빼먹으면 0회차로 취급돼 최신 결과가 버려진다 (`_review()` 를 쓸 것)
- **그래프 노드 이름을 `fn.__name__` 에서 뽑지 말 것.** 테스트가 노드를
  갈아끼우면 이름이 함께 바뀌어 엣지가 끊긴다 (실제로 끊겼다)
- **출처 태그 위치를 가정하지 말 것.** LLM 은 `…줄었어요 [portfolio].` 로,
  Rule 은 `…줄었어요. [portfolio]` 로 쓴다. `normalize_tags_position()` 으로
  통일한 뒤 문장을 가른다. 안 하면 태그가 다음 문장으로 넘어가 전건 반려된다
- **Rule 생성 경로도 3축을 통과해야 한다.** 발표장 안전망이기 때문이다.
  태그 없는 문구나 74자 초과 문구를 내면 `USE_LLM=false` 에서 전건 폴백된다
- **`evidence` 순서에 의존 금지.** 병렬이라 완료 순으로 들어옵니다. `evidence[0]` 대신 `doc` 필드로 조회
- **재작성 제어는 `revision` 카운터로.** `recursion_limit`은 안전망일 뿐
- **폴백 경로 항상 유지.** 생성이 실패해도 기존 41케이스 원본 문구로 카드가 나가야 함
- **케이스별로 Validation 축을 다르게 적용.** `change_type`이 `자산없음`·`자산생김`이면
  시황을 인용하지 않으므로 grounding 면제. 일괄 적용하면 통과 불가능한 문구로 루프만 돕니다

### 문구 생성 규칙 (컴플라이언스)

`check_banned_phrases()`가 1차로 거릅니다.

- 미래 단정 — "반등이 예상됩니다", "회복될 것입니다"
- 투자권유 — "비중을 늘리세요", "지금이 기회", "매수"
- 수익·손실보전 오인 — "보장", "확실", "무조건"

교정 방향은 **미래 단정 → 과거 사실 서술**, **권유 → 구조 설명**.
판단은 고객에게 남기고, 판단에 필요한 재료만 제공합니다.

```
✗ 지금이 저가 매수 기회입니다
✓ 최근 조정으로 가격이 하락했습니다. 보유 비중이 42%로 집중되어 있습니다.
```

### 근거 표기

문장마다 출처 태그를 답니다. 태그 종류를 구분하세요.

- `[일간-261012]` — 외부 사실 주장. 반드시 `evidence`에 있는 문서여야 함
- `[portfolio]` — 자체 계산값(수익률·비중·기여도). 외부 근거 불필요

### 코드 스타일

- 주석·docstring은 한글. 노드 docstring에는 **왜 이 노드가 있는지**를 씁니다
- 노드 함수는 dict를 반환하고 State를 직접 변조하지 않습니다
- Rule로 되는 것은 LLM에 맡기지 않습니다
- 최종 제출은 `.ipynb`(Colab) 또는 `.py` + GitHub. README에 개요·실행법·기능·스택 포함

---

## 8. 이미 겪은 이슈 — 재발 주의

1. **스코어링 가중치** — `personal_briefing`에 기본 가점이 없어 변동률이 작으면
   `domestic_market`에 밀렸습니다. 숫자 하나로 카드가 뒤바뀝니다
2. **grounding 일괄 적용** — 자산없음 케이스가 3회 반려 후 폴백으로 빠졌습니다
3. **`reviews` 미초기화** — 위 "반드시" 항목 참고. 가장 찾기 어려운 버그였습니다
4. **콘텐츠 매칭 위치** — Feedback Loop 안에 두면 재작성 3회 시 API 3회 낭비 + 정확도 하락
5. **`reviews` 미초기화의 진짜 원인** — `operator.add` reducer 자체였습니다.
   `reviews: []` 를 넣어도 비워지지 않습니다. 위 7절 참고
6. **과보수 판정이 과편중에 먹힘** — 국내 채권형 100% 포트폴리오가
   "국내비중 70% 이상"에 먼저 걸려 과편중으로 갔습니다. 과보수를 먼저 봅니다
7. **콘텐츠 상황태그 미스** — `change_type` 을 7종으로 세분화하자
   `situation_to_tag` 의 키(`급락|과편중` 등 5종 어휘)와 안 맞아 태그가 빈
   리스트가 됐습니다. 테이블을 고치지 않고 호출부에서 어휘를 맞춥니다
8. **열람 가점이 영구히 0** — `recent_views` 는 `["ETF"]`, 콘텐츠 태그는
   `["#ETF"]` 라서 교집합이 항상 비었습니다. `normalize_tags()` 로 통일했습니다

---

## 8-2. 화면 규칙 (2026-10 개정 · `asis.png` 기준)

실제 투자홈 캡처를 받고 확정한 것입니다. `docs/PLAN_2610.md` 2-5~2-7 참고.

- **주색은 보라(#6B4EFF)입니다.** 초판 기획서의 "KB 톤 노랑"은 실물과 다릅니다.
  노랑은 자산 영역 그라데이션과 보조 강조에만 씁니다
- **상승 = 빨강(#E8453C) / 하락 = 파랑(#2B6CF6).** 한국 증시 관례이고 실물
  화면도 그렇습니다. 반대로 칠하면 **오독을 만드는 오류**입니다
- **AS-IS 는 카드 한 장이 아니라 "자리 하나 + 후보 4종"입니다.** 네 슬롯을
  모두 그리고 어느 것이 뽑혔는지 표시합니다. 랜덤의 문제를 말로 설명하지 않고
  보여주는 것이 데모의 핵심입니다
- **카드 내부 요소는 block 으로.** `<span>` 을 세로로 쌓으려면
  `display:flex; flex-direction:column`. 인라인이면 제목·요약·발행처가
  **줄바꿈 없이 붙습니다** (실제로 붙었습니다)
- **각 블록에 섹션 헤더를 답니다.** 글이 줄줄이 이어지면 읽히지 않습니다

### "제가 본 점검 포인트" — PB 느낌을 만드는 블록

`card_spec.diagnosis`(Rule 진단값)로 조립합니다. **새 LLM 호출이 없습니다.**

**투자권유가 되지 않도록 "확인해 보세요"까지만 씁니다.** 보유 구조와 하우스뷰
권고의 **차이를 설명**할 뿐이고 판단은 고객에게 남깁니다. "비중을 줄이세요"
같은 표현은 이 블록에서도 금지입니다 — 화면 문구라고 예외가 아닙니다.

## 8-3. MCP — 시황·뉴스 Tool 은 서버로 분리돼 있다

`mcp_servers/market_server.py` (`kb-market`, 도구 6종). 그래프는
`src/mcp_client.py` 를 거쳐 부릅니다.

- **고객 데이터를 MCP 서버로 넘기지 말 것.** `news_for_holdings` 는 종목명만
  받습니다. 보유 금액·비중·고객번호는 Agent 쪽에 남습니다
- **MCP 실패는 예외가 아니라 폴백입니다.** `mcp_client` 가 직접 호출로
  떨어지고 로그에 `(직접 · …)` 으로 찍힙니다. 발표장 리스크를 없애는 설계이니
  "MCP 없으면 죽는" 코드를 새로 쓰지 말 것
- 판정(좋음/보통/나쁨)은 **서버가 단일 정의를 갖습니다.** 호출부에서 다시
  판정하면 팀마다 임계값이 갈립니다
- `mcp` 는 **v1 계열로 고정**합니다. 2.x 는 `FastMCP` 를 `MCPServer` 로
  rename 했고 교육과정 노트북 16곳이 `FastMCP` 를 씁니다

```bash
./run_local.sh mcp        # 서버
./run_local.sh mcptest    # 도구 6종 호출 확인
```

## 9. 하지 말 것

- 카드 종류 추가 (**4종 고정**)
- `evidence`와 `contents` 병합
- **Runtime(고객 실시간) 경로에 LLM 호출 추가**
- 사내 API 실연동, 실데이터 사용
- 콘텐츠 매칭을 Feedback Loop **안**에 배치
- 투자권유로 읽힐 수 있는 문구를 폴백 텍스트에 넣기
- **대고객 문구에 `[portfolio]`나 출처 코드를 노출하기** — `sources.py`를 거칠 것
- 뉴스를 `contents`에 합치기 — 뉴스는 `evidence`(검증 대상),
  KB Think 콘텐츠는 `contents`(검증 대상 아님). 성격이 다릅니다
- 뉴스 본문 크롤링 — 제목·발행처·링크까지만. 저작권 문제가 있고
  링크로 보내는 것이 고객에게도 낫습니다
- **채팅형 UI를 실시간 응답으로 바꾸기** — 2절 경고 참고
- **고객 자유 입력창 열기** — 질문 칩(`src/followups.py`)만 허용합니다.
  고객이 무엇을 물을지 모르면 답을 미리 검수할 수 없습니다
- **당일 시황(1분 브리핑·시황 포맷)을 '이어서 읽어볼 콘텐츠'에 넣기** —
  본문과 근거에서 이미 다룹니다. 같은 내용이 두 번 나옵니다
- **시장지표를 대고객 출처 칩으로 노출하기** — 시황 보드에 숫자가 이미 있습니다.
  grounding 심사용으로 내부 표기에는 남깁니다
- **고객 화면에 `case_id` 노출하기** — 내부 식별자입니다
- **MCP 서버에 고객 데이터 넘기기** — 8-3절 참고
- **MCP 실패 시 예외를 던지기** — 폴백으로 떨어뜨릴 것
- **상승을 파랑, 하락을 빨강으로 칠하기** — 8-2절 참고
- **"제가 본 점검 포인트"에 행동 지시 넣기** — 설명까지가 범위입니다
- 카드 내부 `<span>`을 인라인으로 두기 — 글이 붙습니다
- 41케이스 판정 로직을 LLM으로 대체
- `USE_LLM = False` 경로를 깨뜨리는 변경

---

## 10. 미확정 — 구현 시 추정값 사용하고 TODO로 남길 것

- 국내/해외 전망 중 무엇을 쓸지 결정하는 기준 — 보유자산 지역 비중이 큰 쪽을
  쓰도록 구현했습니다(`diagnose`). 자산이 없으면 국내. 확정 필요
- CASE1~9 원문 대조 (`verified: false`)
- CASE16 `{diffAmt}` 슬롯 누락 (원본 오류 추정)
- CASE12 = CASE29, CASE15 = CASE32 완전 동일 (30일 초과인데 "오랜만에 방문" 미반영)
- 단기시장전망 6종의 데이터 출처 — Yahoo Finance 코스피/S&P500 전일 등락률에
  ±0.5% 임계로 좋음·보통·나쁨을 판정하도록 구현했습니다(`market_tool.outlook`).
  현업이 쓰는 기준과 일치하는지 확인 필요
- `curAmt` 슬롯이 41건 전체에서 사용 0회입니다. `_meta.slots` 정의만 있습니다
- CASE18=CASE35, CASE21=CASE38 도 완전 동일합니다 (아래 목록은 2쌍만 적었음)
