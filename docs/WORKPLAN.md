# WORKPLAN.md — Claude Code 작업 지시서

최종발표 **2026-10-17**. 오늘 기준 5일.
각 STEP의 ``` 블록을 **그대로 복사해 Claude Code에 붙여넣으면** 됩니다.

---

## 0. 시작 전 1회

```bash
mkdir -p digital-pb-briefing && cd digital-pb-briefing
git init
# cases_41.json, case_router.py, briefing_agent.py,
# content_matcher.py, kbthink_contents.json, pattern_lab.py, CLAUDE.md 복사
claude
```

Claude Code를 켜고 가장 먼저:

```
CLAUDE.md를 읽고 이 프로젝트의 구조를 파악해줘.
그다음 현재 코드(briefing_agent.py, case_router.py, content_matcher.py)가
CLAUDE.md의 설계와 어긋나는 부분이 있으면 목록으로만 알려줘. 수정은 아직 하지 마.
```

> **매 STEP 끝에 반드시** `python briefing_agent.py`가 `USE_LLM = False`에서
> 에러 없이 끝까지 도는지 확인하세요. 이게 발표장 안전망입니다.

---

## STEP 1 — 저장소 기반 공사 *(10/13 오전, 1시간)*

```
저장소 기반을 만들어줘. 순서대로 진행하고 각 단계마다 결과를 보여줘.

1. 디렉터리 구조를 아래로 정리해줘. 기존 파일은 이동만 하고 내용은 건드리지 마.
   src/        briefing_agent.py, case_router.py, content_matcher.py
   data/       cases_41.json, kbthink_contents.json
   lab/        pattern_lab.py
   notebooks/  (비워둠)
   루트에 CLAUDE.md, README.md, requirements.txt, .env.example, .gitignore

2. .gitignore에 .env, __pycache__/, .ipynb_checkpoints/, *.pyc, .DS_Store를 넣어줘.

3. .env.example을 만들어줘. 실제 키는 절대 쓰지 말고 플레이스홀더만.
   ANTHROPIC_API_KEY=sk-ant-xxxx
   (또는 OPENAI_API_KEY — 교육과정에서 쓰는 쪽에 맞춰줘)

4. src/config.py를 만들어줘.
   - python-dotenv로 .env 로드
   - USE_LLM 플래그를 환경변수 USE_LLM(기본 false)에서 읽게
   - 키가 없으면 경고만 출력하고 USE_LLM을 강제로 False로 내릴 것 (죽지 말 것)

5. requirements.txt: langgraph, langchain, langchain-anthropic(또는 openai),
   python-dotenv, chromadb, pydantic. 버전은 핀 걸지 말고 이름만.

6. 경로 수정 때문에 import가 깨진 곳을 고쳐줘.
   data 파일 경로는 __file__ 기준 상대경로로. 실행 위치에 의존하지 말 것.

마지막에 python src/briefing_agent.py가 도는지 확인하고, 안 되면 고쳐줘.
```

**완료 기준** — `python src/briefing_agent.py` 정상 종료, `git status`에 `.env` 안 보임

---

## STEP 2 — RAG 연동 *(10/13 오후 ~ 10/14 오전)*

### 2-1. 목 리포트 작성

```
data/reports/ 를 만들고 시황 리포트 목데이터를 작성해줘.

- 일간 5건, 주간 2건, 월간 1건. 총 8건. 각각 마크다운 파일.
- 파일명 규칙: daily-261006.md, weekly-2610W1.md, monthly-2610.md
- 각 파일 상단에 frontmatter: doc(문서ID), title, date, period, region
- 본문은 실제 증권사 데일리 톤으로 300~500자.
  국내 증시 / 해외 증시 / 환율 / 특정 섹터 코멘트가 섞이게.
- 실제 종목명과 수치를 쓰되 가공된 목데이터임을 frontmatter에 mock: true로 표기.
- 반도체 섹터 급락을 다루는 일간 리포트를 최소 1건 포함해줘.
  (MOCK_PORTFOLIOS의 '반도체편중' 케이스 데모에 쓸 것)
```

### 2-2. 벡터 검색 교체

```
src/retriever.py를 만들고 briefing_agent.py의 _retrieve()를 교체해줘.

- Chroma + 로컬 임베딩. 인덱스는 .chroma/에 저장하고 .gitignore에 추가.
- 청킹은 문단 단위. 메타데이터에 doc, title, date, period를 넣을 것.
- build_index() — data/reports/*.md를 읽어 인덱싱. 멱등하게(중복 삽입 금지).
- search(period, query, k=2) — period로 필터링 후 유사도 검색.
  반환 형식은 기존 _retrieve()와 동일하게 [{"doc":..., "title":..., "text":...}].

중요:
- 검색 결과가 0건이면 빈 리스트가 아니라 기존 스텁값을 반환해줘.
  evidence가 비면 generate가 근거 없이 쓰게 되고 grounding이 전부 반려된다.
- USE_LLM과 무관하게 동작해야 함. 임베딩은 LLM 호출이 아님.
- search_daily / search_weekly / search_monthly 세 노드가 병렬로 호출하므로
  인덱스 로딩은 모듈 레벨에서 1회만.

교체 후 python src/briefing_agent.py로 evidence가 실제 리포트에서 오는지 확인해줘.
```

### 2-3. LLM 문구 생성

```
_generate_with_llm()을 구현해줘.

- src/prompts.py에 프롬프트를 분리해줘. 코드에 하드코딩하지 말 것.
- 프롬프트 구성:
  · 역할: KB국민은행 투자홈 브리핑 문구 작성자
  · 입력: case_id, 41케이스 원본 문구, 진단 결과(metrics/change_type/gap_type),
         evidence 본문
  · few-shot: cases_41.json에서 같은 축에 속하는 케이스 문구 2~3개를 예시로 투입
  · 제약: 상세조언 13~74자 / 문장마다 출처 태그 / 금지어 목록 명시 /
         투자권유 금지 / 미래 단정 금지
- with_structured_output으로 {advice, tags} 형태를 받아줘. 파싱 실패 대비.
- LLM 호출 실패 시 예외를 밖으로 던지지 말고 41케이스 원본 문구를 반환하고
  state에 fallback 사유를 로그로 남겨줘.

USE_LLM=true로 1회 실행해서 실제 문구가 나오는지 확인하고,
USE_LLM=false로도 여전히 도는지 둘 다 확인해줘.
```

**완료 기준** — 같은 케이스를 3회 돌렸을 때 서로 다른 문구가 나오고, 전부 출처 태그가 붙음

---

## STEP 3 — 3축 Validation + Feedback Loop *(10/14 오후 ~ 10/15 오전)*

```
Validation을 3축으로 확장해줘. 세 노드가 generate 다음에 병렬로 붙는다.

[1] review_compliance — Rule 1차 + LLM 2차 하이브리드
    - check_banned_phrases()로 명백한 금지어를 먼저 거른다 (기존 유지)
    - Rule 통과분만 LLM에 넘겨서 애매한 투자권유 표현을 판정
    - with_structured_output으로 {passed: bool, issues: list[str], reason: str}
    - USE_LLM=False면 Rule 결과만 사용

[2] review_grounding — 문장 단위 검증으로 승격
    - 문구를 문장으로 쪼갠다
    - 각 문장의 출처 태그를 확인:
      [portfolio] → metrics에서 계산 가능한 값인지 확인, 외부 근거 불필요
      [일간-xxx] 등 → evidence에 해당 doc이 있는지 + 그 본문이 주장을 지지하는지
    - 태그 없는 사실 주장 문장이 있으면 반려
    - change_type이 '자산없음'·'자산생김'이면 전체 면제하고 passed=True
      (이거 빼먹으면 3회 반려 후 폴백으로 빠진다. 이미 한 번 겪었음)

[3] review_format — 신규. 전부 Rule, LLM 쓰지 말 것
    - 상세조언 13~74자 / 서브조언 14~18자 / 버튼명 11~15자
    - 슬롯 검사: {days} {diffAmt} {curAmt} 중 해당 케이스에 필요한 게 있는지,
      정의되지 않은 슬롯이 들어가 있지 않은지
    - 금액 표기 규칙 준수 (억원 미만은 원 단위, 억원 이상은 X억 X만원)
    - 문장 수 3~4문장 이내

[4] aggregate / route_after_review
    - 세 축 중 하나라도 실패하면 반려
    - revision >= 3이면 fallback
    - 어느 축이 왜 반려했는지 logs에 남길 것

[5] optimize
    - 세 축의 지적사항을 모아 LLM에 재작성 요청
    - reviews: [] 를 반드시 넣을 것. 안 넣으면 1회차 실패 기록이 남아
      영원히 통과하지 못한다
    - 세 review 노드 전부로 복귀하는 엣지를 걸 것

그래프 조립도 같이 고쳐줘. fan-in 하는 reviews에 reducer가 걸려 있는지 확인.
```

### 3-1. 루프 테스트

```
tests/test_loop.py를 만들어줘. pytest 말고 그냥 python으로 돌아가는 스크립트여도 돼.

검증 항목:
1. 금지어가 든 draft를 강제 주입했을 때 → optimize로 가고, 재작성 후 통과하는지
2. 3회 반려되면 fallback으로 빠지는지, fallback_used=True인지
3. '자산없음' 케이스가 grounding 면제를 받아 1회에 통과하는지
4. reviews를 비우지 않으면 무한 반려된다는 걸 보여주는 회귀 테스트
   (일부러 reviews: [] 를 빼고 돌려서 3회 돌고 폴백되는 걸 확인)
5. MOCK_PORTFOLIOS 전 케이스가 에러 없이 완주하는지

각 테스트는 통과/실패와 함께 logs를 출력해줘. 발표에서 이 출력을 보여줄 거야.
```

**완료 기준** — 5개 테스트 전부 통과, 4번에서 "reviews 초기화의 중요성"이 출력으로 보임

---

## STEP 4 — HITL + 콘텐츠 매칭 *(10/15 오후)*

```
Human-in-the-Loop과 콘텐츠 매칭을 붙여줘. 순서가 중요하다.

흐름:  aggregate → (통과) → match_contents → human_review → finalize → END

[1] match_contents
    - content_matcher.py를 노드로 감싸서 붙여줘
    - 반드시 Feedback Loop 밖, 확정 문구 기준으로 매칭
      (루프 안에 넣으면 재작성 3회 시 API 3회 낭비 + 매칭 정확도 하락)
    - 결과는 state['contents']에 넣는다. evidence에 절대 넣지 말 것
    - 최대 2건

[2] human_review — interrupt() 사용
    - finalize 바로 앞
    - interrupt()로 담당자에게 넘길 페이로드:
      {case_id, advice, 서브조언, 버튼명, evidence, contents, review 결과,
       selected_over, selection_reason}
    - Command(resume)로 받는 결정 3갈래:
      approve        → 그대로 finalize
      edit           → 담당자가 고친 문구로 교체 후 finalize (재심사 안 함, 사람 책임)
      reject(사유)   → revision+1, reviews: [], optimize로 돌려보냄
    - 승인자와 시각을 card_spec에 남길 것 (감사 추적)
    - checkpointer는 InMemorySaver 유지. thread_id는 case_id로.

[3] 배치 러너 — src/run_batch.py
    - 41케이스를 순회하며 그래프를 돌린다
    - human_review에서 멈춘 케이스를 output/pending/*.json에 쌓는다
    - 승인된 건은 output/approved/*.json으로 이동
    - --auto-approve 플래그를 주면 HITL을 건너뛴다 (데모·테스트용)
    - 41건 전체 실행 시간과 폴백 건수를 집계해 출력

CLI로 interrupt를 어떻게 재개하는지 README에 예시를 적어줘.
```

**완료 기준** — `python src/run_batch.py --auto-approve`가 41건을 완주하고 집계가 나옴

---

## STEP 5 — 데모 뷰어 *(10/16 오전)*

```
발표용 데모 뷰어를 만들어줘. demo/viewer.html 단일 파일, 외부 의존성 없이.

레이아웃: 좌우 2분할
  좌 — 현재 방식: 카드 4종 중 랜덤 1택, 고정 문구, 근거 없음
  우 — Agent 방식: 선택된 카드 + 생성 문구 + 출처 태그 + 선택 이유

우측에 반드시 노출할 것:
  - selected_over — "제친 카드 3종". 랜덤과의 차이를 보여주는 핵심
  - selection_reason
  - 문장별 출처 태그를 클릭하면 evidence 원문이 펼쳐지게
  - review 3축 결과 배지 (통과/반려, 재작성 N회)
  - fallback_used일 때 눈에 띄게 표시

상단에 고객 케이스 선택 드롭다운. output/approved/*.json을 읽어 전환.
(파일 fetch가 막히면 JSON을 html에 인라인으로 박아줘. 발표장 환경을 믿지 말 것)

하단에 실행 로그 타임라인. logs 배열을 순서대로. 병렬 구간은 들여쓰기로 구분.

디자인:
  KB 톤. 노랑 #FFBC00, 먹색 #3E3A34, 회색 #6B6560, 라인 #E5E1DB.
  모바일 카드처럼 보이게 좌우 패널 안에 390px 폭 목업 프레임.
  과한 애니메이션 금지. 발표 화면에서 또렷하게 보이는 게 우선.
```

**완료 기준** — 브라우저에서 열어 케이스를 바꿔가며 좌우 차이가 한눈에 보임

---

## STEP 6 — 제출물 정리 *(10/16 오후)*

```
제출물을 정리해줘.

[1] notebooks/digital_pb_briefing.ipynb
    교육과정 제출용. 셀 순서:
    1) 설치 + import
    2) 문제 정의 (마크다운, CLAUDE.md의 문제 정의/기대효과 인용)
    3) 41케이스 구조와 case_router 동작 — 커버리지 검증 출력 포함
    4) State 정의와 reducer 설명
    5) 노드별 코드 + 왜 이 노드가 있는지
    6) 그래프 조립 + draw_mermaid_png() 출력  ← 설계-구현 일치 증빙. 꼭 넣을 것
    7) 실행 데모 — 반도체편중 / 신규고객 / 자산없음 3케이스
    8) Feedback Loop 동작 — 반려되고 재작성되는 로그
    9) 패턴 비교 (pattern_lab.py 결과)
    10) 한계와 다음 단계
    마크다운 설명을 충분히. 코드만 나열하지 말 것.

[2] README.md
    - 프로젝트 개요 (문제 정의 → 해결 방식)
    - 아키텍처 다이어그램 (mermaid)
    - 실행 방법: 설치 / .env 설정 / USE_LLM=false 실행 / USE_LLM=true 실행
    - 기능 목록
    - 기술 스택: LangGraph, LangChain, Chroma(RAG), Tool, Memory(Checkpointer),
      HITL(interrupt), Structured Output
    - 적용한 LangGraph 패턴과 선택 이유 표
    - 한계와 향후 과제
    - "본 저장소의 모든 데이터는 목데이터입니다" 명시

[3] 최종 점검
    - git log와 전체 파일에서 API 키, 사번, 고객번호, 내부 URL, 내부 IP 유출 확인
    - .env가 커밋되지 않았는지
    - 클린 환경 가정: requirements.txt만으로 설치되는지
    - USE_LLM=false로 전체가 도는지 마지막으로 확인
```

**완료 기준** — 노트북을 처음부터 끝까지 Run All 했을 때 에러 없이 끝까지 감

---

## STEP 7 — 발표 준비 *(10/16 저녁 ~ 10/17)*

Claude Code가 아니라 여기(대화)에서 진행할 것:

- 최종발표 PPT — 중간발표 덱 기반으로 구현 결과 중심 재구성
- 데모 시연 순서 확정 (화면 전환 최소화, 1분 이내)
- 발표 대본 + 낭독 시간 측정
- 예상 질문 정리
  - "LLM이 틀린 문구를 쓰면?" → 3축 Validation + 담당자 승인 + 폴백
  - "비용은?" → Batch 1일 41회. Runtime에 LLM 없음
  - "실서비스 적용 시 걸림돌은?" → 내부 데이터 연동, 검수 공수, 금소법 검토

---

## 일정 요약

| 날짜 | STEP | 산출물 |
|---|---|---|
| 10/13 오전 | 1 | 저장소 구조, config, .env |
| 10/13 오후~10/14 오전 | 2 | RAG 연동, LLM 문구 생성 |
| 10/14 오후~10/15 오전 | 3 | 3축 Validation, Feedback Loop, 루프 테스트 |
| 10/15 오후 | 4 | HITL, 콘텐츠 매칭, 배치 러너 |
| 10/16 오전 | 5 | 데모 뷰어 |
| 10/16 오후 | 6 | 노트북, README, 보안 점검 |
| 10/16 저녁~10/17 | 7 | 발표자료, 리허설 |

**시간이 모자라면 버리는 순서**: STEP 5 뷰어 고도화 → STEP 2-3 LLM 생성 품질 →
STEP 4 배치 러너. **STEP 3(3축 Validation)과 STEP 6(노트북)은 버리지 마세요.**
평가 기준의 핵심입니다.

---

## Claude Code 사용 팁

- 한 STEP이 끝날 때마다 커밋하세요. `git commit -m "STEP 3: 3축 Validation"`
- 코드가 꼬이면: `git stash` 후 되돌리고 STEP 프롬프트를 더 작게 쪼개 다시
- Claude Code가 CLAUDE.md 규칙을 어기면 그대로 지적하세요.
  "CLAUDE.md 9장에 Runtime 경로에 LLM 추가 금지라고 돼 있어. 다시 해줘."
- 설계를 바꾸고 싶으면 코드보다 **CLAUDE.md를 먼저** 고치고 "CLAUDE.md 다시 읽고 반영해줘"
- 긴 작업 전에 `/clear`로 컨텍스트를 비우고 CLAUDE.md부터 다시 읽히는 게 안전합니다
