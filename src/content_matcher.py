"""
match_contents 노드 — KB Think 콘텐츠 매칭

루프 밖에 둔다. 심사를 통과한 확정 문구 기준으로 매칭해야
재작성마다 API를 호출하지 않고 매칭 정확도도 유지된다.

태그 체계는 새로 만들지 않는다. 현업 해시태그 테이블을 그대로 쓰고,
Agent 는 투자 상황을 그 태그 어휘로 '번역'하는 역할만 한다.
"""

import json
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA = json.loads((DATA_DIR / "kbthink_contents.json").read_text(encoding="utf-8"))
CONTENTS = DATA["contents"]
SITUATION = DATA["situation_to_tag"]
OVERLAY = DATA["overlay_rules"]

#  "이어서 읽어볼 콘텐츠"에서 뺄 것.
#  1분 브리핑·시황은 **당일 시장동향**이라 브리핑 본문과 근거에서 이미 다룬다.
#  여기 또 넣으면 같은 내용이 두 번 나온다. 그 역할은 retriever(리포트)와
#  news_tool(기사)이 한다.
_EX = DATA["_meta"].get("exclude_from_followup", {})
EXCLUDE_SECTIONS = set(_EX.get("section", []))
EXCLUDE_FORMATS = set(_EX.get("format", []))


def is_followup_candidate(item: dict) -> bool:
    return (item.get("section") not in EXCLUDE_SECTIONS
            and item.get("format") not in EXCLUDE_FORMATS)

TODAY = date.today()      # 하드코딩하면 발표일에 신선도 가점이 전부 0 이 된다

#  진단과 **반대 방향**인 콘텐츠를 걸러낸다.
#  태그만 보면 과편중·과보수 콘텐츠가 둘 다 #자산배분·#투자성향 을 달고 있어
#  서로의 고객에게 추천된다 (실제로 과편중 고객에게 과보수 콘텐츠가 붙었다).
CONFLICT = {
    "과편중": ["위험자산 비중이 너무 낮", "과보수", "단기자금", "현금성"],
    "과보수": ["한 종목에 몰", "집중", "편중"],
}
W_CONFLICT = -4.0    # 상충 콘텐츠 감점. 상황 태그 1건 이상을 상쇄한다

W_SITUATION = 3.0    # 상황 태그 일치
W_OVERLAY = 2.0      # 포트폴리오 파생 태그 일치
W_VIEWED = 1.5       # 최근 열람 관심사 일치
W_FRESH = 1.0        # 최근 7일 이내 발행
W_RECENT = 0.6       # 최근 30일 이내 (오늘 국면을 다룬 글이 먼저 와야 한다)
LEVEL_FIT = 0.8      # 투자 레벨과 난이도 일치


def derive_tags(change_type: str, gap_type: str, portfolio: dict) -> tuple[list, list]:
    """진단 결과를 현업 태그 어휘로 번역한다."""
    situation = SITUATION.get(f"{change_type}|{gap_type}", [])

    overlay, holdings = [], portfolio.get("holdings", [])
    foreign = sum(h["weight"] for h in holdings if h.get("region") == "해외")
    if foreign >= 0.30:
        overlay += OVERLAY["해외비중_30퍼센트_이상"]
    if any("반도체" in h["name"] or "AI" in h["name"] for h in holdings):
        overlay += OVERLAY["반도체_보유"]
    if any("국채" in h["name"] or "채권" in h["name"] for h in holdings):
        overlay += OVERLAY["채권_보유"]
    if any("연금" in h["name"] for h in holdings):
        overlay += OVERLAY["연금계좌_보유"]

    return situation, list(dict.fromkeys(overlay))


def normalize_tags(tags: list) -> list:
    """'#' 유무를 통일한다.

    briefing_agent 는 ["ETF"], 콘텐츠 태그는 ["#ETF"] 였다. 집합 교집합이
    항상 비어 W_VIEWED 가스코어에 반영되지 않았다 — 조용히 0 이 되는 유형의 버그.
    """
    out = []
    for t in tags or []:
        t = str(t).strip()
        if t and not t.startswith("#"):
            t = "#" + t
        if t:
            out.append(t)
    return out


def conflict_penalty(item: dict, gap_type: str) -> float:
    """진단과 반대 방향인 제목이면 감점."""
    words = CONFLICT.get(gap_type, [])
    return W_CONFLICT if any(w in item["title"] for w in words) else 0.0


def score(item: dict, situation: list, overlay: list, viewed: list, level: str,
          gap_type: str = "") -> tuple:
    tags = set(item["tags"])
    s = 0.0
    hit_sit = tags & set(situation)
    hit_ovl = tags & set(overlay)
    hit_view = tags & set(viewed)

    s += len(hit_sit) * W_SITUATION
    s += len(hit_ovl) * W_OVERLAY
    s += len(hit_view) * W_VIEWED
    age = (TODAY - date.fromisoformat(item["published"])).days
    if age <= 7:
        s += W_FRESH
    elif age <= 30:
        s += W_RECENT
    if item["level"] == level:
        s += LEVEL_FIT
    pen = conflict_penalty(item, gap_type)
    s += pen

    why = []
    if hit_sit:  why.append(f"상황 {'·'.join(sorted(hit_sit))}")
    if hit_ovl:  why.append(f"보유 {'·'.join(sorted(hit_ovl))}")
    if hit_view: why.append(f"열람 {'·'.join(sorted(hit_view))}")
    if pen:      why.append("진단 상충 감점")
    return s, " / ".join(why)


def match_contents(state: dict, k: int = 3) -> dict:
    """LangGraph 노드. aggregate 통과 분기에서 호출한다."""
    situation, overlay = derive_tags(
        state["change_type"], state["gap_type"], state["portfolio"])
    viewed = normalize_tags(state.get("recent_views", []))
    level = state.get("profile", {}).get("level", "입문")

    ranked = []
    for c in CONTENTS:
        if not is_followup_candidate(c):
            continue
        s, why = score(c, situation, overlay, viewed, level,
                       state.get("gap_type", ""))
        if s > 0:
            ranked.append({**c, "_score": round(s, 1), "_why": why})
    ranked.sort(key=lambda x: (-x["_score"], x["published"]))   # 동점이면 오래된 것 먼저

    top = ranked[:k]
    return {"contents": top,
            "logs": [f"콘텐츠 {len(top)}건 (후보 {len(ranked)}건 · "
                     f"당일시황 {len(CONTENTS) - sum(1 for c in CONTENTS if is_followup_candidate(c))}건 제외)"
                     f" · 상황태그 {situation}"]}


# ---------------------------------------------------------------- 테스트

CASES = {
    "반도체 편중 + 급락": {
        "change_type": "급락", "gap_type": "과편중",
        "profile": {"level": "중급"},
        "recent_views": ["#ETF", "#반도체"],
        "portfolio": {"holdings": [
            {"name": "KODEX 반도체", "weight": 0.42, "region": "국내"},
            {"name": "KB글로벌AI펀드", "weight": 0.31, "region": "해외"},
            {"name": "美 단기국채ETF", "weight": 0.27, "region": "해외"},
        ]},
    },
    "안정형 + 유지": {
        "change_type": "유지", "gap_type": "과보수",
        "profile": {"level": "입문"},
        "recent_views": ["#절세"],
        "portfolio": {"holdings": [
            {"name": "KB연금펀드", "weight": 0.55, "region": "국내"},
            {"name": "국내 채권형펀드", "weight": 0.45, "region": "국내"},
        ]},
    },
    "신규 고객 (자산없음)": {
        "change_type": "자산없음", "gap_type": "정합",
        "profile": {"level": "입문"},
        "recent_views": [],
        "portfolio": {"holdings": []},
    },
}

if __name__ == "__main__":
    for name, st in CASES.items():
        out = match_contents(st)
        print(f"\n{'=' * 72}\n{name}\n{'=' * 72}")
        print(out["logs"][0])
        for i, c in enumerate(out["contents"], 1):
            print(f"\n  {i}. [{c['_score']}] {c['title']}")
            print(f"     {c['section']} · {c['level']} · {' '.join(c['tags'])}")
            print(f"     선정 이유: {c['_why']}")
