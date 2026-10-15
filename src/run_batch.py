"""
배치 러너 — 41케이스를 돌려 검수 대기열에 쌓는다.

## 운영 흐름

    [18:00 장 마감 후]
      run_batch.py            41건 실행 → human_review 에서 멈춤
                              → output/pending/*.json 에 적재
    [담당자]
      run_batch.py --review   대기건을 하나씩 승인 / 수정 / 반려
                              → 승인분만 output/approved/ 로 이동
    [다음날 고객 진입]
      승인된 JSON 을 슬롯 치환해 노출. **LLM 호출 없음**

검수 단위는 고객이 아니라 **케이스**다. 41건을 검수하면 전 고객에게 나간다.
MAU 13만 · 케이스당 평균 3천 명이므로, 검수 1건이 3천 명의 화면을 바꾼다.

## 사용법

    python src/run_batch.py                  # 41건 실행 → pending 적재
    python src/run_batch.py --auto-approve   # 검수 건너뛰고 approved 로 (데모용)
    python src/run_batch.py --review         # 대기건 대화형 검수
    python src/run_batch.py --cases CASE19,CASE25
    python src/run_batch.py --limit 5        # 앞 5건만 (리허설용)
"""

import argparse
import json
import sys
import time
from pathlib import Path

from langgraph.types import Command

import briefing_agent as ba
import case_labels
import case_router
import config
import llm
import tracing
import audit_db

ROOT = Path(__file__).resolve().parent.parent
PENDING = ROOT / "output" / "pending"
APPROVED = ROOT / "output" / "approved"


# ──────────────────────────────────────────────────────── 케이스 → 입력

def portfolio_for(case_id: str) -> dict:
    """케이스 조건을 만족하는 목 포트폴리오를 만든다.

    `cases_41.json` 의 `cond` 를 거꾸로 읽어 입력을 합성한다.
    **고객 실데이터를 쓰지 않고** 41건 전체를 돌리기 위한 장치다.
    역산이므로 `case_router.resolve_case()` 가 같은 케이스를 돌려주는지
    실행 중에 대조한다(불일치는 로그로 남긴다).
    """
    cond = case_router.CASES[case_id]["cond"]
    asset = cond.get("asset") or "O>O"
    change = cond.get("change")
    access = cond.get("access")
    market = cond.get("market") or "국내보통"

    if asset == "X>X":
        return {"total": 0, "prev_total": 0, "days_since": 12,
                "prev_holdings": 0, "holdings": []}
    if asset == "O>X":
        return {"total": 0, "prev_total": 5_000_000, "days_since": 9,
                "prev_holdings": 2, "holdings": []}
    if asset == "X>O":
        return {"total": 3_000_000, "prev_total": 0, "days_since": 2,
                "prev_holdings": 0,
                "holdings": [{"name": "KB밸런스포트폴리오", "weight": 1.0,
                              "delta": 30_000, "region": "국내"}]}

    # O>O — 변동률을 조건에 맞춰 역산한다
    rate = {"급등": 42.0, "급락": -42.0, "증가": 6.0,
            "감소": -6.0, "변동없음": 0.1}.get(change, 1.5)
    days = {"동일일자": 0, "1~30": 7, "30+": 45}.get(access, 7)
    if cond.get("access_detail") == "11~30":
        days = 18
    prev = 90_000_000
    delta = int(prev * rate / 100)
    해외 = market.startswith("해외")

    holdings = ([{"name": "KB미국대표성장ETF", "weight": 0.40,
                  "delta": int(delta * 0.6), "region": "해외"},
                 {"name": "KB글로벌AI펀드", "weight": 0.35,
                  "delta": int(delta * 0.3), "region": "해외"},
                 {"name": "KODEX 200", "weight": 0.25,
                  "delta": delta - int(delta * 0.6) - int(delta * 0.3),
                  "region": "국내"}]
                if 해외 else
                [{"name": "KODEX 반도체", "weight": 0.45,
                  "delta": int(delta * 0.7), "region": "국내"},
                 {"name": "KODEX 200", "weight": 0.35,
                  "delta": int(delta * 0.2), "region": "국내"},
                 {"name": "美 단기국채ETF", "weight": 0.20,
                  "delta": delta - int(delta * 0.7) - int(delta * 0.2),
                  "region": "해외"}])

    return {"total": prev + delta, "prev_total": prev, "days_since": days,
            "prev_holdings": 3, "holdings": holdings}


# ──────────────────────────────────────────────────────── 실행

def run_case(app, case_id: str, auto_approve: bool) -> tuple[str, dict]:
    """1건 실행. ('approved'|'pending'|'error', payload) 를 반환한다."""
    cfg = {"configurable": {"thread_id": case_id}, "recursion_limit": 60,
           "callbacks": tracing.callbacks()}

    #  실행 1건 = trace 1개. 먼저 span 을 열어야 LangChain 콜백이 만드는
    #  LLM span 들이 그 아래로 들어가고, 점수도 같은 trace 에 붙는다.
    with tracing.trace_run(case_id, case_labels.label(case_id)) as tr:
        try:
            out = app.invoke(ba.initial_state_for(case_id), config=cfg)
        except Exception as exc:                 # noqa: BLE001
            return "error", {"case_id": case_id,
                             "error": f"{type(exc).__name__}: {exc}"}

        if "card_spec" not in out and auto_approve:
            out = app.invoke(Command(resume={"action": "approve",
                                             "by": "배치 자동승인"}), config=cfg)

        if "card_spec" in out:
            spec = out["card_spec"]
            tr.score_spec(spec)
            if tr.url:
                spec["trace_url"] = tr.url
            return "approved", spec

    if auto_approve:
        return "error", {"case_id": case_id, "error": "자동승인 후에도 미완료"}

    snap = app.get_state(cfg)
    payload = snap.interrupts[0].value if snap.interrupts else {"case_id": case_id}
    return "pending", payload


def save(path: Path, name: str, data: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def refresh_daily_reports() -> str:
    """배치 시작 전에 KB Think 1분 브리핑을 받아 일간 근거를 오늘 것으로 바꾼다.

    실패해도 배치는 돈다 — 기존 live 파일이나 목 리포트로 떨어진다.
    """
    import kbthink_briefing
    import retriever
    _, msg = kbthink_briefing.sync()
    retriever.reload()
    return f"{msg} → 일간 근거: {retriever.daily_source()}"


def batch(case_ids: list[str], auto_approve: bool) -> dict:
    print(f"리포트 : {refresh_daily_reports()}")
    app = ba.get_app()
    llm.reset_stats()
    t0 = time.perf_counter()
    stat = {"approved": 0, "pending": 0, "error": 0,
            "fallback": 0, "rounds": [], "errors": []}

    for i, cid in enumerate(case_ids, 1):
        t = time.perf_counter()
        kind, payload = run_case(app, cid, auto_approve)
        stat[kind] += 1
        if kind == "approved":
            if payload.get("trace_url"):
                stat["traced"] = stat.get("traced", 0) + 1
            #  감사 로그 — 누가 언제 무엇을 승인했는지. 파일은 재생성하면 사라진다.
            if audit_db.record(payload):
                stat["logged"] = stat.get("logged", 0) + 1
            save(APPROVED, cid, payload)
            stat["rounds"].append(payload.get("review_rounds", 1))
            stat["fallback"] += bool(payload.get("fallback_used"))
            mark = "폴백" if payload.get("fallback_used") else "통과"
            extra = f"{payload.get('review_rounds',1)}회차 {mark}"
        elif kind == "pending":
            save(PENDING, cid, payload)
            extra = "검수 대기"
        else:
            stat["errors"].append(payload)
            extra = payload["error"][:50]
        print(f"  [{i:2d}/{len(case_ids)}] {cid:<7} {time.perf_counter()-t:5.1f}초  "
              f"{extra:<16} {case_labels.label(cid)}")

    stat["elapsed"] = time.perf_counter() - t0
    tracing.flush()
    return stat


def report(stat: dict, total: int) -> None:
    print(f"\n{'=' * 66}")
    print(f"  처리 {total}건 · {stat['elapsed']:.1f}초 "
          f"(건당 {stat['elapsed']/max(total,1):.1f}초)")
    print(f"  승인 {stat['approved']} · 검수대기 {stat['pending']} · 오류 {stat['error']}")
    if stat["rounds"]:
        avg = sum(stat["rounds"]) / len(stat["rounds"])
        print(f"  평균 심사 회차 {avg:.2f} · 폴백 {stat['fallback']}건 "
              f"({stat['fallback']/len(stat['rounds'])*100:.0f}%)")
    print(f"  {llm.summary()}")
    if stat.get("logged"):
        print(f"  감사 로그 {stat['logged']}건 → output/audit.db "
              f"(./run_local.sh audit 로 조회)")
    if stat.get("traced"):
        print(f"  Langfuse {stat['traced']}건 기록 — compliance_pass · grounding_pass ·")
        print(f"           format_pass · revisions · fallback · llm_calls · sources")
    if llm.stats["calls"]:
        print(f"  건당 LLM {llm.stats['calls']/max(total,1):.1f}회 "
              f"— Runtime 에는 LLM 호출이 없다")
    for e in stat["errors"][:5]:
        print(f"  ⚠ {e['case_id']}: {e['error'][:70]}")


# ──────────────────────────────────────────────────────── 대화형 검수

def review_pending() -> None:
    files = sorted(PENDING.glob("*.json"))
    if not files:
        print(f"검수 대기건이 없습니다: {PENDING}")
        return

    app = ba.get_app()
    print(f"검수 대기 {len(files)}건\n")
    for f in files:
        p = json.loads(f.read_text(encoding="utf-8"))
        cid = p.get("case_id", f.stem)
        print("=" * 66)
        print(f"{cid}  ·  {p.get('case_label', '')}")
        print(f"{'':11}  진단 {p.get('change_type','')} / {p.get('gap_type','')}")
        print("=" * 66)
        print(f"  {p.get('advice_display', p.get('advice',''))}")
        print(f"\n  카드 {p.get('selected_card')} "
              f"(제친 카드 {', '.join(p.get('selected_over', []))})")
        print(f"  선택 이유 {p.get('selection_reason','')}")
        print(f"  심사 {p.get('review', {})}")
        print(f"  근거 {[e['doc'] for e in p.get('evidence', [])]}")
        print("\n  [a] 승인   [e] 수정 후 승인   [r] 반려   [s] 건너뛰기   [q] 종료")
        ans = input("  > ").strip().lower()
        if ans == "q":
            break
        if ans == "s":
            continue

        by = input("  검수자 이름: ").strip() or "(미상)"
        if ans == "e":
            print(f"  현재: {p.get('advice','')}")
            new = input("  새 문구: ").strip()
            cmd = {"action": "edit", "by": by, "advice": new or p.get("advice", "")}
        elif ans == "r":
            cmd = {"action": "reject", "by": by,
                   "reason": input("  반려 사유: ").strip() or "(사유 없음)"}
        else:
            cmd = {"action": "approve", "by": by}

        cfg = {"configurable": {"thread_id": cid}, "recursion_limit": 60}
        try:
            out = app.invoke(Command(resume=cmd), config=cfg)
        except Exception as exc:                 # noqa: BLE001
            print(f"  ⚠ 재개 실패: {type(exc).__name__} — 배치를 다시 돌려야 합니다")
            print("     (체크포인터가 InMemorySaver 라 프로세스가 바뀌면 상태가 사라집니다)")
            continue
        if "card_spec" in out:
            audit_db.record(out["card_spec"])
            save(APPROVED, cid, out["card_spec"])
            f.unlink()
            print(f"  → 승인 · output/approved/{cid}.json")
        else:
            save(PENDING, cid, app.get_state(cfg).interrupts[0].value)
            print("  → 재작성 후 다시 검수 대기")


# ──────────────────────────────────────────────────────── CLI

def main() -> int:
    ap = argparse.ArgumentParser(description="41케이스 배치 실행 + 검수")
    ap.add_argument("--auto-approve", action="store_true",
                    help="검수를 건너뛰고 바로 approved 로 (데모·테스트용)")
    ap.add_argument("--review", action="store_true", help="대기건 대화형 검수")
    ap.add_argument("--cases", default="", help="쉼표로 구분한 CASE ID")
    ap.add_argument("--limit", type=int, default=0, help="앞 N건만")
    args = ap.parse_args()

    if args.review:
        review_pending()
        return 0

    ids = ([c.strip() for c in args.cases.split(",") if c.strip()]
           or sorted(case_router.CASES, key=lambda c: int(c[4:])))
    if args.limit:
        ids = ids[: args.limit]

    print(f"배치 실행 — {len(ids)}건 · USE_LLM={config.USE_LLM}"
          + (f" · {config.OPENAI_MODEL}" if config.USE_LLM else "")
          + f" · 검수 {'자동승인' if args.auto_approve else '대기열 적재'}")
    import mcp_client
    mcp_client.connect()
    print(f"Tool 경로: {mcp_client.mode()}")
    print(f"Langfuse : {tracing.state()}\n")

    stat = batch(ids, args.auto_approve)
    report(stat, len(ids))
    print(f"\n  → {'output/approved' if args.auto_approve else 'output/pending'}/")
    if not args.auto_approve and stat["pending"]:
        print("  검수: python src/run_batch.py --review")
    return 1 if stat["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
