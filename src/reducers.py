"""
State reducer — Feedback Loop 이 구조적으로 성립하게 만드는 부분.

## 왜 별도 파일인가

이 프로젝트의 가장 찾기 어려운 버그가 여기서 나왔다.

`reviews` 는 세 심사 노드가 병렬로 쓰는 칸이라 **reducer 가 반드시 있어야 한다**
(없으면 `InvalidUpdateError: Can receive only one value per step`).
그런데 reducer 를 `operator.add` 로 두면 **그 칸을 비울 수가 없다.**

    operator.add(["1회차 실패기록"], []) == ["1회차 실패기록"]

노드가 `reviews: []` 를 반환해도 누적분이 그대로 남는다. 그래서

  1회차: compliance 실패 → 재작성
  2회차: compliance 통과 · grounding 통과
  그런데 1회차 실패기록이 남아 있어서 `all(passed)` 가 여전히 False
  → 3회 돌고 폴백. **반려된 문구는 절대 되살아나지 못한다.**

## 설계 원칙

> 하나의 State 칸에 **"지금 판정에 쓸 값"** 과 **"남겨야 할 이력"** 을
> 같이 담으려 하면 실패한다. 둘은 수명이 다르므로 칸을 둘로 나눈다.

    reviews         Annotated[list, keep_latest_round]   현재 회차만. 판정에 쓴다
    review_history  Annotated[list, operator.add]        전 회차 누적. 감사 추적용

`keep_latest_round` 는 **회차 번호를 보고 스스로 오래된 것을 버린다.**
노드가 "비워야 한다"는 걸 기억할 필요가 없다 — 기억에 의존하는 규칙은
언젠가 빠뜨린다(실제로 빠뜨렸고, 빠뜨린 줄도 몰랐다).

금소법상 감사 추적이 필요하므로 이력을 버리지는 않는다. 분리할 뿐이다.
"""

import operator
from typing import Any


def keep_latest_round(old: list, new: list) -> list:
    """같은 회차의 심사 결과만 남긴다.

    각 심사 결과에는 `revision`(몇 회차 문구를 심사했는지)이 박혀 있다.
    `optimize` 가 revision 을 올리면, 다음 심사 결과는 더 큰 revision 을
    달고 들어온다. 그 순간 이전 회차 기록은 이 reducer 가 스스로 버린다.

    병렬 fan-in 도 그대로 처리한다 — 같은 회차의 세 축은 전부 살아남는다.
    """
    merged = list(old or []) + list(new or [])
    if not merged:
        return []
    latest = max(r.get("revision", 0) for r in merged)
    return [r for r in merged if r.get("revision", 0) == latest]


def merge_dict(old: dict, new: dict) -> dict:
    """fan-in 되는 dict 칸. 나중 것이 같은 키를 덮어쓴다."""
    return {**(old or {}), **(new or {})}


accumulate = operator.add   # 이력·로그처럼 계속 쌓여야 하는 칸


# ---------------------------------------------------------------- 자기검증

if __name__ == "__main__":
    print("keep_latest_round 동작 확인")

    r0 = [{"axis": "compliance", "passed": False, "revision": 0},
          {"axis": "grounding", "passed": True, "revision": 0}]
    print("  0회차 심사 2건         :", keep_latest_round([], r0))

    # optimize 가 revision 을 1 로 올리고, 심사 노드가 1회차로 다시 쓴다
    r1a = [{"axis": "compliance", "passed": True, "revision": 1}]
    step = keep_latest_round(r0, r1a)
    print("  1회차 compliance 도착  :", step, "← 0회차 기록이 사라졌다")

    r1b = [{"axis": "grounding", "passed": True, "revision": 1}]
    step = keep_latest_round(step, r1b)
    print("  1회차 grounding 도착   :", len(step), "건 ·",
          "전부 통과" if all(r["passed"] for r in step) else "반려")

    print("\n  operator.add 로는:", operator.add(r0, []), "← 비워지지 않는다")
