#!/usr/bin/env bash
# Agent Cockpit 运行状态查询脚本

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/server.pid"

echo "=== Agent Cockpit 运行状态 ==="
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "🟢 服务状态: 运行中 (PID: $PID)"
        echo "🌐 本地面板: http://localhost:5999"
        exit 0
    fi
fi

PORT_PIDS=$(lsof -ti:5999 2>/dev/null || true)
if [ -n "$PORT_PIDS" ]; then
    echo "🟢 服务状态: 运行中 (端口 5999, PID: $PORT_PIDS)"
    echo "🌐 本地面板: http://localhost:5999"
    exit 0
fi

echo "⚪ 服务状态: 已停止"
echo "👉 启动方式: ./start.sh --daemon"
