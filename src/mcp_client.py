"""
MCP 클라이언트 — `kb-market` 서버의 도구를 그래프에서 부른다.

## 설계 원칙 — MCP 가 죽어도 데모는 돈다

MCP 는 별도 프로세스다. 포트가 막히거나 서버가 안 떠 있으면 그래프 전체가
멈출 수 있다. 발표장에서 그건 치명적이다.

그래서 **MCP 우선, 실패하면 직접 호출**로 떨어진다.

    USE_MCP=true  →  kb-market MCP 서버 호출
                     ↓ 실패 (서버 없음 / 타임아웃 / 도구 오류)
                  →  market_tool · news_tool 을 직접 import 해서 호출

어느 경로로 갔는지는 `last_mode()` 로 확인할 수 있고 로그에도 남는다.
발표에서 "MCP 로 돌고 있습니다"를 보여줄 수 있어야 하기 때문이다.

## 왜 전용 이벤트 루프 스레드인가

MCP 클라이언트는 async 인데 LangGraph 노드는 sync 다. 그리고 Streamlit 은
이미 자기 이벤트 루프를 돌리고 있어서 `asyncio.run()` 이 터진다.
전용 스레드에 루프를 하나 띄워 두고 거기에 코루틴을 던진다.
"""

import asyncio
import json
import threading
from typing import Any

import config

SERVER_URL = "http://127.0.0.1:8765/mcp"
TIMEOUT = 20

_loop: asyncio.AbstractEventLoop | None = None
_tools: dict[str, Any] | None = None
_mode = "미초기화"
_lock = threading.Lock()


# ──────────────────────────────────────────────────────── 전용 루프

def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop and not _loop.is_closed():
        return _loop
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_loop.run_forever, daemon=True,
                     name="mcp-loop").start()
    return _loop


def _run(coro, timeout: float = TIMEOUT):
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop()).result(timeout)


# ──────────────────────────────────────────────────────── 연결

async def _load_tools() -> dict[str, Any]:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    client = MultiServerMCPClient({
        "kb-market": {"transport": "streamable_http", "url": SERVER_URL},
    })
    return {t.name: t for t in await client.get_tools()}


def connect(force: bool = False) -> bool:
    """서버에 붙어 도구 목록을 받는다. 실패해도 예외를 던지지 않는다."""
    global _tools, _mode
    with _lock:
        if _tools is not None and not force:
            return True
        if not config.USE_MCP:
            _mode = "직접 호출 (USE_MCP=false)"
            return False
        try:
            _tools = _run(_load_tools(), timeout=TIMEOUT)
            _mode = f"MCP ({len(_tools)}종 · {SERVER_URL})"
            return True
        except Exception as exc:                 # noqa: BLE001
            _tools = None
            _mode = f"직접 호출 (MCP 연결 실패: {type(exc).__name__})"
            return False


def available() -> bool:
    return _tools is not None


def mode() -> str:
    return _mode


def call(tool: str, **kwargs) -> Any | None:
    """도구 1회 호출. 실패하면 None 을 돌려주고 호출부가 폴백한다."""
    if _tools is None and not connect():
        return None
    fn = (_tools or {}).get(tool)
    if fn is None:
        return None
    try:
        raw = _run(fn.ainvoke(kwargs), timeout=TIMEOUT)
    except Exception:                            # noqa: BLE001
        return None
    return _unwrap(raw)


def _unwrap(raw: Any) -> Any:
    """MCP 응답을 파이썬 값으로 편다.

    langchain-mcp-adapters 는 도구 결과를 **콘텐츠 블록 리스트**로 돌려준다.

        [{"type": "text", "text": "{...json...}", "id": "lc_..."}]

    문자열 하나로 오는 경우도 있어서 둘 다 받는다. JSON 이 아니면 원문 그대로.
    """
    if isinstance(raw, list):
        texts = [b.get("text", "") for b in raw
                 if isinstance(b, dict) and b.get("type") == "text"]
        if not texts:
            return raw
        raw = texts[0] if len(texts) == 1 else "".join(texts)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


# ──────────────────────────────────────────────────────── 그래프가 쓰는 함수
#  각 함수는 (결과, 경로라벨) 을 반환한다. 경로라벨이 로그에 찍힌다.

def market_view() -> tuple[dict, str]:
    out = call("get_market_view")
    if out:
        return out, "MCP"
    import market_tool
    return market_tool.market_view(), "직접"


def market_evidence(symbols: list[str]) -> tuple[list, str]:
    out = call("get_market_evidence", symbols=",".join(symbols))
    if out:
        return out, "MCP"
    import market_tool
    ev = [e for e in market_tool.as_evidence()
          if e["doc"].replace("시장-", "") in symbols]
    return ev, "직접"


def news_for_holdings(holdings: list[dict], context: str,
                      limit: int = 3) -> tuple[list, str]:
    #  ★ 종목명만 넘긴다. 금액·비중은 MCP 서버로 나가지 않는다.
    names = [h["name"] for h in sorted(holdings, key=lambda h: -h.get("weight", 0))]
    out = call("news_for_holdings", holding_names=",".join(names),
               context=context, limit=limit)
    if out is not None:
        return out, "MCP"
    import news_tool
    arts = news_tool.for_holdings(holdings, context=context, limit=limit)
    return news_tool.as_evidence(arts), "직접"


if __name__ == "__main__":
    print("MCP 연결 시도:", SERVER_URL)
    ok = connect()
    print("  →", mode())
    if not ok:
        print("  서버를 먼저 띄우세요:  ./run_local.sh mcp")
    print()
    v, how = market_view()
    print(f"[{how}] 단기 전망 — 국내 {v['국내']['outlook']}"
          f"({v['국내']['change_1d']:+.2f}%) · 해외 {v['해외']['outlook']}"
          f"({v['해외']['change_1d']:+.2f}%)")
    ev, how = market_evidence(["^KS11", "USDKRW=X"])
    print(f"[{how}] 시황 근거 {len(ev)}건 — {ev[0]['title'] if ev else '-'}")
    arts, how = news_for_holdings(
        [{"name": "KODEX 반도체", "weight": .42},
         {"name": "KB글로벌AI펀드", "weight": .31}], "국내", 2)
    print(f"[{how}] 뉴스 {len(arts)}건")
    for a in arts:
        print(f"    [{a.get('matched','')}] {a['title'][:52]}")
