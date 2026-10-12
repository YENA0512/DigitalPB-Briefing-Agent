# Langfuse — 어디서 어떻게 보나

## 1. 접속 — 루트로 가면 빈 화면입니다

`https://cloud.langfuse.com` 로 들어가면 **아무것도 안 보입니다.**
프로젝트 경로까지 들어가야 합니다.

| | 주소 |
|---|---|
**Traces** | https://cloud.langfuse.com/project/cmtnydiiv07k3ad0dmcofht1y/traces |
**Scores** | https://cloud.langfuse.com/project/cmtnydiiv07k3ad0dmcofht1y/scores |
대시보드 | https://cloud.langfuse.com/project/cmtnydiiv07k3ad0dmcofht1y |

프로젝트는 **My Project** (Yena's Organization) 입니다.
앱 사이드바 하단에 이 링크가 걸려 있고, 결과 패널에는 그 실행의 직링크가 뜹니다.

```bash
./run_local.sh trace      # 연결 확인 + 주소 출력
```

## 2. 무엇이 올라가는가

### Traces — 실행 1건 = trace 1개

왼쪽 메뉴 **Tracing → Traces**. 이름이 `브리핑 CASE19` 형태입니다.
하나를 열면 **노드 실행과 MCP 도구 호출이 전부 하위 관측으로** 들어 있습니다.

```
브리핑 CASE25            관측 33개 · 점수 7개
├ diagnose
├ search_daily · search_weekly · search_monthly        (병렬)
├ search_market · search_news
│   └ get_market_view · get_market_evidence · news_for_holdings   (MCP)
├ generate                프롬프트 · 응답 · 토큰 · 지연
├ review_compliance · review_grounding · review_format (병렬)
├ match_contents
└ finalize
```

> trace 가 `LangGraph` 와 `briefing-*` 로 **둘로 갈려 있던 적이 있습니다.**
> LangChain 콜백이 만드는 trace 와 점수를 붙이려 따로 연 span 이 별개여서,
> "이 케이스의 LLM 호출과 심사 점수"를 한 화면에서 볼 수 없었습니다.
> `tracing.trace_run()` 으로 **먼저 span 을 열어** 콜백 span 들이 그 아래로
> 들어가게 했습니다. 지금은 하나입니다.

| 보이는 것 | 내용 |
|---|---|
Input | `case_id` · `card_type` · `change_type` · `gap_type` |
Output | 생성된 문구 · 인용한 출처 doc 목록 |
Metadata | 모델 · 검수 결정(approve/edit/reject) |
하위 span | **LLM 호출마다 프롬프트·응답·토큰·지연** |

trace 를 열면 `generate` → `review_compliance` → `review_grounding` →
`optimize` 가 순서대로 펼쳐집니다. **어느 심사가 무엇을 지적해서 재작성이
돌았는지**를 프롬프트 수준에서 볼 수 있습니다.

카드 스펙의 `trace_url` 필드에 직링크가 박혀 있고, 앱 하단에도
`🔎 Langfuse 에서 이 실행 보기` 링크가 뜹니다.

### Scores — 심사 품질 7종

trace 상세의 **Scores** 탭, 또는 왼쪽 **Scores** 메뉴.

| 점수 | 의미 | 보는 법 |
|---|---|---|
`compliance_pass` | 컴플라이언스 통과 (0/1) | 평균이 1 미만이면 금지어가 새고 있다 |
`grounding_pass` | 근거 결속 통과 | 떨어지면 할루시네이션이 늘고 있다 |
`format_pass` | 형식 통과 | 떨어지면 글자수 한도가 빡빡하다 |
`revisions` | 재작성 횟수 | **올라가면 프롬프트가 나빠진 것** |
`fallback` | 폴백 여부 | **올라가면 생성이 실패하고 있다** |
`llm_calls` | 호출 수 | 비용 |
`sources` | 인용한 출처 수 | 0이면 근거 없는 문구다 |

## 3. 발표에서 쓰는 법

"LLM 이 틀린 문구를 쓰면?" 에 "3축 심사가 거릅니다"라고 답하면 다음 질문은
**"그 심사가 잘 돌고 있는지는 어떻게 아나요?"** 입니다. 그 답이 이 대시보드입니다.

실제로 이걸로 확인한 것:

> 글자수 한도를 **74자 → 220자**로 올렸더니
> **LLM 호출 23 → 15회**, **폴백 1건 → 0건**.
> 74자로는 "변동 + 기여 + 원인"이 안 들어가 계속 형식 반려가 났던 것이다.
> **제약을 풀었더니 비용이 내려간** 역설적인 결과.

프롬프트를 고쳤을 때 `revisions` 평균과 `fallback` 합계가 어떻게 움직이는지를
보는 것이 이 지표의 용도입니다.

## 4. 데이터 쌓기

```bash
./run_local.sh batch -- --auto-approve --limit 10   # 10건 → trace 10개
./run_local.sh batch -- --auto-approve              # 41건 (약 19분)
```

배치 출력 끝에 `Langfuse N건 기록` 이 찍히면 올라간 것입니다.
`USE_LLM=false` 로 돌리면 trace 는 생기지만 LLM span 은 없습니다.

## 5. `Project Not Found` 가 뜰 때

**브라우저가 다른 계정으로 로그인돼 있는 것입니다.** 키는 정상입니다.

Langfuse 대시보드는 **브라우저 세션이 키를 발급한 계정과 같아야** 열립니다.
이 프로젝트의 키는 다음에 속합니다.

```
리전     cloud.langfuse.com  (EU)
조직     Yena's Organization   cmtnydiir07jzad0dudhaac1o
프로젝트  My Project            cmtnydiiv07k3ad0dmcofht1y
```

브라우저 우측 상단 계정을 확인하고, `Yena's Organization` 이 안 보이면
키를 발급한 계정으로 로그인하세요.
조직 주소: https://cloud.langfuse.com/organization/cmtnydiir07jzad0dudhaac1o

### 로그인 없이 보는 방법 — 발표에서는 이쪽을 쓰세요

지표를 **API 로 직접 읽어** 앱 안에 띄웁니다. 브라우저 로그인 상태와 무관합니다.

```bash
./run_local.sh obs          # 터미널에서 집계 출력
```

앱 사이드바에서 `관측 지표 새로고침` 을 누르면 결과 패널에
**관측 — 최근 N건 심사 품질** 섹션이 생깁니다. 통과율·재작성 평균·폴백 합계와
최근 실행 목록이 표로 뜹니다.

> 발표장에서 외부 사이트 로그인에 데모가 걸리면 안 됩니다.
> 대시보드는 깊이 파고들 때 쓰고, 보여줄 숫자는 앱이 직접 가져옵니다.

## 6. 그 밖에 안 될 때

| 증상 | 원인 |
|---|---|
사이드바에 `미사용 (키 없음)` | `.env` 에 `LANGFUSE_*` 키가 없음 |
`미사용 (ImportError)` | `pip install langfuse` |
기록은 되는데 대시보드가 비어 있음 | 플러시 지연. 10초 후 새로고침 |
`trace_url` 이 없음 | 그 건이 Langfuse 없이 생성됨. 다시 배치 |

**키가 없어도 브리핑은 그대로 돕니다.** 관측은 있으면 좋은 것이고
없다고 멈추면 안 됩니다 — `src/tracing.py` 의 모든 함수가 no-op 로 떨어집니다.
