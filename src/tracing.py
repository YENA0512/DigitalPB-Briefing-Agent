"""
Langfuse — 심사 결과를 **점수로 남긴다**.

## 왜 필요한가

"LLM 이 틀린 문구를 쓰면?" 에 "3축 심사가 거릅니다"라고 답하면 다음 질문은
**"그 심사가 잘 돌고 있는지는 어떻게 아나요?"** 다. 그 답이 여기 있다.

매일 41건을 돌리면서 이걸 쌓는다.

    compliance_pass   컴플라이언스 통과 여부 (0/1)
    grounding_pass    근거 결속 통과 여부
    format_pass       형식 통과 여부
    revisions         재작성 횟수 — 올라가면 프롬프트가 나빠진 것이다
    fallback          폴백 여부 — 올라가면 생성이 실패하고 있다
    llm_calls         호출 수 — 비용

**프롬프트를 고쳤을 때 폴백률이 내려갔는지를 숫자로 본다.**
실제로 글자수 한도를 74→220 으로 올렸을 때 LLM 호출이 23→15회로 줄고
폴백이 사라진 것을 이 지표로 확인했다.

## 없어도 돈다

키가 없으면 전부 no-op 이다. 관측은 **있으면 좋은 것**이고 없다고
브리핑이 멈추면 안 된다.
"""

import config

_client = None
_state = "미초기화"
_last_error = ""


def enabled() -> bool:
    return config.LANGFUSE_ENABLED


def client():
    global _client, _state
    if _client is not None or not enabled():
        return _client
    try:
        from langfuse import Langfuse
        _client = Langfuse(public_key=config.LANGFUSE_PUBLIC_KEY,
                           secret_key=config.LANGFUSE_SECRET_KEY,
                           host=config.LANGFUSE_HOST)
        _state = f"연결됨 ({config.LANGFUSE_HOST})"
    except Exception as exc:                     # noqa: BLE001
        _client, _state = None, f"미사용 ({type(exc).__name__})"
    return _client


def state() -> str:
    if not enabled():
        return "미사용 (키 없음)"
    client()
    return _state


def handler():
    """LangGraph `config={"callbacks": [...]}` 에 넣을 콜백.

    그래프 전체가 하나의 trace 가 되고 LLM 호출이 그 안에 span 으로 붙는다.
    """
    if not enabled():
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception:                            # noqa: BLE001
        return None


def callbacks() -> list:
    h = handler()
    return [h] if h else []


def metrics_of(spec: dict) -> dict:
    """card_spec 에서 지표를 뽑는다. Langfuse 유무와 무관하게 쓸 수 있다."""
    rv = spec.get("review", {})
    return {
        "compliance_pass": int(bool(rv.get("compliance", {}).get("passed"))),
        "grounding_pass": int(bool(rv.get("grounding", {}).get("passed"))),
        "format_pass": int(bool(rv.get("format", {}).get("passed"))),
        "revisions": int(spec.get("review_rounds", 1)) - 1,
        "fallback": int(bool(spec.get("fallback_used"))),
        "llm_calls": int(spec.get("llm", {}).get("calls", 0)),
        "sources": len(spec.get("sources", [])),
    }


def score_card(spec: dict, case_id: str | None = None,
               trace_id: str | None = None) -> str | None:
    """완성된 card_spec 을 점수로 기록하고 trace URL 을 돌려준다.

    Langfuse 는 점수를 **trace 에 붙인다.** 떠 있는 trace 가 없으면
    케이스 하나당 span 을 하나 열고 거기에 붙인다. 그래야 대시보드에서
    케이스별로 펼쳐 볼 수 있다.
    """
    c = client()
    if c is None:
        return None
    cid = case_id or spec.get("case_id", "unknown")
    scores = metrics_of(spec)
    try:
        with c.start_as_current_observation(
                as_type="span", name=f"briefing-{cid}",
                input={"case_id": cid, "card_type": spec.get("card_type"),
                       "change_type": spec.get("diagnosis", {}).get("change_type"),
                       "gap_type": spec.get("diagnosis", {}).get("gap_type")},
                output={"advice": spec.get("advice_plain", "")[:400],
                        "sources": [x.get("doc") for x in spec.get("sources", [])
                                    if isinstance(x, dict)]},
                metadata={"model": spec.get("llm", {}).get("model"),
                          "approval": spec.get("approval", {}).get("action")}) as span:
            for name, value in scores.items():
                span.score_trace(name=name, value=value, data_type="NUMERIC")
            tid = span.trace_id
        c.flush()
        return c.get_trace_url(trace_id=tid) if tid else None
    except Exception as exc:                     # noqa: BLE001
        #  관측은 있으면 좋은 것이다. 실패해도 브리핑을 멈추지 않는다.
        #  다만 왜 안 되는지는 알아야 하므로 사유를 남긴다.
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        return None


def flush() -> None:
    c = client()
    if c is not None:
        try:
            c.flush()
        except Exception:                        # noqa: BLE001
            pass


if __name__ == "__main__":
    print("Langfuse:", state())
    if enabled():
        print("콜백 핸들러:", "OK" if handler() else "실패")
        spec = {"case_id": "CASE19", "card_type": "personal_briefing",
                "advice_plain": "테스트 문구",
                "review": {"compliance": {"passed": True},
                           "grounding": {"passed": True},
                           "format": {"passed": False}},
                "review_rounds": 2, "fallback_used": False,
                "llm": {"calls": 4, "model": "gpt-5.5"},
                "sources": [{"doc": "일간-261012"}, {"doc": "뉴스-1"}],
                "diagnosis": {"change_type": "하락", "gap_type": "과편중"},
                "approval": {"action": "approve"}}
        print("지표:", metrics_of(spec))
        url = score_card(spec)
        print("기록:", url or f"실패 — {_last_error}")
