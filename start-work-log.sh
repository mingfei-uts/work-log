#!/bin/bash
# ============================================================
#  Work Log — 一键启动
#  日志 API (19878) + HTML 空间 (7820) + 静态页 (8123) + 浏览器
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
API_PORT="${WORK_LOG_PORT:-19878}"
SPACE_PORT=7820
WEB_PORT=8123

start_if_down () {  # $1=port  $2=name  $3=start-cmd
  if curl -s "http://127.0.0.1:$1/" >/dev/null 2>&1 || curl -s "http://127.0.0.1:$1/ping" >/dev/null 2>&1; then
    echo "  $2 已在运行 (:$1)"
  else
    echo "  启动 $2 (:$1)..."
    eval "$3" >/dev/null 2>&1 &
  fi
}

echo "Work Log 启动中…"

# 1) 日志 API 服务器
pkill -f "work-log-server.py" 2>/dev/null; sleep 0.4
echo "  启动 日志API (:$API_PORT)..."
PYTHONUNBUFFERED=1 python3 "$SCRIPT_DIR/work-log-server.py" --port "$API_PORT" >/tmp/wl-server.log 2>&1 &

# 2) HTML 空间 (htmlspace) — 可选, 找子目录或同级目录的 htmlspace
HTMLSPACE=""
for cand in "$SCRIPT_DIR/htmlspace/htmlspace.py" "$SCRIPT_DIR/../htmlspace/htmlspace.py"; do
  [ -f "$cand" ] && { HTMLSPACE="$cand"; break; }
done
if [ -n "$HTMLSPACE" ]; then
  start_if_down "$SPACE_PORT" "HTML空间" "python3 '$HTMLSPACE' --port $SPACE_PORT"
else
  echo "  HTML空间 未安装 (可选, 跳过)"
fi

# 3) 静态页服务 (serve 日志 HTML, 让 iframe + fetch 走 http)
start_if_down "$WEB_PORT" "静态页" "cd '$SCRIPT_DIR' && python3 -m http.server $WEB_PORT --bind 127.0.0.1"

# 等待 API ready
echo -n "  等待服务就绪"
for i in {1..20}; do
  curl -s "http://127.0.0.1:$API_PORT/ping" >/dev/null 2>&1 && { echo " ✓"; break; }
  echo -n "."; sleep 0.3
done

sleep 0.5
open "http://127.0.0.1:$WEB_PORT/daily-work-log.html"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  日志:      http://127.0.0.1:$WEB_PORT/daily-work-log.html"
echo "  日志 API:  http://127.0.0.1:$API_PORT"
echo "  HTML空间:  http://127.0.0.1:$SPACE_PORT"
echo "  停止:      pkill -f work-log-server; pkill -f htmlspace; pkill -f 'http.server $WEB_PORT'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
