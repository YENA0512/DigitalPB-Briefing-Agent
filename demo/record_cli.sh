#!/usr/bin/env bash
# 터미널 데모 — 녹화용. 각 장면 사이에 멈춰서 읽을 시간을 준다.
#
#   ./demo/record_cli.sh          자동 진행 (장면당 PAUSE 초)
#   ./demo/record_cli.sh --manual 엔터로 넘김 (리허설용)
#
# 화면 녹화는 QuickTime > 새로운 화면 기록. 터미널 폰트 16pt 이상 권장.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ELITE_VENV:-$HOME/.venvs/elite}/bin/python"
PAUSE="${PAUSE:-4}"
MANUAL=0; [ "${1:-}" = "--manual" ] && MANUAL=1

B=$'\033[1m'; D=$'\033[2m'; P=$'\033[38;5;99m'; R=$'\033[0m'

scene() {
  echo; echo "${P}${B}━━━ $1 ${R}"; echo "${D}$2${R}"; echo
}
hold() { if [ "$MANUAL" = 1 ]; then read -rp "$(printf '%s[엔터]%s' "$D" "$R")"; else sleep "$PAUSE"; fi; }

clear
cat <<'EOF'
  디지털PB 브리핑 Agent
  ──────────────────────────────────────────────────
  투자홈 MAU 13만 · 브리핑 문구 41건 고정
  케이스당 평균 3,000명이 같은 문장을 반복해서 본다
  문구 수정 → 개발 반영 최소 7일
EOF
hold

scene "① Feedback Loop 이 왜 안 됐나" \
      "fan-in 때문에 reducer 가 필요한데, operator.add 로는 그 칸을 비울 수 없다"
"$PY" "$HERE/src/reducers.py"
hold

scene "② 41케이스 판정 — 전 조합 커버리지" \
      "288 조합을 전부 돌려 41건에 빠짐없이 도달하는지 확인한다"
"$PY" "$HERE/src/case_router.py" 2>&1 | head -6
hold

scene "③ Tool 을 MCP 서버로 분리" \
      "다른 팀 Agent 도 같은 시세 정의를 쓰게 된다"
"$PY" "$HERE/src/mcp_client.py" 2>&1 | tail -8
hold

scene "④ 루프 회귀 테스트 7종" \
      "reducer 회귀 · 회차 격리 · 금지어 복구 · 3회 폴백 · 면제 · HITL 3갈래"
USE_LLM=false "$PY" "$HERE/tests/test_loop.py" 2>&1 | tail -11
hold

scene "⑤ 배치 — 41케이스" \
      "매일 장 마감 후 돌린다. 검수 단위는 고객이 아니라 케이스다"
USE_LLM=false "$PY" "$HERE/src/run_batch.py" --auto-approve --limit 8 2>&1 | tail -12
hold

scene "⑥ 생성 결과" \
      "같은 고객에게 현재 방식은 한 줄, Agent 는 근거와 함께"
ROOT="$HERE" "$PY" - <<'EOF'
import json, glob, os
#  절대경로를 박으면 폴더 이름이 바뀔 때 깨진다. 스크립트 위치에서 찾는다.
f = sorted(glob.glob(os.path.join(os.environ["ROOT"], "output/approved/*.json")))
import sys
sys.path.insert(0, os.path.join(os.environ["ROOT"], "src"))
import case_router
for p in f:
    d = json.load(open(p, encoding="utf-8"))
    if d.get("sources"):
        #  AS-IS 대조 — 41케이스 원본 문구를 슬롯 치환해 보여준다
        orig = d.get("original_copy")
        if not orig:
            m = d.get("metrics", {})
            orig = case_router.render(d["case_id"], {
                "days": d.get("diagnosis", {}).get("days_since", 5),
                "diffAmt": f"{abs(m.get('delta', 0)):,}",
                "curAmt": f"{m.get('total', 0):,}"})["advice"]
        print("  [AS-IS]", orig)
        print()
        print("  [Agent]", d["advice_display"])
        print()
        for s in d["sources"]:
            print(f"    {s['marker']} [{s['kind']}] {s['title'][:52]}")
            print(f"       {s['publisher']} · {s.get('date','')}  →  {s['url'][:60]}")
        break
EOF
echo
echo "${D}  화면 데모는 http://localhost:8501 (./run_local.sh app)${R}"
