"""
패턴 비교 실습 — 같은 일을 네 가지 구조로 구현하고 실제로 돌려본다.

과제: 일간·주간·월간 리포트를 모아 브리핑 초안을 만든다.
각 검색은 0.4초 걸린다고 가정한다.

  A. Chaining          순차 실행
  B. Parallel          fan-out / fan-in
  C. Parallel (버그)   reducer 없이 병렬 — 무슨 일이 벌어지나
  D. Orchestrator      Send API 로 워커 수를 동적으로 결정
"""

import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

LATENCY = 0.4
PERIODS = ["daily", "weekly", "monthly"]
TITLES = {
    "daily":   "반도체 투심 위축에 코스피 하락",
    "weekly":  "8월 4주차 주간 금융시장 동향",
    "monthly": "KB House View — 위험자산 선호도 상향",
}


def retrieve(period: str) -> dict:
    time.sleep(LATENCY)                      # 실제 벡터 검색/API 호출 대신
    return {"doc": period, "title": TITLES[period]}


def run(app, payload, label):
    t = time.perf_counter()
    try:
        out = app.invoke(payload)
    except Exception as e:
        sec = time.perf_counter() - t
        head = str(e).split("\n")[0]
        print(f"{label:<28} {sec:5.2f}초   실패 → {head}")
        return None
    sec = time.perf_counter() - t
    got = [e["doc"] for e in out["evidence"]]
    print(f"{label:<28} {sec:5.2f}초   수집 {len(got)}건  {got}")
    return out


# ================================================================ A. Chaining

class ChainState(TypedDict):
    evidence: list
    draft: str


def build_chaining():
    g = StateGraph(ChainState)

    # 한 노드가 끝나야 다음 노드가 시작된다
    for p in PERIODS:
        g.add_node(f"search_{p}",
                   lambda s, p=p: {"evidence": s["evidence"] + [retrieve(p)]})
    g.add_node("generate", lambda s: {"draft": f"{len(s['evidence'])}건 근거로 작성"})

    g.add_edge(START, "search_daily")
    g.add_edge("search_daily", "search_weekly")
    g.add_edge("search_weekly", "search_monthly")
    g.add_edge("search_monthly", "generate")
    g.add_edge("generate", END)
    return g.compile()


# ================================================================ B. Parallel

class ParallelState(TypedDict):
    evidence: Annotated[list, operator.add]   # ← reducer 가 핵심
    draft: str


def build_parallel():
    g = StateGraph(ParallelState)

    for p in PERIODS:
        g.add_node(f"search_{p}", lambda s, p=p: {"evidence": [retrieve(p)]})
    g.add_node("generate", lambda s: {"draft": f"{len(s['evidence'])}건 근거로 작성"})

    for p in PERIODS:                 # fan-out
        g.add_edge(START, f"search_{p}")
        g.add_edge(f"search_{p}", "generate")   # fan-in
    g.add_edge("generate", END)
    return g.compile()


# ================================================================ C. Parallel (버그)

class BuggyState(TypedDict):
    evidence: list                    # reducer 없음 — 마지막 쓰기가 이긴다
    draft: str


def build_parallel_buggy():
    g = StateGraph(BuggyState)
    for p in PERIODS:
        g.add_node(f"search_{p}", lambda s, p=p: {"evidence": [retrieve(p)]})
    g.add_node("generate", lambda s: {"draft": f"{len(s['evidence'])}건 근거로 작성"})
    for p in PERIODS:
        g.add_edge(START, f"search_{p}")
        g.add_edge(f"search_{p}", "generate")
    g.add_edge("generate", END)
    return g.compile()


# ================================================================ D. Orchestrator-Worker

class OrchState(TypedDict):
    change_type: str
    plan: list                        # 오케스트레이터가 만든 작업 목록
    evidence: Annotated[list, operator.add]
    draft: str


def plan_node(state: OrchState) -> dict:
    """무엇을 조회할지 런타임에 결정한다. 노드 수가 고정이 아니다."""
    if state["change_type"] in ("자산없음", "자산생김"):
        plan = ["monthly"]                        # 시황 원인 분석 불필요
    elif state["change_type"] == "급락":
        plan = ["daily", "weekly", "monthly"]     # 원인 규명이 중요
    else:
        plan = ["daily", "monthly"]
    return {"plan": plan}


def dispatch(state: OrchState):
    """Send 로 워커를 동적 생성. 개수가 State 값에 따라 달라진다."""
    return [Send("worker", {"period": p}) for p in state["plan"]]


def worker(payload: dict) -> dict:
    return {"evidence": [retrieve(payload["period"])]}


def build_orchestrator():
    g = StateGraph(OrchState)
    g.add_node("plan", plan_node)
    g.add_node("worker", worker)
    g.add_node("generate", lambda s: {"draft": f"{len(s['evidence'])}건 근거로 작성"})

    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", dispatch, ["worker"])
    g.add_edge("worker", "generate")
    g.add_edge("generate", END)
    return g.compile()


# ================================================================ 실행

if __name__ == "__main__":
    print(f"\n리포트 3건 수집 (검색 1건당 {LATENCY}초)\n" + "-" * 68)

    run(build_chaining(),       {"evidence": [], "draft": ""}, "A. Chaining (순차)")
    run(build_parallel(),       {"evidence": [], "draft": ""}, "B. Parallel (reducer O)")
    run(build_parallel_buggy(), {"evidence": [], "draft": ""}, "C. Parallel (reducer X)")

    print("\n오케스트레이터 — 상황에 따라 워커 수가 달라진다\n" + "-" * 68)
    for ct in ("급락", "유지", "자산없음"):
        run(build_orchestrator(),
            {"change_type": ct, "plan": [], "evidence": [], "draft": ""},
            f"D. Orchestrator [{ct}]")
