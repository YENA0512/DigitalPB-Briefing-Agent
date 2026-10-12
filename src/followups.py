"""
후속 질문 — 고객이 **자유 입력 없이** 대화하는 방법.

## 왜 자유 입력을 열지 않는가

채팅 UI 를 보면 입력창을 열고 싶어진다. 하지만 대고객 투자 서비스에서
고객 자유질문 → LLM 실시간 응답은 세 가지가 동시에 깨진다.

  1. **금소법** — 투자 문구는 사람 책임 하에 노출되어야 한다.
     고객이 무엇을 물을지 모르는데 답을 미리 검수할 수 없다
  2. **Runtime LLM** — 고객 수만큼 호출한다. 비용과 지연이 고객 수에 비례한다
  3. **기획 정합** — 이 프로젝트가 푸는 문제는 "문구 관리 병목"이지
     "고객 상담"이 아니다. 범위를 넓히면 둘 다 얕아진다

대신 **미리 정의된 질문 칩**만 누를 수 있게 한다. 칩의 답은 이미 만들어진
`card_spec` 안에 있다 — 새 LLM 호출이 없고, 전부 검수를 거친 내용이다.
실제 금융앱이 쓰는 패턴이기도 하다.

## 부수 효과 — 화면이 짧아진다

초판은 10개 버블을 한 번에 쏟아부어 모바일에서 너무 길었다.
기본 노출을 4개로 줄이고 나머지를 칩 뒤로 보내면
**길이 문제와 상호작용 문제가 같이 풀린다.**
"""

#  (칩 라벨, 응답 블록 id, 노출 조건)
#  블록 id 는 뷰어의 렌더 함수 키와 1:1 대응한다.
CHIPS = [
    ("어느 자산이 움직였어?", "holdings", lambda s: bool(s.get("contributions"))),
    ("내 자산 구성 괜찮아?",   "pbpoints", lambda s: bool(s.get("diagnosis"))),
    ("관련 뉴스 보여줘",       "news",     lambda s: bool(s.get("news"))),
    ("더 읽어볼 글 있어?",     "contents", lambda s: bool(s.get("contents"))),
    ("환율은 어때?",           "fx",       lambda s: (s.get("metrics", {})
                                                       .get("region_mix", {})
                                                       .get("해외", 0) >= 0.3),),
]

#  기본으로 펼칠 블록. 나머지는 칩을 눌러야 나온다.
DEFAULT_BLOCKS = ["market", "delta", "advice", "sources"]


def chips_for(spec: dict) -> list[dict]:
    """이 고객에게 띄울 칩 목록. 데이터가 없는 칩은 띄우지 않는다."""
    return [{"label": label, "block": block}
            for label, block, cond in CHIPS if cond(spec)]


if __name__ == "__main__":
    import json
    from pathlib import Path
    out = Path(__file__).resolve().parent.parent / "output" / "approved"
    for f in sorted(out.glob("*.json")):
        spec = json.loads(f.read_text(encoding="utf-8"))
        cs = chips_for(spec)
        print(f"{f.stem:<14} 칩 {len(cs)}개 — "
              + " / ".join(c["label"] for c in cs))
