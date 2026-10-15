"""
리포트 검색 — 교육과정 3주차(03_retriever_and_citation) 방식을 그대로 가져왔다.

## 왜 Chroma 가 아니라 InMemoryVectorStore 인가

교육과정 노트북 21개를 실측했을 때 Chroma 사용은 0건이고
`InMemoryVectorStore` 가 25건이었다. 리포트가 8건뿐이라 영속 인덱스가
주는 이점(재인덱싱 회피)보다 비용(.chroma 캐시 꼬임, 멱등성 관리,
`.gitignore` 관리)이 크다. 매 실행마다 8건 임베딩이면 수 초다.

## 왜 출처를 파싱 단계부터 들고 다니는가

03번 노트북 Q1 이 묻는 그 이유다. 나중에 붙이려 하면 어느 청크가 어느
문서에서 왔는지 복원할 수 없다. 여기서는 frontmatter 의 `doc` 을
메타데이터로 심고, 그 값이 그대로 문구의 출처 태그 `[일간-261012]` 가 된다.
grounding 심사가 대조하는 키도 같은 값이다.

## 임베딩 실패 시

`USE_LLM` 과 무관하게 임베딩은 OpenAI 를 쓴다(임베딩은 문구 생성이 아니다).
키가 없거나 네트워크가 막히면 **키워드 검색으로 자동 강등**한다.
evidence 가 비면 generate 가 근거 없이 쓰게 되고 grounding 이 전부 반려된다.
"""

import re
from pathlib import Path

import config

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
#  KB Think 1분 브리핑 실제 글 (kbthink_briefing.sync 가 채운다 · .gitignore 대상)
LIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "reports_live"
CHUNK_MIN = 40          # 이보다 짧은 문단은 독립 청크로 두지 않는다


# ---------------------------------------------------------------- 로딩

def _parse(path: Path) -> dict:
    """frontmatter + 본문. 출처 정보를 여기서 확보한다."""
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {"doc": path.stem, "title": path.stem, "body": raw, "period": "unknown"}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    meta["body"] = m.group(2).strip()
    return meta


def _report_files() -> list[Path]:
    """일간은 KB Think 실제 글을 우선한다. 단 목 리포트보다 오래됐으면 목을 쓴다.

    live 파일은 배치·refresh 때 내려받는다. 네트워크가 막혀 며칠 묵은 live 가
    남아 있으면, 오늘 종가로 만든 목 리포트가 더 정확하다.
    """
    mock = sorted(REPORTS_DIR.glob("*.md"))
    live = sorted(LIVE_DIR.glob("daily-*.md")) if LIVE_DIR.exists() else []
    if not live:
        return mock
    newest = lambda files: max((_parse(f).get("date", "") for f in files), default="")
    mock_daily = [f for f in mock if f.name.startswith("daily-")]
    if newest(live) < newest(mock_daily):
        return mock
    return [f for f in mock if not f.name.startswith("daily-")] + live


def load_documents() -> list[dict]:
    """문단 단위 청킹. 메타데이터에 doc/title/date/period/region 을 심는다."""
    chunks = []
    for path in _report_files():
        meta = _parse(path)
        paras = [p.strip() for p in re.split(r"\n\s*\n", meta["body"]) if p.strip()]
        merged: list[str] = []
        for p in paras:
            if merged and len(p) < CHUNK_MIN:
                merged[-1] += " " + p
            else:
                merged.append(p)
        for i, text in enumerate(merged):
            chunks.append({
                "text": re.sub(r"\*\*", "", text),
                "doc": meta.get("doc", path.stem),
                "title": meta.get("title", path.stem),
                "date": meta.get("date", ""),
                "period": meta.get("period", "unknown"),
                "region": meta.get("region", ""),
                "url": meta.get("url", ""),          # 대고객 출처 칩의 이동 대상
                "summary": meta.get("summary", ""),  # 칩에 노출되는 1~2줄
                "chunk": i,
            })
    return chunks


DOCS = load_documents()


# ---------------------------------------------------------------- 인덱스

_store = None
_mode = "미초기화"


def build_index():
    """모듈 레벨에서 1회만. 세 검색 노드가 병렬로 부르기 때문이다."""
    global _store, _mode
    if _store is not None or _mode == "키워드":
        return _store

    if not config.OPENAI_API_KEY:
        _mode = "키워드"
        return None
    try:
        from langchain_core.documents import Document
        from langchain_core.vectorstores import InMemoryVectorStore
        from langchain_openai import OpenAIEmbeddings

        emb = OpenAIEmbeddings(model=config.OPENAI_EMBED_MODEL,
                               api_key=config.OPENAI_API_KEY)
        docs = [Document(page_content=d["text"],
                         metadata={k: v for k, v in d.items() if k != "text"})
                for d in DOCS]
        _store = InMemoryVectorStore.from_documents(docs, emb)
        _mode = f"벡터({config.OPENAI_EMBED_MODEL})"
    except Exception as exc:                     # noqa: BLE001
        _store, _mode = None, f"키워드(임베딩 실패: {type(exc).__name__})"
    return _store


def mode() -> str:
    return _mode


def reload() -> None:
    """리포트를 새로 받은 뒤 같은 프로세스에서 다시 읽는다 (배치 시작 시)."""
    global DOCS, _store, _mode
    DOCS = load_documents()
    _store, _mode = None, "미초기화"


def daily_source() -> str:
    """지금 일간 근거가 어디서 왔는지 — 로그용."""
    live = any(d["doc"].count("-") >= 2 for d in DOCS if d["period"] == "daily")
    return "KB Think 1분 브리핑" if live else "목 리포트(종가 기반)"


# ---------------------------------------------------------------- 검색

#  일간은 최근 거래일만 본다. 5거래일치를 다 검색하면 키워드가 더 많이 겹친
#  일주일 전 시황이 뽑힌다 — "오늘 브리핑"의 근거는 최근 것이어야 한다.
RECENT_DAILY_DATES = 2


def _recent_dates(period: str) -> set[str] | None:
    if period != "daily":
        return None
    dates = sorted({d["date"] for d in DOCS if d["period"] == "daily"}, reverse=True)
    return set(dates[:RECENT_DAILY_DATES])


def _keyword_search(period: str, query: str, k: int) -> list[dict]:
    """임베딩 없이 돌아가는 폴백. 어절 겹침 점수."""
    terms = [t for t in re.split(r"[\s,·]+", query) if len(t) >= 2]
    recent = _recent_dates(period)
    pool = [d for d in DOCS if d["period"] == period
            and (recent is None or d["date"] in recent)] or DOCS
    scored = []
    for d in pool:
        hit = sum(d["text"].count(t) for t in terms)
        #  질의의 지역(국내/해외)과 리포트 지역이 같으면 가점 — 모닝은 해외, 장마감은 국내다
        if d.get("region") and d["region"] in terms:
            hit += 3
        if recent and d["date"] == max(recent):     # 같은 조건이면 가장 최근 글
            hit += 1
        scored.append((hit, -d["chunk"], d))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [d for _, _, d in scored[:k]]


def search(period: str, query: str, k: int = 2) -> list[dict]:
    """period 로 좁힌 뒤 유사도 검색.

    반환 형식은 market_tool.as_evidence() 와 같다 — evidence 칸이
    두 출처를 같은 모양으로 담아야 grounding 심사가 하나의 규칙으로 돈다.
    """
    store = build_index()
    results: list[dict] = []
    recent = _recent_dates(period)

    if store is not None:
        try:
            hits = store.similarity_search(
                query, k=k, filter=lambda d: d.metadata.get("period") == period
                and (recent is None or d.metadata.get("date") in recent))
            results = [{"text": h.page_content, **h.metadata} for h in hits]
        except Exception:                        # noqa: BLE001
            results = []

    if not results:
        results = _keyword_search(period, query, k)

    # 검색이 0건이어도 빈 리스트를 반환하지 않는다. 그 period 의 첫 청크라도 준다.
    if not results:
        fallback = [d for d in DOCS if d["period"] == period][:1] or DOCS[:1]
        results = fallback

    return [{"doc": r["doc"], "title": r["title"], "text": r["text"],
             "period": r.get("period", period), "date": r.get("date", ""),
             "url": r.get("url", ""), "summary": r.get("summary", "")}
            for r in results]


if __name__ == "__main__":
    print(f"리포트 {len({d['doc'] for d in DOCS})}건 · 청크 {len(DOCS)}개")
    build_index()
    print(f"검색 모드: {mode()}\n")
    for period, q in [("daily", "반도체 급락 코스피"),
                      ("weekly", "국내 해외 수익률 괴리"),
                      ("monthly", "단일 업종 집중도 위험자산 비중")]:
        print(f"[{period}] {q}")
        for r in search(period, q, k=2):
            print(f"   [{r['doc']}] {r['title']}")
            print(f"      {r['text'][:88]}…")
        print()
