"""
KB 시황·뉴스 MCP 서버 — 교육과정 `w4_nb04` / `w5_nb01b` 방식 (FastMCP + streamable-http)

## 왜 Tool 을 MCP 로 빼는가

`market_tool.py` 와 `news_tool.py` 를 그래프 안에서 직접 import 해도 돈다.
그런데 그렇게 두면 **이 Agent 안에서만 쓸 수 있다.**

MCP 서버로 분리하면 같은 시황·뉴스 조회를 다른 팀 Agent 도 그대로 붙여 쓴다.
투자홈 브리핑, PB 상담 봇, 리포트 요약기가 **같은 시세 정의**를 쓰게 된다 —
"단기 전망 좋음/보통/나쁨"의 임계값이 팀마다 달라지는 사고를 막는다.

    [이 Agent]  ─┐
    [PB 상담봇] ─┼─→ kb-market MCP ─→ Yahoo Finance / Google News
    [리포트요약] ─┘

## 규칙

- **고객 데이터는 이 서버에 넘기지 않는다.** 종목명·섹터 어휘까지만 받는다.
  보유 금액·고객번호는 Agent 쪽에 남는다
- 도구는 실패해도 예외를 던지지 않는다. 호출부가 빈 결과로 계속 진행한다
- 판정(좋음/보통/나쁨)은 여기서 한다. **같은 수치면 같은 판정**이어야 하므로
  LLM 이 아니라 Rule 이고, 서버가 단일 정의를 갖는다

## 실행

    python mcp_servers/market_server.py          # 127.0.0.1:8765/mcp
    ./run_local.sh mcp
"""

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import market_tool  # noqa: E402
import news_tool    # noqa: E402

HOST, PORT = "127.0.0.1", 8765
mcp = FastMCP("KB-Market", host=HOST, port=PORT)


# ──────────────────────────────────────────────────────── 시황

@mcp.tool()
def get_market_snapshot() -> str:
    """국내외 주요 지수와 환율의 현재가·등락률을 조회한다.

    코스피·코스닥·원/달러·미국 반도체지수(SOX)·S&P500·나스닥·VIX 7종.
    반환은 JSON 문자열이며 각 항목에 price, change_1d(전일 대비 %),
    change_1m(1개월 %), stale(조회 실패 여부)이 들어 있다.
    """
    return json.dumps(market_tool.snapshot(), ensure_ascii=False)


@mcp.tool()
def get_market_view() -> str:
    """단기 시장 전망을 '좋음/보통/나쁨'으로 판정한다.

    국내는 코스피, 해외는 S&P500 의 전일 등락률을 ±0.5% 임계로 가른다.
    같은 수치면 항상 같은 판정이 나온다(Rule). 환율 현재가도 함께 반환한다.
    """
    return json.dumps(market_tool.market_view(), ensure_ascii=False)


@mcp.tool()
def get_market_evidence(symbols: str = "") -> str:
    """시황 지표를 근거(evidence) 형식으로 변환해 반환한다.

    Args:
        symbols: 쉼표로 구분한 심볼. 비우면 전체.
                 예) "^KS11,USDKRW=X"
    """
    want = [s.strip() for s in symbols.split(",") if s.strip()]
    ev = market_tool.as_evidence()
    if want:
        ev = [e for e in ev if e["doc"].replace("시장-", "") in want]
    return json.dumps(ev, ensure_ascii=False)


# ──────────────────────────────────────────────────────── 뉴스

@mcp.tool()
def search_news(query: str, limit: int = 3) -> str:
    """한국어 뉴스 기사를 검색한다 (최근 7일).

    Args:
        query: 검색어. 종목명보다 섹터 어휘가 낫다 ("반도체 주가")
        limit: 최대 건수
    """
    return json.dumps(news_tool.search(query, limit=limit), ensure_ascii=False)


@mcp.tool()
def news_for_holdings(holding_names: str, context: str = "", limit: int = 3) -> str:
    """보유 종목과 관련된 오늘 기사를 찾는다.

    종목명을 섹터 어휘로 번역해 검색한다 — "KODEX 반도체" → "반도체 주가".
    상품 브랜드를 그대로 넣으면 검색이 어긋나기 때문이다.

    **금액·비중은 받지 않는다.** 고객 데이터는 호출부에 남는다.

    Args:
        holding_names: 쉼표로 구분한 종목명. 비중이 큰 순서로 넣을 것
        context: 보조 검색 맥락 — "국내" | "해외" | "환율"
        limit: 최대 건수
    """
    names = [n.strip() for n in holding_names.split(",") if n.strip()]
    holdings = [{"name": n, "weight": 1.0 - i * 0.01} for i, n in enumerate(names)]
    arts = news_tool.for_holdings(holdings, context=context or None, limit=limit)
    return json.dumps(news_tool.as_evidence(arts), ensure_ascii=False)


@mcp.tool()
def sector_query_for(holding_name: str) -> str:
    """종목명을 뉴스 검색용 섹터 어휘로 번역한다. 매핑 확인용."""
    return news_tool.query_for(holding_name)


if __name__ == "__main__":
    print(f"KB-Market MCP · http://{HOST}:{PORT}/mcp", file=sys.stderr)
    print(f"도구 6종 — 시황 3 · 뉴스 3", file=sys.stderr)
    mcp.run(transport="streamable-http")
