"""
Langfuse 공개 API 읽기 — 브라우저 로그인 없이 지표를 가져온다.

## 왜 필요한가

Langfuse 대시보드는 **브라우저 세션이 키를 발급한 계정과 같아야** 열린다.
다른 계정으로 로그인돼 있으면 `Project Not Found` 가 뜬다.
발표장에서 로그인 상태에 데모가 걸리면 안 된다.

API 키만으로 같은 데이터를 읽어 앱 안에서 보여준다. 대시보드는 깊이 파고들 때
쓰고, 발표에서 보여줄 숫자는 앱이 직접 가져온다.

조회만 한다 — 기록은 `tracing.py` 가 SDK 로 한다.
"""

import base64
import json
import statistics
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

import config

TIMEOUT = 20

#  심사 품질 점수. 이름과 "올라가면 좋은가"를 같이 둔다.
SCORE_META = {
    "compliance_pass": ("컴플라이언스 통과", True),
    "grounding_pass": ("근거 결속 통과", True),
    "format_pass": ("형식 통과", True),
    "revisions": ("재작성 횟수", False),
    "fallback": ("폴백", False),
    "llm_calls": ("LLM 호출", False),
    "sources": ("인용 출처 수", True),
}


def _auth() -> str:
    raw = f"{config.LANGFUSE_PUBLIC_KEY}:{config.LANGFUSE_SECRET_KEY}"
    return base64.b64encode(raw.encode()).decode()


def _get(path: str) -> dict | None:
    """공개 API GET. 실패하면 None — 관측이 없다고 앱이 멈추면 안 된다."""
    if not config.LANGFUSE_ENABLED:
        return None
    req = urllib.request.Request(f"{config.LANGFUSE_HOST}{path}",
                                 headers={"Authorization": f"Basic {_auth()}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except Exception:                            # noqa: BLE001
        return None


def project() -> dict:
    d = _get("/api/public/projects") or {}
    rows = d.get("data") or []
    return rows[0] if rows else {}


def project_url(path: str = "") -> str:
    p = project()
    return (f"{config.LANGFUSE_HOST}/project/{p['id']}{path}"
            if p.get("id") else config.LANGFUSE_HOST)


def scores(limit: int = 200) -> list[dict]:
    d = _get(f"/api/public/scores?limit={min(limit, 100)}") or {}
    return d.get("data") or []


def traces(limit: int = 50) -> list[dict]:
    d = _get(f"/api/public/traces?limit={min(limit, 100)}") or {}
    return d.get("data") or []


def trace(trace_id: str) -> dict | None:
    return _get(f"/api/public/traces/{urllib.parse.quote(trace_id)}")


# ──────────────────────────────────────────────────────── 집계

def summary(limit: int = 100) -> dict:
    """점수를 이름별로 모아 평균·합계를 낸다. 발표에서 보여줄 숫자다."""
    rows = scores(limit)
    by = defaultdict(list)
    for s in rows:
        try:
            by[s["name"]].append(float(s["value"]))
        except (TypeError, ValueError, KeyError):
            continue

    out = {}
    for name, (label, higher_better) in SCORE_META.items():
        vals = by.get(name, [])
        if not vals:
            continue
        out[name] = {
            "label": label,
            "higher_better": higher_better,
            "n": len(vals),
            "avg": round(statistics.mean(vals), 2),
            "sum": round(sum(vals), 1),
            "pass_rate": round(sum(1 for v in vals if v >= 1) / len(vals) * 100)
            if name.endswith("_pass") else None,
        }
    return {"scored_runs": len(by.get("compliance_pass", [])),
            "total_scores": len(rows), "metrics": out}


def recent_runs(limit: int = 12) -> list[dict]:
    """최근 실행 목록. 이름이 `브리핑 CASE19` 형태인 것만 추린다."""
    out = []
    for t in traces(limit * 3):
        name = t.get("name") or ""
        if not name.startswith("브리핑"):
            continue
        out.append({
            "name": name,
            "id": t.get("id"),
            "at": (t.get("timestamp") or "")[:19].replace("T", " "),
            "observations": len(t.get("observations") or []),
            "scores": len(t.get("scores") or []),
            "latency": round(t.get("latency") or 0, 1),
        })
        if len(out) >= limit:
            break
    return out


def health() -> str:
    if not config.LANGFUSE_ENABLED:
        return "미사용 (키 없음)"
    p = project()
    if not p:
        return "연결 실패 — 키 또는 네트워크 확인"
    org = (p.get("organization") or {}).get("name", "?")
    return f"{p.get('name')} · {org}"


if __name__ == "__main__":
    print("상태:", health())
    print("주소:", project_url("/traces"))
    s = summary()
    print(f"\n집계 — 실행 {s['scored_runs']}건 · 점수 {s['total_scores']}개")
    for name, m in s["metrics"].items():
        extra = f" · 통과율 {m['pass_rate']}%" if m["pass_rate"] is not None else ""
        print(f"  {m['label']:<16} 평균 {m['avg']:>6}  (n={m['n']}){extra}")
    print("\n최근 실행")
    for r in recent_runs(8):
        print(f"  {r['at']}  {r['name']:<20} 관측 {r['observations']:>2}개 · "
              f"점수 {r['scores']}개 · {r['latency']}s")
    counts = Counter(t.get("name", "?") for t in traces(100))
    print("\ntrace 이름 분포:", dict(counts.most_common(5)))
