"""
시황 지표 Tool — 실시간 지수·환율 조회

## 왜 FMP 가 아닌가

FMP(Financial Modeling Prep) 무료 등급으로는 이 프로젝트가 필요한 세 가지가
전부 막힌다. 2026-10-12 실측:

    AAPL · SPY · EURUSD            200 OK
    USDKRW · QQQ · SOXX · EWY      402 Premium
    ^KS11(코스피) · /forex          404
    /api/v3/*                      2025-08-31 종료 (레거시)

카드 4종이 쓰는 국내 시황 · 환율 · 반도체가 다 비어 있어서 쓸 수 없었다.
키가 없고 코스피·원달러·반도체지수가 모두 되는 Yahoo Finance chart 로 갔다.

## 규칙

- **고객 데이터는 다루지 않는다.** 공개 시장 지표만 조회한다
- 실패하면 예외를 던지지 않고 `stale=True` 로 **마지막 성공값 또는 기본값**을
  반환한다. 발표장에서 네트워크가 막혀도 그래프가 끝까지 돌아야 한다
- 호출 결과는 프로세스 내에서 캐시한다. 배치가 41케이스를 돌 때
  같은 지표를 41번 부를 이유가 없다
"""

import json
import http_util
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
UA = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 12

# 심볼 → (한글명, 구분). 구분이 국내/해외 전망 선택의 근거가 된다.
SYMBOLS = {
    "^KS11":    ("코스피", "국내"),
    "^KQ11":    ("코스닥", "국내"),
    "USDKRW=X": ("원/달러 환율", "환율"),
    "^SOX":     ("미국 반도체지수", "해외"),
    "^GSPC":    ("S&P500", "해외"),
    "^IXIC":    ("나스닥", "해외"),
    "^VIX":     ("VIX 변동성지수", "해외"),
}

# 네트워크가 막혔을 때 쓰는 최후값. 데모가 죽지 않게만 하는 용도다.
_DEFAULTS = {
    "^KS11": 6393.95, "^KQ11": 849.37, "USDKRW=X": 1333.40, "^SOX": 12572.42,
    "^GSPC": 7811.54, "^IXIC": 27366.17, "^VIX": 14.84,
}

#  시장지표 출처 칩의 이동 대상. 투자홈 시장지표 화면으로 보낸다.
MARKET_LINK = "https://kbthink.com/investment/market-indicator.html"

_cache: dict[str, dict] = {}


def _fetch(symbol: str, rng: str = "1mo") -> dict:
    url = f"{BASE}{urllib.parse.quote(symbol)}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers=UA)
    with http_util.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def quote(symbol: str, use_cache: bool = True) -> dict:
    """지표 1종 조회. 실패해도 죽지 않는다."""
    if use_cache and symbol in _cache:
        return _cache[symbol]

    name, kind = SYMBOLS.get(symbol, (symbol, "기타"))
    try:
        result = _fetch(symbol)["chart"]["result"][0]
        meta = result["meta"]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        price = meta.get("regularMarketPrice") or closes[-1]

        out = {
            "symbol": symbol, "name": name, "kind": kind,
            "price": round(price, 2),
            "change_1d": round((price - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else 0.0,
            "change_1m": round((price - closes[0]) / closes[0] * 100, 2) if closes else 0.0,
            "currency": meta.get("currency"),
            "asof": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"),
            "stale": False,
        }
    except Exception as exc:                     # noqa: BLE001 — 어떤 실패든 데모는 계속된다
        out = {
            "symbol": symbol, "name": name, "kind": kind,
            "price": _DEFAULTS.get(symbol, 0.0),
            "change_1d": 0.0, "change_1m": 0.0, "currency": None,
            "asof": None, "stale": True, "error": f"{type(exc).__name__}",
        }

    _cache[symbol] = out
    return out


def snapshot(symbols: list[str] | None = None) -> dict[str, dict]:
    """여러 지표를 한 번에. 기본은 7종 전부."""
    return {s: quote(s) for s in (symbols or list(SYMBOLS))}


# ---------------------------------------------------------------- 전망 판정 (Rule)

#  LLM 에 맡기지 않는다. 같은 수치면 같은 판정이 나와야 한다.
GOOD, FLAT = 0.5, -0.5


def outlook(change_1d: float) -> str:
    if change_1d >= GOOD:
        return "좋음"
    if change_1d <= FLAT:
        return "나쁨"
    return "보통"


def market_view(snap: dict[str, dict] | None = None) -> dict:
    """41케이스의 `단기시장전망` 축에 넣을 값을 만든다.

    CLAUDE.md 10절 미확정 항목: 국내/해외 중 무엇을 쓸지는 호출부가
    보유자산 지역 비중으로 정한다. 여기서는 양쪽을 다 계산해 둔다.
    """
    snap = snap or snapshot()
    dom = snap["^KS11"]["change_1d"]
    ovs = snap["^GSPC"]["change_1d"]
    return {
        "국내": {"outlook": outlook(dom), "change_1d": dom, "지표": "코스피"},
        "해외": {"outlook": outlook(ovs), "change_1d": ovs, "지표": "S&P500"},
        "환율": snap["USDKRW=X"],
        "stale": any(v["stale"] for v in snap.values()),
    }


def _eun_neun(word: str) -> str:
    """받침 유무로 은/는 을 고른다. evidence 본문이 LLM 입력이라 어색하면 문구에 번진다."""
    last = word.strip()[-1]
    if not ("\uac00" <= last <= "\ud7a3"):
        return "는"
    return "은" if (ord(last) - 0xAC00) % 28 else "는"


def as_evidence(snap: dict[str, dict] | None = None) -> list[dict]:
    """검색 결과와 같은 형식으로 변환해 evidence 에 넣는다.

    doc 을 `시장-<심볼>` 로 둔다. 출처 태그가 `[시장-^KS11]` 로 찍히고
    grounding 심사가 그 문서의 존재와 수치를 대조할 수 있다.
    """
    snap = snap or snapshot()
    out = []
    for sym, v in snap.items():
        if v["kind"] == "기타":
            continue
        sign = "하락" if v["change_1d"] < 0 else ("상승" if v["change_1d"] > 0 else "보합")
        out.append({
            "doc": f"시장-{sym}",
            "title": f"{v['name']} {v['price']:,} ({v['change_1d']:+.2f}%)",
            "text": (f"{v['name']}{_eun_neun(v['name'])} {v['asof'] or '최근'} 기준 {v['price']:,}이며 "
                     f"전일 대비 {abs(v['change_1d']):.2f}% {sign}했다. "
                     f"1개월 변동률은 {v['change_1m']:+.2f}%다."),
            "period": "live",
            "summary": (f"전일 대비 {v['change_1d']:+.2f}%, "
                        f"1개월 {v['change_1m']:+.2f}%. {v['asof'] or ''} 기준"),
            "publisher": "실시간 시세",
            "date": (v["asof"] or "")[:10],
            "url": MARKET_LINK,
            "numbers": {"price": v["price"], "change_1d": v["change_1d"],
                        "change_1m": v["change_1m"]},
            "stale": v["stale"],
        })
    return out


if __name__ == "__main__":
    snap = snapshot()
    print("시황 지표")
    for v in snap.values():
        flag = " ⚠ stale" if v["stale"] else ""
        print(f"  {v['name']:<16} {v['price']:>12,.2f}  전일 {v['change_1d']:+6.2f}%  "
              f"1개월 {v['change_1m']:+6.2f}%{flag}")

    mv = market_view(snap)
    print(f"\n단기시장전망  국내 {mv['국내']['outlook']}({mv['국내']['change_1d']:+.2f}%) · "
          f"해외 {mv['해외']['outlook']}({mv['해외']['change_1d']:+.2f}%)")
    print(f"환율          {mv['환율']['price']:,.2f}원 ({mv['환율']['change_1d']:+.2f}%)")
    print(f"\nevidence 변환 {len(as_evidence(snap))}건 — 첫 건:")
    print("  ", as_evidence(snap)[0]["text"])
