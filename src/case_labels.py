"""
케이스 라벨 — `CASE19` 가 무슨 상황인지 사람이 읽을 수 있게.

## 왜 필요한가

41케이스는 내부 식별자다. 발표 화면이나 검수 목록에 `CASE19` 만 떠 있으면
**무슨 고객인지 아무도 모른다.** 조건(`cond`)을 그대로 문장으로 편다.

    CASE19  →  5일만에 방문 · 6% 감소 · 국내 나쁨
    CASE3   →  자산 미보유 · 국내 나쁨
    CASE25  →  10일 이내 방문 · 30% 이상 급락

`cases_41.json` 의 `cond` 가 단일 출처다. 별도 표를 만들면 조건이 바뀔 때
라벨만 남아 거짓말이 된다.
"""

import case_router

ASSET = {
    "X>X": "자산 미보유",
    "X>O": "첫 투자 시작",
    "O>X": "자산 전량 처분",
    "O>O": None,                      # 일반 보유 — 다른 축으로 설명한다
}

ACCESS = {
    "동일일자": "오늘 재방문",
    "1~30": "최근 방문",
    "30+": "오랜만에 방문",
}

ACCESS_DETAIL = {"1~10": "10일 이내 방문", "11~30": "11~30일 만에 방문"}

CHANGE = {
    "증가": "자산 증가",
    "감소": "자산 감소",
    "변동없음": "변동 거의 없음",
    "급등": "30% 이상 급등",
    "급락": "30% 이상 급락",
}

MARKET = {
    "국내좋음": "국내 전망 좋음", "국내보통": "국내 전망 보통", "국내나쁨": "국내 전망 나쁨",
    "해외좋음": "미국 전망 좋음", "해외보통": "미국 전망 보통", "해외나쁨": "미국 전망 나쁨",
}


def label(case_id: str) -> str:
    """조건을 사람이 읽는 한 줄로."""
    c = case_router.CASES.get(case_id)
    if not c:
        return case_id
    cond = c.get("cond") or {}
    parts = []

    a = ASSET.get(cond.get("asset"))
    if a:
        parts.append(a)

    detail = ACCESS_DETAIL.get(cond.get("access_detail"))
    if detail:
        parts.append(detail)
    elif cond.get("access"):
        parts.append(ACCESS[cond["access"]])

    if cond.get("change"):
        parts.append(CHANGE[cond["change"]])
    if cond.get("market"):
        parts.append(MARKET[cond["market"]])

    return " · ".join(parts) or "기타"


def short(case_id: str, width: int = 34) -> str:
    """목록용 — `CASE19 · 최근 방문 · 자산 감소 · 국내 전망 나쁨`"""
    t = label(case_id)
    return f"{case_id} · {t if len(t) <= width else t[:width - 1] + '…'}"


def all_labels() -> dict[str, str]:
    return {cid: label(cid) for cid in
            sorted(case_router.CASES, key=lambda c: int(c[4:]))}


if __name__ == "__main__":
    print("41케이스 — 무슨 상황인가\n")
    for cid, t in all_labels().items():
        print(f"  {cid:<7} {t}")
