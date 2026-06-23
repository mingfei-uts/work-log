#!/bin/bash
# ============================================================
#  Work Log — 本地一键启动
#  日志服务器 (19878, 同时托管网页) + HTML 空间 (7820, 可选) + 浏览器
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
API_PORT="${WORK_LOG_PORT:-19878}"
SPACE_PORT=7820

echo "Work Log 启动中…"

# 1) 日志服务器 (现在自身托管 daily-work-log.html, 无需单独静态服务)
pkill -f "work-log-server.py" 2>/dev/null; sleep 0.4
echo "  启动 日志服务器 (:$API_PORT)..."
PYTHONUNBUFFERED=1 python3 "$SCRIPT_DIR/work-log-server.py" --port "$API_PORT" >/tmp/wl-server.log 2>&1 &

# 2) HTML 空间 (htmlspace) — 可选, 找子目录或同级目录
HTMLSPACE=""
for cand in "$SCRIPT_DIR/htmlspace/htmlspace.py" "$SCRIPT_DIR/../htmlspace/htmlspace.py"; do
  [ -f "$cand" ] && { HTMLSPACE="$cand"; break; }
done
if [ -n "$HTMLSPACE" ]; then
  if curl -s "http://127.0.0.1:$SPACE_PORT/" >/dev/null 2>&1; then
    echo "  HTML空间 已在运行 (:$SPACE_PORT)"
  else
    echo "  启动 HTML空间 (:$SPACE_PORT)..."
    python3 "$HTMLSPACE" --port "$SPACE_PORT" >/dev/null 2>&1 &
  fi
else
  echo "  HTML空间 未安装 (可选, 跳过)"
fi

# 等 API ready
echo -n "  等待服务就绪"
for i in {1..20}; do
  curl -s "http://127.0.0.1:$API_PORT/ping" >/dev/null 2>&1 && { echo " ✓"; break; }
  echo -n "."; sleep 0.3
done

sleep 0.4
open "http://127.0.0.1:$API_PORT/daily-work-log.html"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  日志:      http://127.0.0.1:$API_PORT/daily-work-log.html"
echo "  HTML空间:  http://127.0.0.1:$SPACE_PORT"
echo "  停止:      pkill -f work-log-server; pkill -f htmlspace"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
