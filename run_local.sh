#!/usr/bin/env bash
# 로컬 실행 헬퍼 — 시스템 python3 가 3.7 이라 venv 를 쓴다.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${ELITE_VENV:-$HOME/.venvs/elite}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "venv 가 없습니다: $VENV"
  echo "만들기:  python3.12 -m venv \"$VENV\" && \"$VENV/bin/pip\" install -r \"$HERE/requirements.txt\""
  exit 1
fi

case "${1:-agent}" in
  agent)   exec "$VENV/bin/python" "$HERE/src/briefing_agent.py" ;;
  config)  exec "$VENV/bin/python" "$HERE/src/config.py" ;;
  market)  exec "$VENV/bin/python" "$HERE/src/market_tool.py" ;;
  search)  exec "$VENV/bin/python" "$HERE/src/retriever.py" ;;
  cases)   exec "$VENV/bin/python" "$HERE/src/case_router.py" ;;
  reducer) exec "$VENV/bin/python" "$HERE/src/reducers.py" ;;
  test)    exec "$VENV/bin/python" "$HERE/tests/test_loop.py" ;;
  news)    exec "$VENV/bin/python" "$HERE/src/news_tool.py" ;;
  sources) exec "$VENV/bin/python" "$HERE/src/sources.py" ;;
  lab)     exec "$VENV/bin/python" "$HERE/lab/pattern_lab.py" ;;
  viewer)  exec "$VENV/bin/python" "$HERE/demo/build_viewer.py" ;;
  app)     exec "$VENV/bin/streamlit" run "$HERE/app/briefing_app.py" ;;
  chips)   exec "$VENV/bin/python" "$HERE/src/followups.py" ;;
  mcp)     exec "$VENV/bin/python" "$HERE/mcp_servers/market_server.py" ;;
  mcptest) exec "$VENV/bin/python" "$HERE/src/mcp_client.py" ;;
  trace)   exec "$VENV/bin/python" "$HERE/src/tracing.py" ;;
  obs)     exec "$VENV/bin/python" "$HERE/src/langfuse_api.py" ;;
  audit)   exec "$VENV/bin/python" "$HERE/src/audit_db.py" ;;
  labels)  exec "$VENV/bin/python" "$HERE/src/case_labels.py" ;;
  meta)    exec "$VENV/bin/python" "$HERE/src/graph_meta.py" ;;
  batch)   shift; exec "$VENV/bin/python" "$HERE/src/run_batch.py" "$@" ;;
  record)  shift; exec bash "$HERE/demo/record_cli.sh" "$@" ;;
  *) echo "사용법: ./run_local.sh [mcp|app|agent|config|market|news|search|sources|chips|mcptest|batch|record|trace|obs|audit|labels|meta|cases|reducer|test|lab|viewer]"; exit 1 ;;
esac
