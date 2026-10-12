"""
출처 렌더링 — 내부 태그를 **대고객 표기**로 바꾼다.

## 왜 분리했나

심사(grounding)는 `[일간-261012]` 같은 **기계가 대조할 수 있는 라벨**이 필요하고,
고객은 그 라벨을 읽을 이유가 없다. 둘은 목적이 다르므로 같은 문자열을 쓰지 않는다.

    내부(검수·감사)   하루 사이 83만원이 줄었어요 [portfolio].
                      반도체에 차익 실현이 번졌어요 [일간-261012].

    대고객            하루 사이 83만원이 줄었어요.
                      반도체에 차익 실현이 번졌어요. ①
                      ① 반도체 투심 위축에 코스피 급락 · KB Think → 클릭 시 이동

## 규칙

- `[portfolio]` 는 **고객 노출에서 완전히 지운다.** 자체 계산값이라
  출처를 밝힐 대상이 아니다 (밝혀도 고객에게 의미가 없다)
- 외부 출처는 **번호 + 제목 + 발행처 + URL** 로 펼친다. 코드는 보여주지 않는다
- 번호는 문구에 등장한 순서다. 같은 출처가 두 번 나오면 같은 번호를 쓴다
- URL 이 없는 출처는 칩을 만들되 링크를 비운다 (뷰어가 클릭 불가로 렌더)
"""

import re

MARKERS = "①②③④⑤⑥⑦⑧⑨"

#  evidence 의 doc 접두어 → 고객에게 보일 출처 종류
KIND_LABEL = {
    "일간-": ("리포트", "KB Think"),
    "주간-": ("리포트", "KB Think"),
    "월간-": ("하우스뷰", "KB Think"),
    "시장-": ("시장지표", "실시간 시세"),
    "뉴스-": ("뉴스", None),          # 발행처는 기사에 들어 있다
}

INTERNAL_ONLY = {"portfolio"}        # 고객에게 보이지 않는 태그

#  시장지표는 **화면 상단 시황 보드에 숫자가 이미 보인다.**
#  같은 값을 출처 칩으로 또 보여주면 중복이고, 누를 곳도 마땅치 않다.
#  단 grounding 심사는 그대로 대조하므로 내부 표기(`advice`)에는 남는다.
HIDDEN_PREFIXES = ("시장-",)


def classify(doc: str) -> tuple[str, str | None]:
    for prefix, label in KIND_LABEL.items():
        if doc.startswith(prefix):
            return label
    return ("참고자료", None)


def render(draft: str, evidence: list[dict]) -> dict:
    """내부 태그가 박힌 문구 → 대고객 문구 + 출처 목록.

    반환:
        plain    태그를 전부 지운 순수 문장 (TTS·요약용)
        display  외부 출처 자리에 ①②③ 가 박힌 문장
        sources  [{marker, title, summary, publisher, kind, url, doc}]
    """
    by_doc = {e["doc"]: e for e in evidence}
    order: list[str] = []

    def repl(match: re.Match) -> str:
        tag = match.group(1).strip()
        if tag in INTERNAL_ONLY:
            return ""                                  # 고객 노출에서 제거
        if tag.startswith(HIDDEN_PREFIXES):
            return ""                                  # 시황 보드가 이미 보여준다
        if tag not in by_doc:
            return ""                                  # 심사에서 이미 걸렀어야 한다
        if tag not in order:
            order.append(tag)
        idx = order.index(tag)
        return f" {MARKERS[idx]}" if idx < len(MARKERS) else f" [{idx + 1}]"

    display = re.sub(r"\s*\[([^\[\]]+)\]", repl, draft)
    display = re.sub(r"\s+([.!?])", r"\1", display)     # " ." → "."
    display = re.sub(r"\s{2,}", " ", display).strip()

    sources = []
    for i, doc in enumerate(order):
        e = by_doc[doc]
        kind, default_pub = classify(doc)
        sources.append({
            "marker": MARKERS[i] if i < len(MARKERS) else f"[{i + 1}]",
            "doc": doc,
            "kind": kind,
            "title": e.get("title", doc),
            "summary": e.get("summary") or e.get("text", "")[:110],
            "publisher": e.get("publisher") or default_pub or "KB Think",
            "url": e.get("url", ""),
            "date": e.get("date", ""),
        })

    plain = re.sub(r"\s*\[[^\[\]]+\]", "", draft)
    plain = re.sub(r"\s+([.!?])", r"\1", plain)
    plain = re.sub(r"\s{2,}", " ", plain).strip()

    return {"plain": plain, "display": display, "sources": sources}


if __name__ == "__main__":
    ev = [
        {"doc": "일간-261012", "title": "반도체 투심 위축에 코스피 급락",
         "summary": "반도체 업종 차익 실현으로 코스피·코스닥이 동반 하락한 날의 시황.",
         "url": "https://kbthink.com/investment/today-pick/2610/261012-1.html",
         "date": "2026-10-12"},
        {"doc": "뉴스-1", "title": "[증시-마감] 코스피, 두 달 만에 6,400선 밑으로",
         "text": "연합인포맥스 2026-10-12 기사", "publisher": "연합인포맥스",
         "url": "https://news.google.com/rss/articles/CBMicEFV", "date": "2026-10-12"},
    ]
    draft = ("하루 사이 839,000원이 줄었어요 [portfolio]. "
             "KODEX 반도체가 624,000원 줄며 변동을 키웠어요 [portfolio]. "
             "이날 반도체 업종에 차익 실현이 번졌어요 [일간-261012]. "
             "코스피는 두 달 만에 6,400선을 밑돌았어요 [뉴스-1].")
    ev.append({"doc": "시장-^KS11", "title": "코스피 6,401 (-3.39%)",
               "summary": "전일 대비 -3.39%", "url": "", "date": "2026-10-12"})
    draft += " 코스피는 3.39% 내렸어요 [시장-^KS11]."
    out = render(draft, ev)
    print("내부 문구:\n ", draft, "\n")
    print("대고객 문구:\n ", out["display"], "\n")
    print("출처:")
    for s in out["sources"]:
        print(f"  {s['marker']} [{s['kind']}] {s['title']}")
        print(f"     {s['publisher']} · {s['date']}")
        print(f"     {s['summary'][:72]}")
        print(f"     → {s['url'][:70]}")
