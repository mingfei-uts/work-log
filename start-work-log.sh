#!/bin/bash
# ============================================================
#  Work Log — 一键启动
#  启动本地服务器 + 打开浏览器
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_PID_FILE="/tmp/work-log-server.pid"
PORT="${WORK_LOG_PORT:-19878}"

# Kill existing server if running
if [ -f "$SERVER_PID_FILE" ]; then
    OLD_PID=$(cat "$SERVER_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing server (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$SERVER_PID_FILE"
fi

echo "Starting Work Log Server on port $PORT..."
python3 "$SCRIPT_DIR/work-log-server.py" --port "$PORT" &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

# Wait for server to be ready
echo -n "Waiting for server"
for i in {1..20}; do
    if curl -s "http://127.0.0.1:$PORT/ping" > /dev/null 2>&1; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 0.3
done

# Open browser
HTML_FILE="$SCRIPT_DIR/daily-work-log.html"
if [ -f "$HTML_FILE" ]; then
    open "$HTML_FILE"
    echo "Browser opened."
else
    echo "⚠  HTML file not found: $HTML_FILE"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Server:  http://localhost:$PORT"
echo "  PID:     $SERVER_PID"
echo "  Stop:    kill $SERVER_PID"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
