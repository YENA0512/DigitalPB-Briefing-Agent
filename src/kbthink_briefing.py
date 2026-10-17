"""
KB Think '1분 브리핑' 수집 — 일간 시황 근거를 실제 리포트로 쓴다.

## 왜 필요한가

일간 리포트가 목데이터일 때는 본문 숫자가 실제 시장과 어긋났다
(report_builder 로 숫자는 맞췄지만 "왜 움직였나"는 쓸 수 없었다).
KB Think 1분 브리핑은 KB증권 리서치가 매 거래일 두 번 올린다.

    https://kbthink.com/investment/today-pick/{yymm}/{yymmdd}-1.html   모닝코멘트 (글로벌)
    https://kbthink.com/investment/today-pick/{yymm}/{yymmdd}-2.html   장마감코멘트 (국내)

수급·업종·이슈처럼 시세에서 계산할 수 없는 **해설**이 들어 있고,
고객에게 보여줄 출처 링크도 실제 글이 된다.

## 규칙

- **배치에서만 부른다.** 고객 요청 경로(Runtime)에는 네트워크 호출이 없다
- **본문은 저장소에 올리지 않는다.** `data/reports_live/` 는 .gitignore 대상이다.
  KB증권 리서치 저작물이므로 공개 저장소에는 링크만 남는다
- 본문 중 **코멘트 문단만** 가져온다 (차트·순매수 표·캘린더·면책 문구 제외)
- 실패해도 예외를 던지지 않는다. 기존 파일을 그대로 두고 메시지만 돌려준다.
  retriever 는 live 리포트가 목 리포트보다 오래되면 목 리포트를 쓴다

    python src/kbthink_briefing.py            # 최근 글 수집
    python src/kbthink_briefing.py --dry-run  # 무엇을 가져오는지만 출력
"""

import argparse
import html
import re
import time
import http_util
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://kbthink.com"
LIST_URL = BASE + "/investment/today-pick.html?pageNo={page}&sort=recent"
LIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "reports_live"
UA = {"User-Agent": "Mozilla/5.0 (DigitalPB-Briefing-Agent; batch)"}
TIMEOUT = 15
N_ARTICLES = 10            # 최근 5거래일 × 2건
PAUSE = 0.5                # 요청 사이 간격 — 사이트에 부담을 주지 않는다

#  섹션 제목 / 항목 클래스. 모닝은 briefing-main-trend, 장마감은 closing-main-comment
_SECTION = re.compile(
    r'<h2 class="(?:briefing-main-trend|closing-main-comment)__title"[^>]*>(.*?)</h2>'
    r'(.*?)(?=<h2 |<p class="common-compliance|$)', re.S)
_ITEM = re.compile(
    r'<li class="(?:briefing-main-trend|closing-main-comment)__list__item"[^>]*>(.*?)</li>', re.S)
_ARTICLE = re.compile(r'href="(/investment/today-pick/(\d{4})/(\d{6})-(\d)\.html)"')


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with http_util.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _text(fragment: str) -> str:
    #  종목 등락 표기(<span class="…__stock">)는 괄호로 붙인다 — 안 그러면 문장에 들러붙는다
    t = re.sub(r'<span class="[^"]*__stock"[^>]*>(.*?)</span>', r" (\1)", fragment, flags=re.S)
    t = re.sub(r"<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def list_articles(n: int = N_ARTICLES) -> list[tuple[str, str, int]]:
    """최근 글 (경로, yymmdd, 1|2) — 최신순."""
    found: dict[str, tuple[str, str, int]] = {}
    for page in (1, 2):
        for m in _ARTICLE.finditer(_get(LIST_URL.format(page=page))):
            found[m.group(1)] = (m.group(1), m.group(3), int(m.group(4)))
        if len(found) >= n:
            break
        time.sleep(PAUSE)
    return sorted(found.values(), key=lambda a: (a[1], a[2]), reverse=True)[:n]


def parse_article(page: str, path: str, ymd: str, no: int) -> dict | None:
    title = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    title = html.unescape(title.group(1)).split(" | ")[0].strip() if title else path
    sections = []
    for m in _SECTION.finditer(page):
        items = [_text(i) for i in _ITEM.findall(m.group(2))]
        items = [i for i in items if i]
        if items:
            sections.append((_text(m.group(1)), items))
    if not sections:
        return None

    credit = re.search(r"\(출처:\s*([^)]+)\)", page)
    morning = "briefing-main" in page
    d = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
    return {
        "doc": f"일간-{ymd}-{no}",
        "title": title,
        "date": d.isoformat(),
        "region": "해외" if morning else "국내",
        "kind": "모닝코멘트" if morning else "장마감코멘트",
        "url": BASE + path,
        "summary": sections[0][1][0][:90],
        "credit": credit.group(1).strip() if credit else "KB증권 리서치본부",
        "sections": sections,
    }


def to_markdown(a: dict) -> str:
    """retriever 가 읽는 형식. 섹션 하나가 청크 하나가 된다."""
    fm = "\n".join([
        "---",
        f"doc: {a['doc']}", f"title: {a['title']}", f"date: {a['date']}",
        "period: daily", f"region: {a['region']}", f"url: {a['url']}",
        f"summary: {a['summary']}",
        f"source: KB Think 1분 브리핑 · {a['kind']} ({a['credit']})",
        "---", ""])
    body = "\n\n".join(f"[{name}] " + " ".join(i if i.endswith(".") else i + "." for i in items)
                       for name, items in a["sections"])
    return fm + "\n" + body + "\n"


def sync(n: int = N_ARTICLES, dry_run: bool = False) -> tuple[int, str]:
    """최근 글을 내려받아 data/reports_live/ 를 교체한다. 실패해도 예외 없음."""
    try:
        articles = []
        for path, ymd, no in list_articles(n):
            time.sleep(PAUSE)
            a = parse_article(_get(BASE + path), path, ymd, no)
            if a:
                articles.append(a)
        if not articles:
            return 0, "KB Think 1분 브리핑을 찾지 못했습니다 — 기존 파일 유지"
    except Exception as exc:                     # noqa: BLE001 — 배치는 멈추지 않는다
        return 0, f"KB Think 수집 실패({type(exc).__name__}: {str(exc)[:80]}) — 기존 파일 유지"

    if dry_run:
        for a in articles:
            print(f"   [{a['doc']}] {a['kind']} · {a['title']} · 섹션 {len(a['sections'])}")
        return len(articles), "dry-run"

    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    keep = set()
    for a in articles:
        name = f"daily-{a['doc'].split('-', 1)[1]}.md"
        (LIVE_DIR / name).write_text(to_markdown(a), encoding="utf-8")
        keep.add(name)
    for f in LIVE_DIR.glob("*.md"):
        if f.name not in keep:
            f.unlink()
    latest = max(a["date"] for a in articles)
    return len(articles), f"KB Think 1분 브리핑 {len(articles)}건 (최신 {latest})"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="KB Think 1분 브리핑 수집")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    n, msg = sync(dry_run=args.dry_run)
    print(f"   {msg}")
