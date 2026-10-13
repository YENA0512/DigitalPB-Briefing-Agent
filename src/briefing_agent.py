"""
디지털PB 브리핑 Agent — LangGraph

    START → diagnose
              ↓ 리스트 반환 → 병렬 fan-out
       search_daily / search_weekly / search_monthly / search_market
              ↓ fan-in (evidence reducer 가 병합)
            generate                        카드 선택 + 문구 생성
              ↓ 고정 병렬
       review_compliance / review_grounding / review_format
              ↓ fan-in
            aggregate
              ↓ 문자열 반환 → 택1
       optimize ──┐      fallback      match_contents → finalize → END
                  └→ 3개 review 로 복귀 (Feedback Loop, 최대 3회)

`USE_LLM=false` 면 API 키 없이 전체 흐름이 돈다. 이 경로를 끝까지 유지한다.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import case_labels
import case_router
import config
import content_matcher
import llm
import market_tool
import mcp_client
import news_tool
import prompts
import retriever
import sources as src_render
import tracing
from reducers import accumulate, keep_latest_round

USE_LLM = config.USE_LLM

CASES = case_router.CASES
LIMITS = case_router.DATA["_meta"]["limits"]

#  41케이스 원본 제한(13~74자)은 **현재 카드 UI 의 제약**이고 폴백 문구에만 쓴다.
#  채팅형 UI 로 가면서 생성 문구는 config 의 더 긴 한도를 따른다.
ORIGINAL_MIN, ORIGINAL_MAX = LIMITS["상세조언"]
MIN_LEN, MAX_LEN = config.ADVICE_MIN_LEN, config.ADVICE_MAX_LEN
MAX_SENTENCES = config.ADVICE_MAX_SENTENCES
SLOTS = set(case_router.DATA["_meta"]["slots"])


# ---------------------------------------------------------------- State

class BriefingState(TypedDict):
    # 입력
    portfolio: dict
    profile: dict
    recent_views: list

    # 진단 = 라우팅 키
    metrics: dict
    change_type: str
    gap_type: str
    market: dict
    case_id: str

    # 근거와 콘텐츠 — 절대 합치지 않는다
    evidence: Annotated[list, accumulate]     # 검증 대상
    contents: list                            # KB Think 링크. 검증 대상 아님

    # 생성·심사
    selected_card: str
    selection_reason: str
    card_scores: dict
    draft: str

    # ★ 칸을 둘로 나눈 이유는 reducers.py 참고
    reviews: Annotated[list, keep_latest_round]    # 현재 회차만. 판정에 쓴다
    review_history: Annotated[list, accumulate]    # 전 회차 누적. 감사 추적
    revision: int

    # 출력
    card_spec: dict
    fallback_used: bool
    approval: dict              # 담당자 검수 결과 — 승인자·시각·결정 (감사 추적)
    logs: Annotated[list, accumulate]


# ---------------------------------------------------------------- Mock 데이터

#  고객 실데이터는 쓰지 않는다. 구조만 실제와 같게 둔 목데이터다.
MOCK_PORTFOLIOS = {
    "반도체편중": {
        "total": 91_754_057, "prev_total": 92_593_406, "days_since": 5,
        "prev_holdings": 3,
        "holdings": [
            {"name": "KODEX 반도체",   "weight": 0.42, "delta": -624_000, "region": "국내"},
            {"name": "KB글로벌AI펀드", "weight": 0.31, "delta": -219_000, "region": "해외"},
            {"name": "美 단기국채ETF", "weight": 0.27, "delta":   +4_000, "region": "해외"},
        ],
    },
    "안정형과보수": {
        "total": 48_200_000, "prev_total": 48_100_000, "days_since": 40,
        "prev_holdings": 2,
        "holdings": [
            {"name": "KB단기채권펀드", "weight": 0.62, "delta": +62_000, "region": "국내"},
            {"name": "KB MMF",        "weight": 0.38, "delta": +38_000, "region": "국내"},
        ],
    },
    "해외분산상승": {
        "total": 120_400_000, "prev_total": 117_900_000, "days_since": 3,
        "prev_holdings": 3,
        "holdings": [
            {"name": "KB미국대표성장ETF", "weight": 0.34, "delta": +1_300_000, "region": "해외"},
            {"name": "KB글로벌AI펀드",   "weight": 0.33, "delta":   +900_000, "region": "해외"},
            {"name": "KODEX 200",       "weight": 0.33, "delta":   +300_000, "region": "국내"},
        ],
    },
    "신규고객": {
        "total": 0, "prev_total": 0, "days_since": 12, "prev_holdings": 0,
        "holdings": [],
    },
    "첫투자시작": {
        "total": 3_000_000, "prev_total": 0, "days_since": 2, "prev_holdings": 0,
        "holdings": [
            {"name": "KB밸런스포트폴리오", "weight": 1.0, "delta": +30_000, "region": "국내"},
        ],
    },
}

#  프로파일·열람이력도 고객마다 다르다. 하나로 고정하면 화면에서
#  "입력이 달라진다"가 보이지 않고, 콘텐츠 매칭의 열람 가점도 늘 같아진다.
MOCK_PROFILES = {
    "반도체편중":   ({"wmti": "APML", "age_band": "30대", "risk": "적극투자형",
                   "level": "중급"}, ["#반도체", "#ETF"]),
    "안정형과보수": ({"wmti": "CSPL", "age_band": "50대", "risk": "안정추구형",
                   "level": "입문"}, ["#절세", "#퇴직연금"]),
    "해외분산상승": ({"wmti": "APWL", "age_band": "40대", "risk": "위험중립형",
                   "level": "심화"}, ["#해외증시", "#환율"]),
    "신규고객":     ({"wmti": "CSML", "age_band": "20대", "risk": "안정형",
                   "level": "입문"}, ["#투자입문"]),
    "첫투자시작":   ({"wmti": "CPML", "age_band": "20대", "risk": "위험중립형",
                   "level": "입문"}, ["#투자입문", "#ETF"]),
}

DEFAULT_PROFILE = ({"wmti": "APML", "age_band": "30대", "risk": "위험중립형",
                    "level": "중급"}, ["#ETF", "#반도체"])


def inputs_for(name: str) -> dict:
    """케이스 이름 또는 CASE ID → **그래프에 실제로 들어가는 입력**.

    화면의 "Agent 입력" 패널과 실행 경로가 **같은 함수**를 쓴다.
    따로 만들면 화면이 보여주는 것과 실제 입력이 갈린다.
    """
    if name in MOCK_PORTFOLIOS:
        profile, views = MOCK_PROFILES.get(name, DEFAULT_PROFILE)
        return {"portfolio": MOCK_PORTFOLIOS[name],
                "profile": profile, "recent_views": views}

    #  CASE1~41 — 조건에서 역산한 목 포트폴리오 (run_batch 와 같은 함수)
    import run_batch
    cond = case_router.CASES.get(name, {}).get("cond", {})
    market = cond.get("market") or ""
    profile, views = DEFAULT_PROFILE
    if market.startswith("해외"):
        profile = {**profile, "risk": "적극투자형"}
        views = ["#해외증시", "#환율"]
    if cond.get("asset") in ("X>X", "X>O"):
        profile = {**profile, "age_band": "20대", "level": "입문"}
        views = ["#투자입문"]
    return {"portfolio": run_batch.portfolio_for(name),
            "profile": profile, "recent_views": views}


BANNED = ["보장", "확실", "반드시", "무조건", "지금이 기회", "매수",
          "비중을 늘리", "예상됩니다", "회복될 것", "오를 전망", "담아두"]


# ---------------------------------------------------------------- Tool (Rule)

def calc_portfolio_metrics(portfolio: dict) -> dict:
    """수익률·비중·집중도·기여도 계산. LLM 아님 — 같은 입력이면 같은 출력이어야 한다."""
    holdings = portfolio.get("holdings", [])
    if not holdings:
        return {"delta": 0, "rate": 0.0, "max_weight": 0.0,
                "top_contributor": None, "region_mix": {}, "total": portfolio.get("total", 0)}

    delta = sum(h["delta"] for h in holdings)
    prev = portfolio.get("prev_total") or portfolio.get("total") or 1
    region_mix: dict[str, float] = {}
    for h in holdings:
        region_mix[h["region"]] = round(region_mix.get(h["region"], 0) + h["weight"], 4)

    return {
        "delta": delta,
        "rate": round(delta / prev * 100, 2),
        "max_weight": max(h["weight"] for h in holdings),
        "top_contributor": min(holdings, key=lambda h: h["delta"]),
        "region_mix": region_mix,
        "total": portfolio.get("total", 0),
    }


def check_banned_phrases(text: str) -> list[str]:
    """명백한 금지어는 Rule 이 먼저 거른다 (하이브리드 1차)."""
    return [w for w in BANNED if w in text]


def normalize_tags_position(text: str) -> str:
    """마침표 뒤에 떨어진 출처 태그를 직전 문장 안으로 끌어온다.

        "…줄었어요. [portfolio] 보유…"  →  "…줄었어요 [portfolio]. 보유…"

    생성 주체(LLM / Rule)마다 태그를 마침표 앞뒤로 다르게 붙인다.
    심사가 그 표기 차이로 반려하면 루프만 돈다.
    """
    return re.sub(r"([.!?])\s*(\[[^\[\]]+\])", r" \2\1", text)


def split_sentences(text: str) -> list[str]:
    """한국어 종결어미 기준. 출처 태그는 문장에 붙은 채로 둔다."""
    parts = re.split(r"(?<=[.!?])\s+", normalize_tags_position(text).strip())
    return [p.strip() for p in parts if p.strip()]


def extract_tags(text: str) -> list[str]:
    return re.findall(r"\[([^\[\]]+)\]", text)


def fmt_amount(won: int) -> str:
    """억원 미만은 원 단위, 억원 이상은 X억 X만원 (cases_41.json _meta.amount_format)."""
    won = abs(int(won))
    if won < 100_000_000:
        return f"{won:,}원"
    eok, rest = divmod(won, 100_000_000)
    man = rest // 10_000
    return f"{eok}억 {man:,}만원" if man else f"{eok}억원"


# ---------------------------------------------------------------- Node ① 진단

def diagnose(state: BriefingState) -> dict:
    """상황을 진단하고 41케이스를 판정한다. 여기 결과가 전부 라우팅 키가 된다.

    판정은 전부 Rule 이다. 규제 영역이라 같은 입력에 같은 출력이 보장돼야 하고,
    왜 그 케이스로 갔는지 추적 가능해야 한다.
    """
    pf = state["portfolio"]
    m = calc_portfolio_metrics(pf)

    prev_has = bool(pf.get("prev_holdings", 0)) or bool(pf.get("prev_total", 0))
    cur_has = bool(pf.get("holdings"))

    # 자산변동 유형
    if not cur_has:
        change = "자산없음"
    elif not prev_has:
        change = "자산생김"
    elif m["rate"] <= -0.5:
        change = "급락" if m["rate"] <= -30 else "하락"
    elif m["rate"] >= 0.5:
        change = "급등" if m["rate"] >= 30 else "상승"
    else:
        change = "유지"

    # 하우스뷰 갭 — 과편중 / 과보수 / 정합
    risky = sum(h["weight"] for h in pf.get("holdings", [])
                if not any(k in h["name"] for k in ("채권", "국채", "MMF", "단기")))
    if not cur_has:
        gap = "정합"
    elif risky <= 0.25:
        # 먼저 본다. 국내 채권형 100% 는 "국내 편중"이 아니라 과보수다.
        gap = "과보수"
    elif m["max_weight"] >= 0.40 or m["region_mix"].get("국내", 0) >= 0.70:
        gap = "과편중"
    else:
        gap = "정합"

    # 시황 — MCP 서버의 kb-market 도구. 실패하면 직접 호출로 떨어진다.
    # 국내/해외 중 어느 쪽을 쓸지는 보유 지역 비중으로 정한다.
    view, via = mcp_client.market_view()
    region = "국내" if m["region_mix"].get("국내", 0) >= m["region_mix"].get("해외", 0) else "해외"
    if not cur_has:
        region = "국내"
    outlook = view[region]["outlook"]

    case_id = case_router.resolve_case({
        "prev_has": prev_has, "cur_has": cur_has,
        "days": pf.get("days_since", 1), "rate": m["rate"],
        "region": region, "outlook": outlook,
    })

    return {
        "metrics": m, "change_type": change, "gap_type": gap, "case_id": case_id,
        "market": {**view, "region_used": region, "outlook_used": outlook},
        "revision": 0, "fallback_used": False, "contents": [],
        "logs": [f"진단: {change} / {gap} / {m['rate']:+.2f}% → {case_id} "
                 f"(전망 {region}{outlook} · 시황 {via}"
                 f"{' · stale' if view.get('stale') else ''})"],
    }


def route_after_diagnose(state: BriefingState) -> list[str]:
    """리스트를 반환하면 해당 노드들이 **병렬 실행**된다 (문자열이면 택1).

    자산이 없는 고객에게 어제 코스피 얘기를 할 이유가 없다.
    라우팅이 검색 경로 자체를 바꾼다.
    """
    if state["change_type"] in ("자산없음", "자산생김"):
        #  보유 종목이 없으면 종목 뉴스를 찾을 대상도 없다
        return ["search_monthly", "search_market"]
    return ["search_daily", "search_weekly", "search_monthly",
            "search_market", "search_news"]


# ---------------------------------------------------------------- Node ② 검색 (병렬)

def _query(state: BriefingState) -> str:
    m = state["metrics"]
    bits = [state["change_type"], state["gap_type"]]
    if m.get("top_contributor"):
        bits.append(m["top_contributor"]["name"])
    bits.append(state["market"]["region_used"])
    return " ".join(bits)


def search_daily(state: BriefingState) -> dict:
    hits = retriever.search("daily", _query(state), k=2)
    return {"evidence": hits, "logs": [f"일간 검색 {len(hits)}건 ({retriever.mode()})"]}


def search_weekly(state: BriefingState) -> dict:
    hits = retriever.search("weekly", _query(state), k=1)
    return {"evidence": hits, "logs": [f"주간 검색 {len(hits)}건"]}


def search_monthly(state: BriefingState) -> dict:
    hits = retriever.search("monthly", _query(state), k=2)
    return {"evidence": hits, "logs": [f"월간 House View 검색 {len(hits)}건"]}


def search_market(state: BriefingState) -> dict:
    """실시간 지표. **MCP 서버(kb-market)** 를 거친다.

    같은 시세 정의를 다른 팀 Agent 도 쓸 수 있게 Tool 을 서버로 분리했다.
    서버가 없으면 `mcp_client` 가 직접 호출로 떨어진다 — 데모는 멈추지 않는다.
    """
    region = state["market"]["region_used"]
    want = ["^KS11", "USDKRW=X"] if region == "국내" else ["^GSPC", "^SOX", "USDKRW=X"]
    ev, via = mcp_client.market_evidence(want)
    return {"evidence": ev,
            "logs": [f"시황 지표 {len(ev)}건 ({via} · Yahoo Finance)"]}


def search_news(state: BriefingState) -> dict:
    """보유 종목·섹터 관련 기사. 근거 3층의 마지막 층이다.

        market_tool  숫자 — 코스피 -3.39%
        retriever    해설 — 반도체 업종에 차익 실현이 번졌다
        news_tool    사건 — '반도체 약세' 코스피 6,500 내줘 (MBC뉴스)

    고객이 알고 싶은 "왜 줄었는지"에 가장 가까운 것이 기사다.
    실패하면 빈 리스트다 — 뉴스는 있으면 좋은 것이고 없다고 멈추지 않는다.
    """
    ev, via = mcp_client.news_for_holdings(
        state["portfolio"].get("holdings", []),
        context=state["market"]["region_used"], limit=3)
    matched = ", ".join(e.get("matched", "") for e in ev) or "없음"
    return {"evidence": ev,
            "logs": [f"뉴스 {len(ev)}건 ({via} · 보유 종목 매칭: {matched})"]}


# ---------------------------------------------------------------- Node ③ 카드 선택 + 생성

CARDS = ["personal_briefing", "domestic_market", "fx", "content"]


def score_cards(state: BriefingState) -> dict[str, float]:
    """랜덤 4택1을 대체한다. 왜 골랐는지가 숫자로 남는다."""
    m, s = state["metrics"], {c: 0.0 for c in CARDS}
    mk = state["market"]

    if state["change_type"] in ("급락", "급등"):
        s["personal_briefing"] += 6.0 + abs(m["rate"]) * 0.1
    elif state["change_type"] in ("하락", "상승"):
        s["personal_briefing"] += 3.0 + abs(m["rate"]) * 2
    if state["gap_type"] in ("과편중", "과보수"):
        s["personal_briefing"] += 1.5
    if state["change_type"] in ("자산없음", "자산생김"):
        s["content"] += 5.0
    if m["region_mix"].get("국내", 0) >= 0.35:
        s["domestic_market"] += 2.0 + abs(mk["국내"]["change_1d"]) * 0.3
    if m["region_mix"].get("해외", 0) >= 0.30:
        s["fx"] += 1.5 + abs(mk["환율"]["change_1d"]) * 2
    return {k: round(v, 2) for k, v in s.items()}


def _few_shot(case_id: str, n: int = 2) -> str:
    """같은 축(앞뒤 케이스)의 문구를 톤 예시로 넣는다."""
    num = int(case_id[4:])
    picks = [f"CASE{num + d}" for d in (-1, 1, -2, 2) if 1 <= num + d <= 41]
    out = [f"- {CASES[p]['advice']}" for p in picks[:n] if p in CASES]
    return "\n".join(out) or "- (없음)"


def _holdings_block(portfolio: dict) -> str:
    """보유 종목을 비중 순으로. 이 수치는 전부 [portfolio] 태그 대상이다."""
    hs = sorted(portfolio.get("holdings", []), key=lambda h: -h["weight"])
    if not hs:
        return "- (보유 종목 없음)"
    return "\n".join(
        f"- {h['name']} · 비중 {h['weight']:.0%} · {h['region']} · "
        f"{'+' if h['delta'] >= 0 else '-'}{abs(h['delta']):,}원" for h in hs)


def _evidence_block(evidence: list) -> str:
    return "\n".join(f"- [{e['doc']}] {e['title']}\n  {e['text']}" for e in evidence)


def _rule_draft(state: BriefingState) -> str:
    """LLM 없이 쓰는 경로. **발표장 안전망이므로 3축을 반드시 통과해야 한다.**

    두 가지를 지킨다.
      · 모든 문장에 출처 태그 — 없으면 grounding 이 전건 반려한다
      · 본문(태그 제외) MAX_LEN 자 이내 — 넘으면 format 이 반려한다
    v1 에서 상승·유지 케이스가 전부 폴백으로 빠진 원인이 이 둘이었다.
    """
    m, ct = state["metrics"], state["change_type"]
    ev = state["evidence"]
    idx = next((e for e in ev if e["doc"].startswith("시장-")), None)

    def market_sentence() -> str:
        """시황 한 문장. 근거가 없으면 빈 문자열."""
        if not idx:
            return ""
        d = idx["numbers"]["change_1d"]
        short = idx["title"].split(" ")[0]
        move = "하락" if d < 0 else ("상승" if d > 0 else "보합")
        return f"{short}는 전일 {abs(d):.2f}% {move}했어요 [{idx['doc']}]."

    # 자산이 없거나 막 생긴 케이스 — 원본 문구를 쓰고 시황을 덧붙인다
    if ct in ("자산없음", "자산생김"):
        base = CASES[state["case_id"]]["advice"].strip()
        if len(base) <= MAX_LEN - 2:
            return f"{base[:-1] if base.endswith('.') else base} [portfolio]."
        return f"{base[:MAX_LEN - 3]}… [portfolio]."

    top = m["top_contributor"]
    days = state["portfolio"].get("days_since", 1)
    verb = "줄었어요" if m["delta"] < 0 else "늘었어요"

    # 짧은 조각부터 조립하고, 예산이 남는 만큼만 덧붙인다
    head = f"{days}일 사이 {fmt_amount(m['delta'])}이 {verb} [portfolio]."
    cause = f"{top['name']}에서 {fmt_amount(top['delta'])} 움직였어요 [portfolio]."
    conc = (f"한 종목 비중이 {m['max_weight']:.0%}예요 [portfolio]."
            if m["max_weight"] >= 0.40 else "")
    mkt = market_sentence()

    out, used = [head], len(_plain(head))
    for piece in (cause, conc, mkt):
        if not piece:
            continue
        cost = len(_plain(piece)) + 1
        if used + cost <= MAX_LEN and len(out) < 4:
            out.append(piece)
            used += cost
    return " ".join(out)


def _plain(text: str) -> str:
    """출처 태그를 뺀 본문. 글자수 규칙은 태그를 세지 않는다."""
    return re.sub(r"\s*\[[^\[\]]+\]", "", text).strip()


def generate(state: BriefingState) -> dict:
    """카드를 고르고 문구를 만든다. 문장별 출처 태그를 강제한다."""
    scores = score_cards(state)
    card = max(scores, key=scores.get)
    m = state["metrics"]
    logs = []

    draft, used_llm = None, False
    if llm.available():
        top = m.get("top_contributor") or {"name": "-", "delta": 0}
        out, why = llm.ask(
            llm.AdviceOut,
            prompts.SYSTEM.format(banned=prompts.BANNED_DESC, min_len=MIN_LEN,
                                  max_len=MAX_LEN, max_sent=MAX_SENTENCES),
            prompts.GENERATE.format(
                case_id=state["case_id"], change_type=state["change_type"],
                gap_type=state["gap_type"], delta=m["delta"], rate=m["rate"],
                max_weight=m["max_weight"], top_name=top["name"],
                top_delta=top["delta"], region_mix=m["region_mix"],
                original=CASES[state["case_id"]]["advice"],
                few_shot=_few_shot(state["case_id"]),
                holdings=_holdings_block(state["portfolio"]),
                evidence=_evidence_block(state["evidence"])),
            purpose="generate")
        if out:
            draft, used_llm = out.advice, True
            logs.append(f"LLM 생성 ({config.OPENAI_MODEL})")
        else:
            logs.append(f"LLM 생성 실패 → Rule 경로 ({why})")

    if draft is None:
        draft = _rule_draft(state)
        if not used_llm and llm.available():
            pass
        elif not llm.available():
            logs.append("Rule 생성 (USE_LLM=false)")

    reason_bits = [state["change_type"]]
    if m["max_weight"]:
        reason_bits.append(f"최대비중 {m['max_weight']:.0%}")
    reason_bits.append(f"{state['market']['region_used']}시황 "
                       f"{state['market'][state['market']['region_used']]['change_1d']:+.2f}%")

    logs.insert(0, f"카드 선택: {card} {scores} (제친 카드 {len(CARDS) - 1}개)")
    return {"selected_card": card, "card_scores": scores,
            "selection_reason": " · ".join(reason_bits),
            "draft": draft, "logs": logs}


# ---------------------------------------------------------------- Node ④ 3축 병렬 심사

def _review(axis: str, revision: int, passed: bool,
            issues: list | None = None, **extra) -> dict:
    """심사 결과에는 **반드시 revision 을 박는다.**

    reducer(keep_latest_round)가 이 값으로 회차를 가른다. 빼먹으면
    0회차로 취급돼 최신 결과가 버려진다.
    """
    return {"axis": axis, "revision": revision, "passed": passed,
            "issues": issues or [], **extra}


def review_compliance(state: BriefingState) -> dict:
    """Rule 1차 → LLM 2차 하이브리드.

    명백한 금지어는 규칙이 결정적으로 잡는다. LLM 은 규칙이 못 잡는
    회색지대(우회적 권유, 암시적 미래 단정)만 본다.
    """
    rev = state["revision"]
    hits = check_banned_phrases(state["draft"])
    if hits:
        r = _review("compliance", rev, False,
                    [f"금지어 '{w}'" for w in hits], stage="rule")
        return {"reviews": [r], "review_history": [r],
                "logs": [f"컴플라이언스(Rule): {len(hits)}건 지적 — {', '.join(hits)}"]}

    if llm.available():
        out, why = llm.ask(llm.JudgeOut, prompts.COMPLIANCE_JUDGE.format(draft=state["draft"]),
                           "판정하세요.", purpose="compliance")
        if out:
            r = _review("compliance", rev, out.passed, out.issues,
                        stage="llm", reason=out.reason)
            return {"reviews": [r], "review_history": [r],
                    "logs": [f"컴플라이언스(LLM 2차): "
                             f"{'통과' if out.passed else f'{len(out.issues)}건 지적'}"
                             f"{' — ' + '; '.join(out.issues) if out.issues else ''}"]}

    r = _review("compliance", rev, True, stage="rule")
    return {"reviews": [r], "review_history": [r], "logs": ["컴플라이언스(Rule): 통과"]}


def review_grounding(state: BriefingState) -> dict:
    """문장 단위 검증.

    `[portfolio]` 는 자체 계산값이라 외부 근거가 불필요하다.
    `[일간-…]` `[시장-…]` 은 evidence 에 그 doc 이 있어야 하고,
    LLM 이 켜져 있으면 본문이 주장을 지지하는지까지 본다.

    시황을 인용하지 않는 케이스는 **면제**한다. 일괄 적용하면
    통과할 수 없는 문구로 루프만 돈다 (이미 한 번 겪었다).
    """
    rev = state["revision"]
    if state["change_type"] in ("자산없음", "자산생김"):
        r = _review("grounding", rev, True, exempt=True)
        return {"reviews": [r], "review_history": [r],
                "logs": ["근거 결속: 면제 (시황 미인용 케이스)"]}

    docs = {e["doc"]: e for e in state["evidence"]}
    issues, checked = [], 0

    for sent in split_sentences(state["draft"]):
        tags = extract_tags(sent)
        if not tags:
            if re.search(r"\d", sent):          # 수치가 있는 무태그 문장은 사실 주장이다
                issues.append(
                    f"이 문장에 출처 태그가 없습니다 — 문장 끝에 태그를 붙이세요. "
                    f"자체 계산값(증감액·비중·기여도)이면 [portfolio], "
                    f"외부 사실이면 근거 목록의 doc 을 쓰세요: \"{sent}\"")
            continue
        for t in tags:
            if t == "portfolio":
                continue
            checked += 1
            if t not in docs:
                issues.append(f"evidence 에 없는 출처 '[{t}]'")

    # LLM 2차 — 태그는 맞는데 내용이 어긋나는 경우를 잡는다
    if llm.available() and not issues:
        for sent in split_sentences(state["draft"]):
            tags = [t for t in extract_tags(sent) if t != "portfolio"]
            if not tags:
                continue
            ev = _evidence_block([docs[t] for t in tags if t in docs])
            out, _ = llm.ask(llm.JudgeOut,
                             prompts.GROUNDING_JUDGE.format(evidence=ev, sentence=sent),
                             "판정하세요.", purpose="grounding")
            if out and not out.passed:
                issues += [f"근거 불일치: {i}" for i in (out.issues or [out.reason])]
            break                                # 문장 하나만 샘플 검증 (비용 통제)

    r = _review("grounding", rev, not issues, issues, tags_checked=checked)
    return {"reviews": [r], "review_history": [r],
            "logs": [f"근거 결속: {'통과' if not issues else f'{len(issues)}건 지적'} "
                     f"(외부 태그 {checked}개 대조)"
                     + (f" — {'; '.join(issues)}" if issues else "")]}


def review_format(state: BriefingState) -> dict:
    """전부 Rule. LLM 을 쓰지 않는다 — 결정적 판정이고 LLM 이 불필요하다."""
    rev, draft = state["revision"], state["draft"]
    body = _plain(draft)                                   # 태그 제외 본문
    issues = []

    n = len(body)
    if n > MAX_LEN:
        issues.append(f"글자수 {n}자로 {n - MAX_LEN}자 초과 — {MAX_LEN}자 이내로 줄이세요 "
                      f"(출처 태그는 글자수에서 제외합니다. 본문만 {MAX_LEN}자)")
    elif n < MIN_LEN:
        issues.append(f"글자수 {n}자로 {MIN_LEN - n}자 부족 — {MIN_LEN}자 이상 쓰세요")

    sents = split_sentences(body)
    if len(sents) > MAX_SENTENCES:
        issues.append(f"문장이 {len(sents)}개입니다 — "
                      f"{len(sents) - MAX_SENTENCES}개를 합쳐 {MAX_SENTENCES}문장 이내로")

    found = set(re.findall(r"\{(\w+)\}", draft))
    unknown = found - SLOTS
    if unknown:
        issues.append(f"정의되지 않은 슬롯 {sorted(unknown)}")
    if found & SLOTS:
        issues.append(f"치환되지 않은 슬롯 {sorted(found & SLOTS)}")

    # 금액 표기 — 억 단위인데 원 단위로 쓰면 지적
    for raw in re.findall(r"([\d,]{9,})원", body):
        if int(raw.replace(",", "")) >= 100_000_000:
            issues.append(f"억원 이상은 'X억 X만원' 표기 ({raw}원)")

    r = _review("format", rev, not issues, issues, length=n, sentences=len(sents))
    return {"reviews": [r], "review_history": [r],
            "logs": [f"형식: {'통과' if not issues else f'{len(issues)}건 지적'} "
                     f"({n}자 · {len(sents)}문장)"
                     + (f" — {'; '.join(issues)}" if issues else "")]}


# ---------------------------------------------------------------- Node ⑤ 종합 · 분기

def aggregate(state: BriefingState) -> dict:
    """현재 회차 세 축만 본다. reducer 가 이미 이전 회차를 버렸다."""
    rv = state["reviews"]
    failed = [r["axis"] for r in rv if not r["passed"]]
    return {"logs": [f"심사 종합(rev {state['revision']}): "
                     f"{'통과' if not failed else '반려 — ' + ', '.join(failed)} "
                     f"[{len(rv)}축 판정]"]}


def route_after_review(state: BriefingState) -> Literal["optimize", "fallback", "match_contents"]:
    """문자열을 반환하므로 택1이다."""
    if all(r["passed"] for r in state["reviews"]):
        return "match_contents"
    if state["revision"] >= 3:
        return "fallback"
    return "optimize"


def optimize(state: BriefingState) -> dict:
    """지적사항을 반영해 다시 쓴다.

    `reviews` 를 비우려고 애쓰지 않는다. revision 을 올리면
    reducer 가 이전 회차를 스스로 버린다 (reducers.py 참고).
    """
    issues = [f"- [{r['axis']}] {i}" for r in state["reviews"] for i in r.get("issues", [])]
    nxt = state["revision"] + 1
    text = "\n".join(issues) or "- (사유 없음)"

    if llm.available():
        out, why = llm.ask(
            llm.AdviceOut,
            prompts.SYSTEM.format(banned=prompts.BANNED_DESC, min_len=MIN_LEN,
                                  max_len=MAX_LEN, max_sent=MAX_SENTENCES),
            prompts.OPTIMIZE.format(draft=state["draft"], issues=text)
            + "\n\n## 사용 가능한 근거\n" + _evidence_block(state["evidence"]),
            purpose="optimize")
        if out:
            return {"draft": out.advice, "revision": nxt,
                    "logs": [f"재작성 {nxt}회차 (LLM) — 반영: {len(issues)}건"]}

    # Rule 폴백 — 금지어를 지우고 길이를 맞춘다
    fixed = state["draft"]
    for r in state["reviews"]:
        for i in r.get("issues", []):
            m = re.search(r"'([^']+)'", i)
            if m and m.group(1) in fixed:
                fixed = fixed.replace(m.group(1), "")
    fixed = re.sub(r"\s{2,}", " ", fixed).strip()
    return {"draft": fixed, "revision": nxt,
            "logs": [f"재작성 {nxt}회차 (Rule) — 반영: {len(issues)}건"]}


def fallback(state: BriefingState) -> dict:
    """생성이 실패해도 서비스는 죽지 않는다.

    41케이스 **원본 문구**로 돌아간다. 현업이 쓴 문장이라 컴플라이언스가 보증된다.
    """
    m = state["metrics"]
    slots = {"days": state["portfolio"].get("days_since", 1),
             "diffAmt": f"{abs(m['delta']):,}",
             "curAmt": f"{m.get('total', 0):,}"}
    rendered = case_router.render(state["case_id"], slots)
    return {"draft": rendered["advice"], "fallback_used": True,
            "logs": [f"폴백: {state['case_id']} 원본 문구 사용 "
                     f"(3회 재작성 후에도 반려)"]}


# ---------------------------------------------------------------- Node ⑥ 콘텐츠 · 확정

#  situation_to_tag 의 키 어휘로 되돌린다. 진단은 7종으로 세분화했지만
#  콘텐츠 태그 테이블은 현업 5종 어휘다 — 테이블을 고치지 않고 여기서 맞춘다.
_CT_FOR_TAGS = {"하락": "급락", "급락": "급락", "상승": "상승", "급등": "상승",
                "유지": "유지", "자산없음": "자산없음", "자산생김": "자산생김"}


def match_contents(state: BriefingState) -> dict:
    """Feedback Loop **밖**이다. 확정 문구 기준으로 매칭한다.

    루프 안에 두면 재작성 3회 시 API 를 3번 쓰고 매칭 정확도도 떨어진다.
    결과는 contents 에만 넣는다 — evidence 에 넣으면 교양 콘텐츠가
    시황 판단의 근거로 인용되는 사고가 난다.
    """
    out = content_matcher.match_contents(
        {**state, "change_type": _CT_FOR_TAGS.get(state["change_type"], state["change_type"])},
        k=2)
    return {"contents": out["contents"], "logs": out["logs"]}


def human_review(state: BriefingState) -> dict:
    """담당자 검수 — Human-in-the-Loop.

    ## 왜 여기 있는가

    금소법상 투자 문구는 **사람 책임 하에** 노출되어야 한다. 3축 심사를
    통과했다고 바로 고객에게 나가면 그 책임 구조가 성립하지 않는다.
    `finalize` 바로 앞에 두어, 승인된 것만 카드 스펙이 된다.

    검수 단위는 고객이 아니라 **케이스**다. 41건을 검수하면 전 고객에게 나간다.

    ## 세 갈래

        approve        그대로 확정
        edit           담당자가 고친 문구로 교체 후 확정.
                       **재심사하지 않는다** — 사람이 쓴 문장이고 사람이 책임진다
        reject(사유)   revision+1 후 optimize 로 되돌린다. 사유가 재작성 지시가 된다

    ## 재개 방법

        graph.invoke(Command(resume={"action": "approve", "by": "홍길동"}), config)

    `thread_id` 는 case_id 다. 체크포인터가 중단 지점을 들고 있으므로
    배치가 41건을 멈춰 두고 담당자가 하나씩 처리할 수 있다.
    """
    spec_preview = {
        "case_id": state["case_id"],
        "case_label": case_labels.label(state["case_id"]),
        "advice": state["draft"],
        "advice_display": src_render.render(state["draft"], state["evidence"])["display"],
        "change_type": state["change_type"],
        "gap_type": state["gap_type"],
        "selected_card": state["selected_card"],
        "selected_over": [c for c in CARDS if c != state["selected_card"]],
        "selection_reason": state["selection_reason"],
        "evidence": [{"doc": e["doc"], "title": e["title"]} for e in state["evidence"]],
        "contents": [{"title": c["title"], "url": c.get("url", "")}
                     for c in state["contents"]],
        "review": {r["axis"]: {"passed": r["passed"], "issues": r.get("issues", [])}
                   for r in state["reviews"]},
        "revision": state["revision"],
        "fallback_used": state["fallback_used"],
    }

    decision = interrupt(spec_preview) or {}
    action = decision.get("action", "approve")
    by = decision.get("by", "(미상)")
    at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if action == "reject":
        reason = decision.get("reason", "(사유 없음)")
        #  반려 사유를 심사 지적처럼 넣어 optimize 가 읽게 한다.
        #  revision 을 올리면 reducer 가 이전 회차를 버린다 (reducers.py).
        r = _review("human", state["revision"], False, [f"담당자 반려: {reason}"])
        return {"reviews": [r], "review_history": [r],
                "approval": {"action": "reject", "by": by, "at": at, "reason": reason},
                "logs": [f"검수 반려 ({by}): {reason}"]}

    if action == "edit":
        edited = decision.get("advice", state["draft"])
        return {"draft": edited,
                "approval": {"action": "edit", "by": by, "at": at,
                             "original": state["draft"]},
                "logs": [f"검수 수정 후 승인 ({by}) — 재심사하지 않음 (사람 책임)"]}

    return {"approval": {"action": "approve", "by": by, "at": at},
            "logs": [f"검수 승인 ({by})"]}


def route_after_review_human(state: BriefingState
                             ) -> Literal["optimize", "fallback", "finalize"]:
    """검수 결과로 분기. 반려면 재작성 루프로 되돌아간다."""
    if state.get("approval", {}).get("action") != "reject":
        return "finalize"
    if state["revision"] >= 3:
        return "fallback"
    return "optimize"


def finalize(state: BriefingState) -> dict:
    """카드 스펙을 확정한다.

    ## 내부 표기와 대고객 표기를 분리한다

    `advice` 는 `[일간-261012]` 가 박힌 내부 문구다 — 검수 화면과 감사 추적이
    쓴다. 고객에게는 `advice_display`(①②③) + `sources`(제목·발행처·링크)를
    내려준다. `[portfolio]` 는 고객 노출에서 완전히 사라진다.

    고객이 ① 을 누르면 그 출처의 **엔드서비스로 이동**한다. 리포트는
    KB Think 페이지, 뉴스는 기사, 시장지표는 투자홈 시장지표 화면이다.
    """
    m = state["metrics"]
    svc = case_router.SERVICES[CASES[state["case_id"]]["service"]]
    rendered = src_render.render(state["draft"], state["evidence"])

    #  뉴스는 출처 칩과 별도로 카드 하단에 펼쳐 보여준다 (관련 기사 영역)
    news = [{"title": e["title"], "url": e["url"], "publisher": e["publisher"],
             "date": e["date"], "matched": e.get("matched", "")}
            for e in state["evidence"] if e["doc"].startswith("뉴스-")]

    spec = {
        "case_id": state["case_id"],
        #  CASE19 만 떠 있으면 무슨 고객인지 아무도 모른다. 조건을 문장으로 편다.
        "case_label": case_labels.label(state["case_id"]),
        "card_type": state["selected_card"],
        "selected_over": [c for c in CARDS if c != state["selected_card"]],
        "selection_reason": state["selection_reason"],
        "card_scores": state["card_scores"],

        # ── 문구
        "advice": state["draft"],              # 내부(검수·감사) — 태그 포함
        "advice_display": rendered["display"],  # 대고객 — ①②③
        "advice_plain": rendered["plain"],      # 태그 없는 순수 문장
        "sources": rendered["sources"],         # 클릭 대상 출처 목록
        "서브조언": svc["서브조언"],
        "버튼명": svc["버튼명"],
        "end_service": {"name": svc["버튼명"], "link": svc.get("link", ""),
                        "element": svc.get("클릭요소명", "")},

        # ── 진단 — 뷰어의 "PB 점검 포인트"가 이 값으로 조립된다.
        #    새 LLM 호출 없이 Rule 결과를 그대로 내보낸다.
        "diagnosis": {
            "change_type": state["change_type"],
            "gap_type": state["gap_type"],
            "days_since": state["portfolio"].get("days_since", 1),
            "outlook_region": state["market"]["region_used"],
            "outlook": state["market"]["outlook_used"],
        },

        # ── 자산 변동
        "metrics": {"delta": m["delta"], "rate": m["rate"],
                    "max_weight": m["max_weight"], "total": m.get("total", 0),
                    "region_mix": m["region_mix"]},
        "contributions": [{"name": h["name"], "delta": h["delta"],
                           "weight": h["weight"], "region": h["region"]}
                          for h in state["portfolio"].get("holdings", [])],
        "market": {k: v for k, v in state["market"].items() if k != "환율"} |
                  {"환율": {"price": state["market"]["환율"]["price"],
                            "change_1d": state["market"]["환율"]["change_1d"]}},

        # ── 관련 콘텐츠
        "news": news,
        "contents": state["contents"],

        # ── 심사
        "review": {r["axis"]: r for r in state["reviews"]},
        "review_rounds": state["revision"] + 1,
        "review_history": state["review_history"],
        "fallback_used": state["fallback_used"],
        "approval": state.get("approval") or {"action": "auto", "by": "(검수 생략)"},
        "llm": {"used": llm.available(),
                "model": config.OPENAI_MODEL if llm.available() else None,
                "calls": llm.stats["calls"]},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #  실행 로그를 스펙에 싣는다. State 에만 두면 검수 화면·뷰어가 못 읽는다.
        "logs": list(state.get("logs") or []),
    }
    return {"card_spec": spec,
            "logs": [f"카드 스펙 확정 (출처 {len(rendered['sources'])}개 · "
                     f"뉴스 {len(news)}건 · 콘텐츠 {len(state['contents'])}건)"]}


# ---------------------------------------------------------------- 그래프 조립

REVIEWS = ("review_compliance", "review_grounding", "review_format")
SEARCHES = ("search_daily", "search_weekly", "search_monthly",
            "search_market", "search_news")


def build_graph(checkpointer=None):
    #  MCP 서버에 미리 붙어 둔다. 노드가 병렬로 돌 때 각자 붙으면 느리다.
    #  실패해도 그냥 진행한다 — 각 노드가 직접 호출로 떨어진다.
    mcp_client.connect()

    g = StateGraph(BriefingState)

    # 노드 이름을 명시한다. fn.__name__ 에서 뽑으면 테스트가 노드를 갈아끼울 때
    # 이름이 함께 바뀌어 엣지가 끊긴다 (실제로 끊겼다).
    for name, fn in (("diagnose", diagnose),
                     ("search_daily", search_daily),
                     ("search_weekly", search_weekly),
                     ("search_monthly", search_monthly),
                     ("search_market", search_market),
                     ("search_news", search_news),
                     ("generate", generate),
                     ("review_compliance", review_compliance),
                     ("review_grounding", review_grounding),
                     ("review_format", review_format),
                     ("aggregate", aggregate),
                     ("optimize", optimize),
                     ("fallback", fallback),
                     ("match_contents", match_contents),
                     ("human_review", human_review),
                     ("finalize", finalize)):
        g.add_node(name, fn)

    g.add_edge(START, "diagnose")
    g.add_conditional_edges("diagnose", route_after_diagnose, list(SEARCHES))

    for n in SEARCHES:                       # fan-in — evidence reducer 가 병합
        g.add_edge(n, "generate")

    for n in REVIEWS:                        # 3축 병렬 심사
        g.add_edge("generate", n)
        g.add_edge(n, "aggregate")

    g.add_conditional_edges("aggregate", route_after_review,
                            {"optimize": "optimize", "fallback": "fallback",
                             "match_contents": "match_contents"})

    for n in REVIEWS:                        # Feedback Loop — 세 축 전부로 복귀
        g.add_edge("optimize", n)

    g.add_edge("fallback", "match_contents")

    #  콘텐츠 매칭 → 담당자 검수 → 확정.
    #  검수는 **루프 밖**이지만 반려 시 optimize 로 되돌아간다.
    g.add_edge("match_contents", "human_review")
    g.add_conditional_edges("human_review", route_after_review_human,
                            {"optimize": "optimize", "fallback": "fallback",
                             "finalize": "finalize"})
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())


def initial_state(portfolio: dict, profile: dict | None = None,
                  recent_views: list | None = None) -> dict:
    return {
        "portfolio": portfolio,
        "profile": profile or {"wmti": "APML", "age_band": "30대",
                               "risk": "위험중립형", "level": "중급"},
        "recent_views": recent_views or ["#ETF", "#반도체"],
        "evidence": [], "contents": [], "reviews": [], "review_history": [],
        "approval": {}, "logs": [],
    }


# ---------------------------------------------------------------- 실행

_shared_app = None


def get_app():
    """프로세스 안에서 **하나의 그래프**를 공유한다.

    `build_graph()` 는 호출할 때마다 새 `InMemorySaver` 를 만든다.
    배치가 `human_review` 에서 멈춰 둔 건을 API 가 재개하려면 **같은
    체크포인터**를 봐야 한다. 따로 만들면 `KeyError` 로 재개가 실패한다.

    (운영은 `SqliteSaver` 로 바꿔 프로세스 경계를 넘어야 한다 — README 한계 절)
    """
    global _shared_app
    if _shared_app is None:
        _shared_app = build_graph()
    return _shared_app


def initial_state_for(name: str) -> dict:
    """케이스 이름 하나로 초기 State 를 만든다. 화면·CLI·배치가 공유한다."""
    i = inputs_for(name)
    return initial_state(i["portfolio"], i["profile"], i["recent_views"])


def run_one(name: str, portfolio: dict, app=None, quiet: bool = False,
            approver: str = "자동승인(데모)") -> dict:
    """1건 실행. `human_review` 에서 멈추면 자동 승인으로 재개한다.

    실제 운영은 `run_batch.py` 가 멈춤 상태를 `output/pending` 에 쌓고
    담당자가 하나씩 처리한다. 여기서는 CLI 데모라 바로 승인한다.
    """
    app = app or build_graph()
    #  Langfuse 콜백을 달면 그래프 1회 실행이 trace 하나가 되고
    #  LLM 호출이 그 안에 span 으로 붙는다. 키가 없으면 빈 리스트다.
    cfg = {"configurable": {"thread_id": name}, "recursion_limit": 60,
           "callbacks": tracing.callbacks()}
    i = inputs_for(name) if name in MOCK_PORTFOLIOS else {
        "portfolio": portfolio, "profile": None, "recent_views": None}
    result = app.invoke(
        initial_state(i["portfolio"], i.get("profile"), i.get("recent_views")),
        config=cfg)

    #  interrupt 가 걸리면 결과에 card_spec 이 없다. 승인으로 재개한다.
    guard = 0
    while "card_spec" not in result and guard < 5:
        guard += 1
        result = app.invoke(Command(resume={"action": "approve", "by": approver}),
                            config=cfg)
    state = app.get_state(cfg).values if "card_spec" not in result else result
    result = state if isinstance(state, dict) and "card_spec" in state else result

    #  심사 결과를 점수로 남긴다. 매일 쌓으면 폴백률·재작성 횟수의 추세가 보인다.
    if "card_spec" in result:
        with tracing.trace_run(result["card_spec"].get("case_id", name)) as tr:
            tr.score_spec(result["card_spec"])
            if tr.url:
                result["card_spec"]["trace_url"] = tr.url

    if quiet:
        return result

    spec = result["card_spec"]
    print(f"\n{'=' * 78}\n케이스: {name}  →  {spec['case_id']} "
          f"({spec.get('case_label','')})\n{'=' * 78}")
    for line in result["logs"]:
        print("  ·", line)

    print(f"\n  ── 대고객 노출 ──")
    print(f"  {spec['advice_display']}")
    print(f"  {spec['서브조언']}   [{spec['버튼명']}]")

    if spec["sources"]:
        print("\n  출처 (클릭 시 이동)")
        for so in spec["sources"]:
            print(f"    {so['marker']} [{so['kind']}] {so['title']}")
            print(f"       {so['publisher']}"
                  + (f" · {so['date']}" if so["date"] else "")
                  + (f"  → {so['url'][:58]}…" if so["url"] else ""))

    if spec["news"]:
        print("\n  관련 뉴스")
        for n in spec["news"]:
            print(f"    · [{n['matched']}] {n['title'][:52]}  ({n['publisher']})")

    if spec["contents"]:
        print("\n  관련 콘텐츠")
        for c in spec["contents"]:
            print(f"    · {c['title'][:52]}")
            print(f"      {c.get('summary', '')[:66]}")

    print(f"\n  ── 내부 ──")
    print(f"  태그 문구: {spec['advice'][:96]}…" if len(spec["advice"]) > 96
          else f"  태그 문구: {spec['advice']}")
    print(f"  카드: {spec['card_type']} — 제친 카드 {spec['selected_over']}")
    print(f"  선택이유: {spec['selection_reason']}")
    axes = " · ".join(f"{k} {'O' if v['passed'] else 'X'}"
                      for k, v in spec["review"].items())
    print(f"  심사: {axes} · {spec['review_rounds']}회차 · 폴백 {spec['fallback_used']}")
    ap = spec.get("approval", {})
    print(f"  검수: {ap.get('action','-')} · {ap.get('by','-')} · {ap.get('at','-')}")
    return result


if __name__ == "__main__":
    print(f"USE_LLM={USE_LLM}" + (f" · 모델 {config.OPENAI_MODEL}" if USE_LLM else ""))
    mcp_client.connect()
    print(f"Tool 경로: {mcp_client.mode()}")
    print(f"Langfuse : {tracing.state()}")
    if tracing.enabled():
        print(f"           {tracing.project_url('/traces')}")
    print(f"검색 모드: {retriever.mode() if retriever.build_index() or True else ''}")
    app = build_graph()
    for name, pf in MOCK_PORTFOLIOS.items():
        run_one(name, pf, app)
    print(f"\n{'=' * 74}\n{llm.summary()}")
