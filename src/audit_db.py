"""
감사 로그 DB — 누가 언제 무엇을 승인했는가 (SQLite)

## 왜 DB 가 필요한가

HITL 을 붙이면서 `approval` 에 승인자·시각을 담았지만, 그건 JSON 파일
하나에만 남는다. 재생성하면 사라진다.

금소법 영역에서 **"누가 언제 어떤 문구를 승인해 고객에게 내보냈는가"** 는
사후에 반드시 조회할 수 있어야 한다. 파일이 아니라 조회 가능한 저장소가
있어야 하는 유일한 이유다.

    "작년 10월 12일에 반도체 급락 케이스로 나간 문구가 뭐였죠?"
    "그거 누가 승인했죠?"
    "그 주에 폴백으로 나간 건이 몇 건이죠?"

## 무엇을 넣고 무엇을 안 넣는가

- 넣는다 — 케이스 ID · 문구 · 심사 결과 · 재작성 횟수 · 승인자 · 시각 · 근거 doc
- **넣지 않는다 — 고객 식별자, 보유 금액.** 검수 단위가 케이스라서 필요 없다.
  고객 단위로 쌓으면 13만 행이 매일 생기고 개인정보가 된다

## 교육과정 연결

`w5_nb02a/b` (DB 접근 MCP) 와 같은 구조다. 아래 `kb-audit` MCP 도구로도
노출돼 있어서, 다른 Agent 가 "지난주 폴백 건수"를 물어볼 수 있다.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "output" / "audit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT    NOT NULL,
    case_label   TEXT,                   -- CASE19 가 무슨 상황인지
    served_date  TEXT    NOT NULL,          -- 이 문구가 나갈 영업일
    card_type    TEXT,
    advice       TEXT    NOT NULL,          -- 고객에게 나간 문장 (태그 제외)
    advice_tagged TEXT,                     -- 출처 태그 포함 (대조용)
    change_type  TEXT,
    gap_type     TEXT,
    revisions    INTEGER DEFAULT 0,
    fallback     INTEGER DEFAULT 0,
    compliance   INTEGER,
    grounding    INTEGER,
    format_ok    INTEGER,
    evidence     TEXT,                      -- JSON 배열 — 인용한 doc
    approver     TEXT,
    approval_act TEXT,                      -- approve | edit | reject | auto
    approved_at  TEXT,
    model        TEXT,
    llm_calls    INTEGER DEFAULT 0,
    trace_url    TEXT,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_case ON approvals(case_id);
CREATE INDEX IF NOT EXISTS ix_date ON approvals(served_date);
"""


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def record(spec: dict, served_date: str | None = None) -> int:
    """확정된 card_spec 1건을 남긴다. 실패해도 예외를 던지지 않는다."""
    rv = spec.get("review", {}) or {}
    ap = spec.get("approval", {}) or {}
    dg = spec.get("diagnosis", {}) or {}
    row = (
        spec.get("case_id", "?"),
        spec.get("case_label", ""),
        served_date or datetime.now().strftime("%Y-%m-%d"),
        spec.get("card_type"),
        spec.get("advice_plain", ""),
        spec.get("advice", ""),
        dg.get("change_type"), dg.get("gap_type"),
        int(spec.get("review_rounds", 1)) - 1,
        int(bool(spec.get("fallback_used"))),
        int(bool(rv.get("compliance", {}).get("passed"))),
        int(bool(rv.get("grounding", {}).get("passed"))),
        int(bool(rv.get("format", {}).get("passed"))),
        json.dumps([e.get("doc") for e in spec.get("sources", [])
                    if isinstance(e, dict)], ensure_ascii=False),
        ap.get("by"), ap.get("action"), ap.get("at"),
        (spec.get("llm") or {}).get("model"),
        int((spec.get("llm") or {}).get("calls", 0)),
        spec.get("trace_url"),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    try:
        with conn() as c:
            cur = c.execute(
                "INSERT INTO approvals (case_id, case_label, served_date, card_type, advice,"
                " advice_tagged, change_type, gap_type, revisions, fallback,"
                " compliance, grounding, format_ok, evidence, approver,"
                " approval_act, approved_at, model, llm_calls, trace_url, created_at)"
                " VALUES (" + ",".join("?" * 21) + ")", row)
            return cur.lastrowid or 0
    except Exception:                            # noqa: BLE001
        return 0


# ──────────────────────────────────────────────────────── 조회

def history(case_id: str, limit: int = 10) -> list[dict]:
    """한 케이스가 날짜별로 어떻게 달라졌는지. **같은 케이스인데 문구가
    매일 다르다**는 것이 이 프로젝트의 증명이다."""
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT served_date, case_label, advice, revisions, fallback, approver, approval_act"
            " FROM approvals WHERE case_id=? ORDER BY id DESC LIMIT ?",
            (case_id, limit))]


def daily_summary(days: int = 7) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT served_date, COUNT(*) n, SUM(fallback) fallbacks,"
            " ROUND(AVG(revisions),2) avg_rev, SUM(llm_calls) llm,"
            " SUM(compliance=0) comp_fail, SUM(grounding=0) gr_fail,"
            " SUM(format_ok=0) fmt_fail"
            " FROM approvals WHERE served_date>=? GROUP BY served_date"
            " ORDER BY served_date DESC", (since,))]


def search(keyword: str, limit: int = 10) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT case_id, case_label, served_date, advice, approver FROM approvals"
            " WHERE advice LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{keyword}%", limit))]


def stats() -> dict:
    with conn() as c:
        r = c.execute(
            "SELECT COUNT(*) total, COUNT(DISTINCT case_id) cases,"
            " COUNT(DISTINCT served_date) days, SUM(fallback) fallbacks,"
            " ROUND(AVG(revisions),2) avg_rev, SUM(llm_calls) llm"
            " FROM approvals").fetchone()
        return dict(r) if r else {}


if __name__ == "__main__":
    s = stats()
    print(f"감사 로그 — {DB_PATH}")
    print(f"  총 {s.get('total',0)}건 · 케이스 {s.get('cases',0)}종 · "
          f"{s.get('days',0)}일치 · 폴백 {s.get('fallbacks',0)} · "
          f"평균 재작성 {s.get('avg_rev',0)} · LLM {s.get('llm',0)}회")
    print("\n일자별")
    for r in daily_summary(14):
        print(f"  {r['served_date']}  {r['n']:>3}건 · 폴백 {r['fallbacks']} · "
              f"평균 재작성 {r['avg_rev']} · 심사반려 "
              f"(컴 {r['comp_fail']} / 근거 {r['gr_fail']} / 형식 {r['fmt_fail']})")
    h = history("CASE19", 5)
    if h:
        print("\nCASE19 이력 — 같은 케이스인데 날짜마다 문구가 다르다")
        for r in h:
            print(f"  {r['served_date']} · 재작성 {r['revisions']} · "
                  f"{r['approver'] or '-'}")
            print(f"    {r['advice'][:76]}")
