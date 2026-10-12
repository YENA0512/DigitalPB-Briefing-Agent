"""
Feedback Loop 회귀 테스트 — pytest 없이 python 으로 돈다.

5번이 이 프로젝트의 핵심 증빙이다. **reducer 를 operator.add 로 되돌리면
반려된 문구가 영원히 되살아나지 못한다**는 것을 코드로 보여준다.
발표에서 이 출력을 그대로 쓴다.
"""

import operator
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import briefing_agent as ba          # noqa: E402
import config                        # noqa: E402
import llm                           # noqa: E402
import reducers                      # noqa: E402

PASS, FAIL = "통과", "실패"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"\n  [{PASS if ok else FAIL}] {name}")
    if detail:
        for line in detail.splitlines():
            print(f"        {line}")


def run(portfolio: dict, thread: str, patch_generate=None, state_extra=None):
    """그래프를 1회 돌린다. generate 를 갈아끼워 특정 draft 를 강제할 수 있다."""
    orig = ba.generate
    if patch_generate:
        ba.generate = patch_generate
    try:
        from langgraph.types import Command
        app = ba.build_graph()
        cfg = {"configurable": {"thread_id": thread}, "recursion_limit": 60}
        st = ba.initial_state(portfolio)
        st.update(state_extra or {})
        out = app.invoke(st, config=cfg)
        #  HITL 도입 후 human_review 에서 멈춘다. 이 테스트들의 관심사가
        #  아니므로 자동 승인으로 통과시킨다 (검수 자체는 7번이 본다).
        guard = 0
        while "card_spec" not in out and guard < 5:
            guard += 1
            out = app.invoke(Command(resume={"action": "approve", "by": "테스트"}),
                             config=cfg)
        return out
    finally:
        ba.generate = orig


# ================================================================ 1
def test_banned_recovers():
    """금지어가 든 draft 를 주입하면 재작성으로 살아나야 한다.

    v1 에서는 1회차 실패기록이 reviews 에 남아 **절대 통과하지 못했다.**
    """
    def gen(state):
        return {"selected_card": "personal_briefing", "card_scores": {},
                "selection_reason": "테스트",
                #  금지어만 떼면 나머지가 규격(40~220자)을 만족하도록 길게 짠다.
                #  짧게 주입하면 Rule 재작성이 길이를 못 맞춰 폴백되고,
                #  "루프가 복구된다"가 아니라 "LLM 이 있어야 복구된다"가 된다.
                "draft": "5일 사이 839,000원이 줄었어요 [portfolio]. "
                         "KODEX 반도체가 624,000원 줄며 하락분의 대부분을 "
                         "만들었어요 [portfolio]. 보유 비중이 42%라 업종 조정의 "
                         "영향이 커졌어요 [portfolio]. 지금이 기회입니다 [portfolio].",
                "logs": ["카드 선택: personal_briefing (금지어 주입)"]}

    r = run(ba.MOCK_PORTFOLIOS["반도체편중"], "t1-banned", gen)
    s = r["card_spec"]
    first = next((h for h in s["review_history"]
                  if h["axis"] == "compliance" and h["revision"] == 0), None)
    ok = (first is not None and not first["passed"]          # 0회차에 잡혔고
          and not s["fallback_used"]                          # 폴백으로 안 빠졌고
          and s["review"]["compliance"]["passed"])            # 최종 통과
    check("금지어 주입 → 재작성 후 통과",
          ok,
          f"0회차 compliance: {'반려' if first and not first['passed'] else '?'}\n"
          f"최종 회차: {s['review_rounds']} · 폴백: {s['fallback_used']}\n"
          f"최종 문구: {s['advice'][:70]}")


# ================================================================ 2
def test_three_strikes_falls_back():
    """고칠 수 없는 반려는 3회 후 폴백. 41케이스 원본 문구로 나간다.

    심사 축 하나를 **항상 반려**로 갈아끼운다. 불량 draft 를 주입하는 방식은
    deterministic 하지 않다 — gpt-5.5 가 1회차에 고쳐버려서 폴백에 닿지 않았다.
    여기서 보려는 것은 문구 품질이 아니라 **라우팅**이다.
    """
    orig = ba.review_format

    def always_reject(state):
        return {"reviews": [ba._review("format", state["revision"], False,
                                       ["(테스트) 강제 반려"])],
                "review_history": [ba._review("format", state["revision"], False,
                                              ["(테스트) 강제 반려"])],
                "logs": ["형식: 강제 반려 (테스트)"]}

    ba.review_format = always_reject
    try:
        r = run(ba.MOCK_PORTFOLIOS["반도체편중"], "t2-strikes")
    finally:
        ba.review_format = orig

    s_ = r["card_spec"]
    original = ba.CASES[s_["case_id"]]["advice"]
    # 폴백 문구는 슬롯이 치환된 원본이다. 슬롯 앞부분으로 대조한다
    stem = original.split("{")[0][:14]
    ok = (s_["fallback_used"] and r["revision"] >= 3
          and stem and stem in s_["advice_plain"])
    check("3회 반려 → fallback_used=True · 41케이스 원본 문구로 복귀",
          ok,
          f"revision: {r['revision']} · fallback_used: {s_['fallback_used']}\n"
          f"원본:  {original[:52]}\n"
          f"폴백:  {s_['advice_plain'][:52]}\n"
          f"회차별 심사 기록: {sorted({h['revision'] for h in s_['review_history']})}")


# ================================================================ 3
def test_no_asset_exempt():
    """자산없음 케이스는 grounding 면제. 1회차에 통과해야 한다.

    일괄 적용하면 인용할 시황이 없는 문구가 3회 반려 후 폴백으로 빠진다.
    """
    r = run(ba.MOCK_PORTFOLIOS["신규고객"], "t3-exempt")
    s = r["card_spec"]
    g = s["review"]["grounding"]
    ok = g.get("exempt") and g["passed"] and not s["fallback_used"]
    check("자산없음 → grounding 면제 · 폴백 없음",
          ok,
          f"grounding: passed={g['passed']} exempt={g.get('exempt')}\n"
          f"회차: {s['review_rounds']} · 폴백: {s['fallback_used']}")


# ================================================================ 4
def test_round_isolation():
    """심사 결과에 revision 이 박히고, aggregate 가 현재 회차만 본다."""
    def gen(state):
        return {"selected_card": "personal_briefing", "card_scores": {},
                "selection_reason": "테스트",
                "draft": "5일 사이 839,000원이 줄었어요 [portfolio]. 무조건 좋아요 [portfolio].",
                "logs": ["카드 선택 (1회차만 실패하는 draft)"]}

    r = run(ba.MOCK_PORTFOLIOS["반도체편중"], "t4-rounds", gen)
    s = r["card_spec"]
    rounds = sorted({h["revision"] for h in s["review_history"]})
    final_rev = max(rounds)
    final_only = all(v["revision"] == final_rev for v in s["review"].values())
    ok = len(rounds) >= 2 and final_only
    check("회차 격리 — review 는 최신 회차만, history 는 전부 보존",
          ok,
          f"history 에 남은 회차: {rounds} (총 {len(s['review_history'])}건)\n"
          f"최종 review 가 전부 rev {final_rev} 인가: {final_only}")


# ================================================================ 5 ★
def test_reducer_regression():
    """★ reducer 를 operator.add 로 되돌리면 어떻게 되는가.

    WORKPLAN 이 요구한 "reviews 를 비우지 않으면 무한 반려된다"의 증빙이다.
    단, v1 의 처방(`reviews: []` 반환)으로는 **비워지지도 않는다**는 것까지 보인다.
    """
    r0 = [{"axis": "compliance", "passed": False, "revision": 0},
          {"axis": "grounding", "passed": True, "revision": 0},
          {"axis": "format", "passed": True, "revision": 0}]
    r1 = [{"axis": a, "passed": True, "revision": 1}
          for a in ("compliance", "grounding", "format")]

    # (가) v1 방식 — operator.add. 노드가 [] 를 반환해도 비워지지 않는다
    cleared = operator.add(r0, [])
    acc = operator.add(cleared, r1)
    v1_pass = all(x["passed"] for x in acc)

    # (나) 현재 방식 — 회차를 보고 스스로 버린다
    kept = reducers.keep_latest_round(r0, r1)
    v2_pass = all(x["passed"] for x in kept)

    ok = (not v1_pass) and v2_pass
    check("★ reducer 회귀 — operator.add 로는 1회차 실패가 영구히 남는다",
          ok,
          f"operator.add(r0, [])        → {len(cleared)}건. 비워지지 않는다\n"
          f"  이후 1회차 전부 통과해도  → all(passed)={v1_pass}  ← 영원히 반려\n"
          f"keep_latest_round(r0, r1)   → {len(kept)}건 (rev 1 만 남음)\n"
          f"  → all(passed)={v2_pass}  ← 재작성이 실제로 반영된다")


# ================================================================ 6
def test_all_mocks_complete():
    """MOCK_PORTFOLIOS 전 케이스가 에러 없이 완주한다."""
    bad, rows = [], []
    for name, pf in ba.MOCK_PORTFOLIOS.items():
        try:
            r = run(pf, f"t6-{name}")        # interrupt 재개 포함
            s = r["card_spec"]
            rows.append(f"{name:<12} {s['case_id']:<7} {r['change_type']:<6} "
                        f"{r['gap_type']:<6} {s['review_rounds']}회차 "
                        f"{'폴백' if s['fallback_used'] else '통과'} "
                        f"검수 {s.get('approval',{}).get('action','-')}")
        except Exception as exc:                 # noqa: BLE001
            bad.append(f"{name}: {type(exc).__name__}: {exc}")
    check(f"MOCK {len(ba.MOCK_PORTFOLIOS)}케이스 완주",
          not bad, "\n".join(rows + bad))


# ================================================================ 7 HITL
def test_hitl_three_ways():
    """검수 3갈래 — approve / edit / reject 가 각각 설계대로 동작한다."""
    from langgraph.types import Command

    def run_until_interrupt(thread):
        app = ba.build_graph()
        cfg = {"configurable": {"thread_id": thread}, "recursion_limit": 60}
        out = app.invoke(ba.initial_state(ba.MOCK_PORTFOLIOS["반도체편중"]), config=cfg)
        return app, cfg, out

    lines, ok = [], True

    # (가) interrupt 가 실제로 걸리는가 — card_spec 이 아직 없어야 한다
    app, cfg, out = run_until_interrupt("t7-approve")
    paused = "card_spec" not in out
    lines.append(f"interrupt 발생: {paused} (card_spec 없음)")
    ok &= paused

    # (나) approve
    out = app.invoke(Command(resume={"action": "approve", "by": "김검수"}), config=cfg)
    ap = out["card_spec"]["approval"]
    lines.append(f"approve → {ap['action']} · {ap['by']} · {ap['at'][:16]}")
    ok &= ap["action"] == "approve" and ap["by"] == "김검수"

    # (다) edit — 담당자가 고친 문구가 그대로 나가고 재심사하지 않는다
    app, cfg, out = run_until_interrupt("t7-edit")
    EDITED = "담당자가 직접 고친 문구예요 [portfolio]."
    out = app.invoke(Command(resume={"action": "edit", "by": "박검수",
                                     "advice": EDITED}), config=cfg)
    spec = out["card_spec"]
    edited_ok = spec["advice"] == EDITED and spec["approval"]["action"] == "edit"
    lines.append(f"edit → 문구 교체 {edited_ok} · 원본 보존 "
                 f"{bool(spec['approval'].get('original'))}")
    ok &= edited_ok

    # (라) reject — revision 이 오르고 재작성 후 다시 검수로 돌아온다
    app, cfg, out = run_until_interrupt("t7-reject")
    rev0 = app.get_state(cfg).values["revision"]
    out = app.invoke(Command(resume={"action": "reject", "by": "이검수",
                                     "reason": "수치 표현을 더 쉽게"}), config=cfg)
    st = app.get_state(cfg).values
    rev1 = st["revision"]
    reran = "card_spec" not in out            # 다시 검수에서 멈춰야 한다
    lines.append(f"reject → revision {rev0}→{rev1} · 재작성 후 재검수 대기 {reran}")
    ok &= rev1 > rev0 and reran

    # 반려 후 승인하면 최종 확정된다
    out = app.invoke(Command(resume={"action": "approve", "by": "이검수"}), config=cfg)
    done = "card_spec" in out
    lines.append(f"재검수 승인 → 확정 {done} · "
                 f"최종 회차 {out['card_spec']['review_rounds'] if done else '-'}")
    ok &= done

    check("HITL 3갈래 — approve / edit / reject", ok, "\n".join(lines))


if __name__ == "__main__":
    print("=" * 78)
    print(f"Feedback Loop 회귀 테스트  ·  USE_LLM={config.USE_LLM}"
          + (f" · {config.OPENAI_MODEL}" if config.USE_LLM else ""))
    print("=" * 78)

    for fn in (test_reducer_regression, test_round_isolation, test_banned_recovers,
               test_three_strikes_falls_back, test_no_asset_exempt,
               test_hitl_three_ways, test_all_mocks_complete):
        try:
            fn()
        except Exception as exc:                 # noqa: BLE001
            check(fn.__name__, False, f"예외: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 78)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"  {passed}/{len(results)} 통과   ·   {llm.summary()}")
    for name, ok, _ in results:
        print(f"    {'O' if ok else 'X'}  {name}")
    sys.exit(0 if passed == len(results) else 1)
