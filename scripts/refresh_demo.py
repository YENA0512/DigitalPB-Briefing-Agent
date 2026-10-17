"""
데모 데이터 날짜 맞추기 — 오늘 기준으로 리포트·승인본·뷰어를 다시 만든다.

## 왜 필요한가

목 리포트가 `daily-261012.md` 처럼 **날짜를 파일명과 frontmatter 에 박고**
있다. 하루 지나면 "오늘 시황"이라며 어제 날짜를 보여준다. 발표가 10/17 인데
10/12 짜리가 떠 있으면 그 자체로 신뢰를 깎는다.

시황 지표와 뉴스는 Tool 이 **실시간으로** 가져오므로 늘 오늘이다.
문제는 목데이터(리포트)와 그걸로 만든 승인본뿐이다.

예전에는 ①에서 **날짜만** 옮겼다. 그러면 "오늘 일간 리포트"가 며칠 전 숫자를
말하고, 같은 evidence 안의 시세 Tool 은 오늘 숫자를 가져와 근거끼리 어긋났다.
이제 ①은 `report_builder` 로 **본문 숫자까지 Yahoo 종가에서 다시 계산**한다.
시세 조회가 실패할 때만 예전 방식(날짜만 갱신)으로 떨어진다.

## 하는 일

    1. 일간: KB Think 1분 브리핑 실제 글 수집 → data/reports_live/ (kbthink_briefing.py)
       data/reports/*.md 를 실제 종가로 다시 생성 (report_builder.py)
       daily  : 최근 5거래일 (KB Think 수집 실패 시 대체용)
       weekly : 이번 주, 지난 주
       monthly: 이번 달 House View (시장 수치 문단만 자동)
    2. 승인본 5건 재생성 (LLM 사용)
    3. demo/viewer.html 다시 빌드

## 사용법

    python scripts/refresh_demo.py            # 전체
    python scripts/refresh_demo.py --dry-run  # 무엇이 바뀌는지만
    python scripts/refresh_demo.py --no-llm   # 리포트만 (빠름)

**발표 당일 아침에 한 번 돌리면 됩니다.**
"""

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEMO_CASES = ["반도체편중", "안정형과보수", "해외분산상승", "신규고객", "첫투자시작"]


def main() -> int:
    ap = argparse.ArgumentParser(description="데모 데이터를 오늘 날짜로 갱신")
    ap.add_argument("--dry-run", action="store_true", help="바뀔 내용만 출력")
    ap.add_argument("--no-llm", action="store_true", help="리포트만 갱신 (승인본·뷰어 건너뜀)")
    ap.add_argument("--date", default="", help="기준일 (기본 오늘). 예 2026-10-17")
    args = ap.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    print(f"기준일 {today.isoformat()}\n")

    print("① 리포트 — KB Think 1분 브리핑 수집 + 주간·월간은 실제 종가로 생성")
    import kbthink_briefing
    _, msg = kbthink_briefing.sync(dry_run=args.dry_run)
    print(f"   {msg}")
    try:
        import report_builder
        files = report_builder.build(today)
        if args.dry_run:
            for name in sorted(files):
                print(f"   {name}")
        else:
            for name in report_builder.write(files):
                print(f"   {name}")
    except Exception as exc:                     # noqa: BLE001 — 데모 준비는 멈추지 않는다
        #  예전에는 여기서 목 리포트의 **날짜만** 오늘로 옮겼다. 그러면 며칠 전
        #  내용이 오늘 시황처럼 보이고, KB Think 실제 글보다 "최신"이 되어 검색에서
        #  이겼다 (10/17 발표 PC 에서 실제로 그랬다). 이제는 건드리지 않는다.
        print(f"   ⚠ 시세 조회 실패({type(exc).__name__}: {str(exc)[:80]})")
        print("     목 리포트는 그대로 둡니다. 네트워크 확인 후 다시 실행하세요.")

    if args.dry_run:
        print("\n(dry-run — 아무것도 바꾸지 않았습니다)")
        return 0

    if args.no_llm:
        print("\n--no-llm — 승인본·뷰어는 건너뜁니다.")
        print("   전체 갱신: python scripts/refresh_demo.py")
        return 0

    print("\n② 승인본 재생성 (LLM 사용 · 2~3분)")
    import briefing_agent as ba
    app = ba.build_graph()
    for name in DEMO_CASES:
        if name not in ba.MOCK_PORTFOLIOS:
            continue
        r = ba.run_one(name, ba.MOCK_PORTFOLIOS[name], app, quiet=True)
        spec = r.get("card_spec")
        if not spec:
            print(f"   {name:<12} 실패")
            continue
        import case_router
        m = spec.get("metrics", {})
        spec["original_copy"] = case_router.render(spec["case_id"], {
            "days": spec.get("diagnosis", {}).get("days_since", 5),
            "diffAmt": f"{abs(m.get('delta', 0)):,}",
            "curAmt": f"{m.get('total', 0):,}"})["advice"]
        import json
        out = ROOT / "output" / "approved" / f"{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        print(f"   {name:<12} {spec['case_id']} · 출처 {len(spec.get('sources', []))} · "
              f"뉴스 {len(spec.get('news', []))} · "
              f"{'폴백' if spec.get('fallback_used') else '통과'}")

    print("\n③ 뷰어 재빌드")
    subprocess.run([sys.executable, str(ROOT / "demo" / "build_viewer.py")],
                   check=False)

    print(f"\n완료 — 발표 당일 아침에 한 번 더 돌리세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
