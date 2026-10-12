# Langfuse — 어디서 어떻게 보나

## 1. 접속

**https://cloud.langfuse.com** · 프로젝트 **My Project** (Yena's Organization)

`.env` 의 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` 로 연결됩니다.
앱 사이드바 하단에 연결 상태와 바로가기가 떠 있습니다.

```bash
./run_local.sh trace      # 연결 확인 + 테스트 기록 1건
```

## 2. 무엇이 올라가는가

### Traces — 실행 1건 = trace 1개

왼쪽 메뉴 **Tracing → Traces**. 이름이 `브리핑 CASE19` 형태입니다.

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

## 5. 안 될 때

| 증상 | 원인 |
|---|---|
사이드바에 `미사용 (키 없음)` | `.env` 에 `LANGFUSE_*` 키가 없음 |
`미사용 (ImportError)` | `pip install langfuse` |
기록은 되는데 대시보드가 비어 있음 | 플러시 지연. 10초 후 새로고침 |
`trace_url` 이 없음 | 그 건이 Langfuse 없이 생성됨. 다시 배치 |

**키가 없어도 브리핑은 그대로 돕니다.** 관측은 있으면 좋은 것이고
없다고 멈추면 안 됩니다 — `src/tracing.py` 의 모든 함수가 no-op 로 떨어집니다.
