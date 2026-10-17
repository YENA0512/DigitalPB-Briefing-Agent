"""
뉴스 Tool — 보유 종목·섹터 관련 기사 조회 (Google News RSS)

## 왜 이 Tool 이 생겼나

기존 브리핑은 "자산이 83만원 줄었어요"까지였다. 고객이 알고 싶은 건
**왜 줄었는지**이고, 그 답은 대개 그날 뉴스에 있다. 시황 지표(숫자)와
리포트(해설)에 **기사(사건)** 를 더해 근거 3층을 만든다.

    market_tool   숫자   코스피 -3.39%
    retriever     해설   반도체 업종에 차익 실현이 번졌다
    news_tool     사건   '반도체 약세' 코스피 6,500 내줘 — MBC뉴스

## 왜 Google News RSS 인가

| 후보 | 결과 (2026-10-12 실측) |
|---|---|
| Google News RSS | 한국어 기사 100건 · 키 불필요 · 당일 기사 |
| Yahoo Finance search | 영문 기사만. `005930.KS` 는 0건 |
| GDELT `sourcelang:korean` | 0건 |
| Naver 뉴스 API | client id/secret 필요 |

대고객 문구에 영문 기사를 링크할 수 없어서 Google News RSS 로 갔다.

## 규칙

- **고객 데이터는 쿼리에 넣지 않는다.** 종목명과 섹터 키워드만 쓴다
- 실패하면 빈 리스트를 반환한다. 뉴스는 **있으면 좋은 것**이고
  없다고 브리핑이 멈추면 안 된다
- 결과는 프로세스 내 캐시. 배치가 41케이스를 돌 때 같은 종목을 반복 조회하지 않는다
"""

import html
import re
import http_util
import urllib.parse
import urllib.request
from datetime import datetime, timezone

RSS = "https://news.google.com/rss/search"
UA = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 12

#  종목명 → 검색어. ETF/펀드 접두어를 걷어내고 섹터 어휘로 바꾼다.
#  종목명을 그대로 넣으면 "KODEX" 같은 상품 브랜드가 검색을 망친다.
SECTOR_HINTS = [
    (("반도체", "소자", "SOX"),              "반도체 주가"),
    (("AI", "인공지능"),                      "AI 반도체 투자"),
    (("국채", "채권", "크레딧"),              "채권 금리"),
    (("MMF", "단기", "유동성"),               "단기금리 자금시장"),
    (("미국", "美", "S&P", "나스닥", "글로벌"), "미국 증시"),
    (("200", "코스피", "KOSPI"),              "코스피"),
    (("코스닥", "KOSDAQ"),                    "코스닥"),
    (("연금", "퇴직"),                        "퇴직연금 투자"),
    (("배당", "고배당"),                      "배당주"),
    (("2차전지", "배터리"),                   "2차전지"),
]

#  진단 결과 → 보조 검색어
CONTEXT_QUERY = {
    "환율": "원달러 환율",
    "국내": "코스피 증시",
    "해외": "미국 증시",
}

_cache: dict[str, list] = {}


def query_for(holding_name: str) -> str:
    """종목명에서 검색어를 뽑는다. 못 찾으면 상품 브랜드를 떼고 쓴다."""
    for keys, q in SECTOR_HINTS:
        if any(k in holding_name for k in keys):
            return q
    cleaned = re.sub(r"(KODEX|TIGER|KBSTAR|ARIRANG|KB|펀드|ETF|포트폴리오)", "",
                     holding_name).strip()
    return cleaned or holding_name


def _parse_rss(xml: str, limit: int) -> list[dict]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S)[:limit * 3]:
        def pick(tag: str) -> str:
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S)
            return html.unescape(m.group(1)).strip() if m else ""

        title, link = pick("title"), pick("link")
        if not title or not link:
            continue
        publisher = pick("source")
        #  Google 은 제목 끝에 " - 발행처" 를 붙인다. 중복이라 떼어낸다
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -(len(publisher) + 3)].strip()
        title = re.sub(r"\s*-\s*[^-]{2,12}$", "", title).strip()

        out.append({"title": title, "url": link, "publisher": publisher or "뉴스",
                    "published": _to_date(pick("pubDate"))})
        if len(out) >= limit:
            break
    return out


def _to_date(raw: str) -> str:
    """RFC822 → YYYY-MM-DD. 실패하면 빈 문자열."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    return ""


def search(query: str, limit: int = 3) -> list[dict]:
    """한국어 기사 검색. 실패해도 예외를 던지지 않는다."""
    key = f"{query}|{limit}"
    if key in _cache:
        return _cache[key]

    url = (f"{RSS}?q={urllib.parse.quote(query)}"
           f"&hl=ko&gl=KR&ceid=KR:ko&when=7d")
    try:
        req = urllib.request.Request(url, headers=UA)
        with http_util.urlopen(req, timeout=TIMEOUT) as resp:
            items = _parse_rss(resp.read().decode("utf-8", "replace"), limit)
    except Exception:                            # noqa: BLE001 — 뉴스는 없어도 된다
        items = []

    _cache[key] = items
    return items


def for_holdings(holdings: list[dict], context: str | None = None,
                 limit: int = 3) -> list[dict]:
    """보유 종목 비중 순으로 관련 기사를 모은다.

    비중이 큰 종목이 변동 설명력도 크다. 상위 2종목 + 시황 1건을 섞는다.
    """
    picked, seen = [], set()
    ranked = sorted(holdings or [], key=lambda h: -h.get("weight", 0))

    for h in ranked[:2]:
        q = query_for(h["name"])
        for art in search(q, limit=2):
            if art["url"] in seen:
                continue
            seen.add(art["url"])
            picked.append({**art, "matched": h["name"], "query": q})
            break                                # 종목당 1건

    if context and len(picked) < limit:
        q = CONTEXT_QUERY.get(context, context)
        for art in search(q, limit=3):
            if art["url"] in seen:
                continue
            seen.add(art["url"])
            picked.append({**art, "matched": context, "query": q})
            if len(picked) >= limit:
                break

    return picked[:limit]


def as_evidence(articles: list[dict]) -> list[dict]:
    """검색·시황과 같은 형식으로 변환해 evidence 에 넣는다.

    doc 을 `뉴스-1` 로 둔다. 짧고 문구에 박기 쉬운 라벨이어야
    LLM 이 출처 태그를 빠뜨리지 않는다.
    """
    out = []
    for i, a in enumerate(articles, 1):
        out.append({
            "doc": f"뉴스-{i}",
            "title": a["title"],
            "text": (f"{a['publisher']} {a['published']} 기사: {a['title']}. "
                     f"({a.get('matched', '')} 관련)"),
            "period": "news",
            "url": a["url"],
            "publisher": a["publisher"],
            "date": a["published"],
            "matched": a.get("matched", ""),
        })
    return out


if __name__ == "__main__":
    holdings = [
        {"name": "KODEX 반도체", "weight": 0.42},
        {"name": "KB글로벌AI펀드", "weight": 0.31},
        {"name": "美 단기국채ETF", "weight": 0.27},
    ]
    print("종목 → 검색어")
    for h in holdings:
        print(f"  {h['name']:<16} → {query_for(h['name'])}")

    print(f"\n보유 종목 관련 기사 ({datetime.now(timezone.utc).astimezone():%Y-%m-%d})")
    arts = for_holdings(holdings, context="국내", limit=3)
    for a in arts:
        print(f"\n  [{a['matched']}] {a['publisher']} · {a['published']}")
        print(f"    {a['title']}")
        print(f"    {a['url'][:84]}…")

    print(f"\nevidence 변환 {len(as_evidence(arts))}건")
