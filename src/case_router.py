"""
41케이스 판정 — 현업 엑셀의 압축 논리를 코드로 옮긴 것.

축을 전부 곱하면 288조합이지만 실제 케이스는 41개다.
줄어든 이유가 곧 판정 로직이다.

  · 자산이 없거나 상태가 바뀌면 나머지 축이 무의미      → CASE1~8
  · 오늘 이미 봤으면 변동을 말할 게 없음                 → CASE9
  · 급등·급락이면 개인 변동폭이 커서 시장전망을 쓰지 않음 → CASE23~26, 40, 41
  · 30일 초과 구간은 급등·급락에서 접속일을 세분화하지 않음
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA = json.loads((DATA_DIR / "cases_41.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in DATA["cases"]}
SERVICES = DATA["services"]

SURGE = 30.0      # 급등·급락 임계 (%)
FLAT = 0.5        # 변동없음 임계 (%)


# ---------------------------------------------------------------- 축 판정

def classify_asset(prev_has: bool, cur_has: bool) -> str:
    return f"{'O' if prev_has else 'X'}>{'O' if cur_has else 'X'}"


def classify_access(days: int) -> str:
    if days == 0:
        return "동일일자"
    return "1~30" if days <= 30 else "30+"


def classify_change(rate: float) -> str:
    """rate = (현재 - 직전접속시점) / 직전접속시점 × 100"""
    if abs(rate) < FLAT:
        return "변동없음"
    if rate >= SURGE:
        return "급등"
    if rate <= -SURGE:
        return "급락"
    return "증가" if rate > 0 else "감소"


def classify_market(region: str, outlook: str) -> str:
    """region 국내/해외 × outlook 좋음/보통/나쁨"""
    return f"{region}{outlook}"


# ---------------------------------------------------------------- 케이스 판정

def resolve_case(ctx: dict) -> str:
    """고객 컨텍스트 → CASE ID

    ctx: prev_has, cur_has, days, rate, region, outlook
    """
    asset = classify_asset(ctx["prev_has"], ctx["cur_has"])

    # 자산 미보유 — 시장전망만 사용
    if asset == "X>X":
        m = classify_market(ctx["region"], ctx["outlook"])
        return {
            "국내좋음": "CASE1", "국내보통": "CASE2", "국내나쁨": "CASE3",
            "해외좋음": "CASE4", "해외보통": "CASE5", "해외나쁨": "CASE6",
        }[m]

    # 상태 전환 — 다른 축 무시
    if asset == "X>O":
        return "CASE7"
    if asset == "O>X":
        return "CASE8"

    # O>O
    access = classify_access(ctx["days"])
    if access == "동일일자":
        return "CASE9"

    change = classify_change(ctx["rate"])
    days = ctx["days"]

    if access == "1~30":
        if change in ("급등", "급락"):
            detail = "1~10" if days <= 10 else "11~30"
            return {("급등", "1~10"): "CASE23", ("급등", "11~30"): "CASE24",
                    ("급락", "1~10"): "CASE25", ("급락", "11~30"): "CASE26"}[(change, detail)]
        if change == "변동없음":
            return "CASE22"
        m = classify_market(ctx["region"], ctx["outlook"])
        base = {"증가": 10, "감소": 16}[change]
        offset = ["국내좋음", "국내보통", "국내나쁨",
                  "해외좋음", "해외보통", "해외나쁨"].index(m)
        return f"CASE{base + offset}"

    # 30일 초과
    if change == "급등":
        return "CASE40"
    if change == "급락":
        return "CASE41"
    if change == "변동없음":
        return "CASE39"
    m = classify_market(ctx["region"], ctx["outlook"])
    base = {"증가": 27, "감소": 33}[change]
    offset = ["국내좋음", "국내보통", "국내나쁨",
              "해외좋음", "해외보통", "해외나쁨"].index(m)
    return f"CASE{base + offset}"


def render(case_id: str, slots: dict) -> dict:
    """케이스 문구 + 서비스 세트를 슬롯 치환해 반환 (폴백 경로)."""
    c = CASES[case_id]
    svc = SERVICES[c["service"]]
    text = c["advice"]
    for k, v in slots.items():
        text = text.replace("{" + k + "}", str(v))
    return {"case_id": case_id, "advice": text, **svc}


# ---------------------------------------------------------------- 커버리지 검증

def _coverage():
    """모든 입력 조합을 돌려 41케이스에 빠짐없이 도달하는지 확인."""
    seen, unreachable = set(), []
    for prev in (True, False):
        for cur in (True, False):
            for days in (0, 1, 5, 10, 11, 20, 30, 31, 60, 200):
                for rate in (-45.0, -12.0, -0.3, 0.0, 0.3, 12.0, 45.0):
                    for region in ("국내", "해외"):
                        for outlook in ("좋음", "보통", "나쁨"):
                            seen.add(resolve_case({
                                "prev_has": prev, "cur_has": cur, "days": days,
                                "rate": rate, "region": region, "outlook": outlook,
                            }))
    all_ids = set(CASES)
    unreachable = sorted(all_ids - seen, key=lambda s: int(s[4:]))
    ghost = sorted(seen - all_ids)
    return seen, unreachable, ghost


if __name__ == "__main__":
    seen, unreachable, ghost = _coverage()
    print(f"도달한 케이스 : {len(seen)} / {len(CASES)}")
    print(f"미도달        : {unreachable or '없음'}")
    print(f"정의 밖 반환  : {ghost or '없음'}")

    print("\n" + "=" * 68)
    samples = [
        ("5일 만에 접속 · 12% 감소 · 국내 나쁨",
         {"prev_has": True, "cur_has": True, "days": 5, "rate": -12.0,
          "region": "국내", "outlook": "나쁨"},
         {"days": 5, "diffAmt": "839,349", "curAmt": "91,754,057"}),
        ("45일 만에 접속 · 40% 급락",
         {"prev_has": True, "cur_has": True, "days": 45, "rate": -40.0,
          "region": "국내", "outlook": "보통"},
         {"days": 45, "diffAmt": "12,400,000", "curAmt": "18,600,000"}),
        ("신규 투자 시작",
         {"prev_has": False, "cur_has": True, "days": 3, "rate": 0.0,
          "region": "국내", "outlook": "좋음"},
         {}),
        ("미보유 · 해외 좋음",
         {"prev_has": False, "cur_has": False, "days": 12, "rate": 0.0,
          "region": "해외", "outlook": "좋음"},
         {}),
        ("오늘 재접속",
         {"prev_has": True, "cur_has": True, "days": 0, "rate": -1.0,
          "region": "국내", "outlook": "보통"},
         {}),
    ]
    for name, ctx, slots in samples:
        cid = resolve_case(ctx)
        out = render(cid, slots)
        print(f"\n{name}\n  → {cid} · {out['버튼명']}")
        print(f"  {out['advice']}")
