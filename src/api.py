"""
배치 API — n8n 이 호출하는 얇은 HTTP 계층.

## 경계

**n8n 은 오케스트레이션이고 Agent 는 판단이다.**

    n8n 이 하는 것      언제 돌릴지 · 끝나면 누구에게 알릴지 · 실패하면 재시도
    Agent 가 하는 것    무엇을 쓸지 · 통과시킬지 · 폴백할지

이 경계를 흐리면 둘 다 나빠진다. n8n 안에 판단 로직을 넣으면 테스트할 수
없고, Agent 안에 스케줄을 넣으면 운영이 코드 배포에 묶인다.

## ⚠️ 이 API 는 Batch 전용이다

고객 요청 경로가 **아니다.** 금소법상 투자 문구는 사람 책임 하에 노출되어야
하므로 고객 진입 시점에는 승인된 JSON 만 읽는다.
여기에 `/customer/briefing` 같은 엔드포인트를 만들지 말 것.

## 엔드포인트

    GET  /health            살아 있는지 + Tool 경로
    POST /batch/run         배치 실행 → 검수 대기열 적재
    GET  /pending           검수 대기 목록
    POST /approve/{case}    승인 (검수자 이름 필요)
    POST /reject/{case}     반려 (사유 필요)
    GET  /stats             최근 품질 집계 — n8n 이 알림 문구를 만들 때 쓴다

## 실행

    ./run_local.sh api          # 127.0.0.1:8900
    curl localhost:8900/health
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import audit_db      # noqa: E402
import case_labels   # noqa: E402
import case_router   # noqa: E402
import config        # noqa: E402
import mcp_client    # noqa: E402

PENDING = ROOT / "output" / "pending"
APPROVED = ROOT / "output" / "approved"
HOST, PORT = "127.0.0.1", 8900

app = FastAPI(title="디지털PB 브리핑 배치 API",
              description="n8n 이 호출하는 Batch 계층. 고객 요청 경로가 아니다.",
              version="1.0")

#  배치는 오래 걸린다(41건 약 19분). n8n 이 타임아웃 나지 않게
#  백그라운드로 돌리고 상태를 폴링하게 한다.
_job: dict = {"state": "idle", "started": None, "finished": None, "result": None}


# ──────────────────────────────────────────────────────── 스키마

class RunRequest(BaseModel):
    limit: int = Field(0, description="앞 N건만. 0이면 41건 전체")
    cases: str = Field("", description="쉼표로 구분한 CASE ID. 비우면 전체")
    auto_approve: bool = Field(False, description="검수를 건너뛰고 바로 승인")


class Decision(BaseModel):
    by: str = Field(..., description="검수자 이름 — 감사 추적에 남는다")
    reason: str = Field("", description="반려 사유")
    advice: str = Field("", description="수정 후 승인일 때 교체할 문구")


# ──────────────────────────────────────────────────────── 조회

@app.get("/health")
def health() -> dict:
    mcp_client.connect()
    return {
        "ok": True,
        "use_llm": config.USE_LLM,
        "model": config.OPENAI_MODEL if config.USE_LLM else None,
        "tool_path": mcp_client.mode(),
        "cases": len(case_router.CASES),
        "job": _job["state"],
        "at": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/pending")
def pending() -> dict:
    rows = []
    for f in sorted(PENDING.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        #  파일명은 **요청한** 케이스, case_id 는 오늘 시황으로 **판정된** 케이스다.
        #  둘이 다를 수 있다 — 조건을 역산해 만든 목 포트폴리오에
        #  실시간 시황을 적용하면 다른 케이스로 떨어진다.
        rows.append({
            "requested": f.stem,
            "case_id": d.get("case_id", f.stem),
            "label": d.get("case_label") or case_labels.label(f.stem),
            "advice": d.get("advice_display", ""),
            "revision": d.get("revision", 0),
            "fallback": bool(d.get("fallback_used")),
            "review": {k: v.get("passed") for k, v in (d.get("review") or {}).items()},
        })
    return {"count": len(rows), "items": rows}


@app.get("/stats")
def stats(days: int = 7) -> dict:
    """n8n 이 알림 문구를 만들 때 쓴다. 숫자만 돌려준다."""
    s = audit_db.stats()
    daily = audit_db.daily_summary(days)
    today = daily[0] if daily else {}
    return {
        "total": s.get("total", 0),
        "cases": s.get("cases", 0),
        "fallbacks": s.get("fallbacks", 0) or 0,
        "avg_revisions": s.get("avg_rev") or 0,
        "today": {
            "date": today.get("served_date"),
            "count": today.get("n", 0),
            "fallbacks": today.get("fallbacks", 0) or 0,
            "compliance_fail": today.get("comp_fail", 0) or 0,
            "grounding_fail": today.get("gr_fail", 0) or 0,
            "format_fail": today.get("fmt_fail", 0) or 0,
        },
        "pending": len(list(PENDING.glob("*.json"))),
    }


# ──────────────────────────────────────────────────────── 배치

def _run_batch(limit: int, cases: str, auto_approve: bool) -> None:
    import run_batch
    _job.update(state="running", started=datetime.now().isoformat(timespec="seconds"),
                finished=None, result=None)
    try:
        ids = ([c.strip() for c in cases.split(",") if c.strip()]
               or sorted(case_router.CASES, key=lambda c: int(c[4:])))
        if limit:
            ids = ids[:limit]
        stat = run_batch.batch(ids, auto_approve)
        _job.update(state="done", finished=datetime.now().isoformat(timespec="seconds"),
                    result={
                        "total": len(ids),
                        "approved": stat.get("approved", 0),
                        "pending": stat.get("pending", 0),
                        "error": stat.get("error", 0),
                        "fallback": stat.get("fallback", 0),
                        "elapsed_sec": round(stat.get("elapsed", 0), 1),
                        "avg_revisions": round(
                            sum(stat.get("rounds") or [1]) / max(len(stat.get("rounds") or [1]), 1) - 1, 2),
                    })
    except Exception as exc:                     # noqa: BLE001
        _job.update(state="error", finished=datetime.now().isoformat(timespec="seconds"),
                    result={"error": f"{type(exc).__name__}: {exc}"})


@app.post("/batch/run")
def batch_run(req: RunRequest, bg: BackgroundTasks) -> dict:
    """배치를 **백그라운드로** 시작하고 즉시 응답한다.

    41건이 약 19분 걸린다. 동기로 두면 n8n HTTP 노드가 타임아웃 난다.
    n8n 은 `/batch/status` 를 폴링한다.
    """
    if _job["state"] in ("queued", "running"):
        raise HTTPException(409, "이미 실행 중입니다")

    #  ★ 응답 **전에** 상태를 바꾼다. BackgroundTasks 는 응답을 보낸 뒤
    #     실행되므로, 여기서 안 바꾸면 폴링하는 쪽이 아직 "idle" 을 보고
    #     "벌써 끝났다"고 판단한다. n8n 워크플로가 바로 이 함정에 빠진다.
    _job.update(state="queued", started=datetime.now().isoformat(timespec="seconds"),
                finished=None, result=None)
    bg.add_task(_run_batch, req.limit, req.cases, req.auto_approve)
    return {"accepted": True, "state": "queued", "poll": "/batch/status"}


@app.get("/batch/status")
def batch_status() -> dict:
    return dict(_job)


# ──────────────────────────────────────────────────────── 검수

def _resume(case_id: str, cmd: dict) -> dict:
    """체크포인트에서 재개한다.

    ⚠️ 체크포인터가 `InMemorySaver` 라 **배치를 돌린 그 프로세스 안에서만**
    재개할 수 있다. API 를 재시작하면 대기건이 날아간다.
    운영은 `SqliteSaver` 로 바꿔야 한다 — README 한계 절 참고.
    """
    import briefing_agent as ba
    from langgraph.types import Command

    f = PENDING / f"{case_id}.json"
    if not f.exists():
        raise HTTPException(404, f"검수 대기건이 없습니다: {case_id}")

    cfg = {"configurable": {"thread_id": case_id}, "recursion_limit": 60}
    try:
        out = ba.get_app().invoke(Command(resume=cmd), config=cfg)
    except Exception as exc:                     # noqa: BLE001
        raise HTTPException(
            409, f"재개 실패 ({type(exc).__name__}) — InMemorySaver 라 "
                 f"API 를 재시작하면 대기 상태가 사라집니다. 배치를 다시 돌리세요")

    if "card_spec" not in out:
        return {"case_id": case_id, "state": "pending",
                "message": "반려 — 재작성 후 다시 검수 대기"}

    spec = out["card_spec"]
    audit_db.record(spec)
    APPROVED.mkdir(parents=True, exist_ok=True)
    (APPROVED / f"{case_id}.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    f.unlink()
    return {"case_id": case_id, "state": "approved",
            "fallback_used": spec.get("fallback_used"),
            "by": (spec.get("approval") or {}).get("by")}


@app.post("/approve/{case_id}")
def approve(case_id: str, d: Decision) -> dict:
    cmd = {"action": "edit" if d.advice else "approve", "by": d.by}
    if d.advice:
        cmd["advice"] = d.advice
    return _resume(case_id, cmd)


@app.post("/reject/{case_id}")
def reject(case_id: str, d: Decision) -> dict:
    return _resume(case_id, {"action": "reject", "by": d.by,
                             "reason": d.reason or "(사유 없음)"})


if __name__ == "__main__":
    import uvicorn
    print(f"배치 API · http://{HOST}:{PORT}  (문서 /docs)")
    print("⚠️ Batch 전용 — 고객 요청 경로가 아닙니다")
    #  Docker 로 n8n 을 돌리면 컨테이너가 호스트의 127.0.0.1 에 닿지 못한다.
    #  그때는 API_HOST=0.0.0.0 으로 열고 BRIEFING_API 를
    #  http://host.docker.internal:8900 으로 준다.
    uvicorn.run(app, host=os.getenv("API_HOST", HOST),
                port=int(os.getenv("API_PORT", PORT)), log_level="warning")
