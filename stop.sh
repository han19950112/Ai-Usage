#!/usr/bin/env bash
# Agent Cockpit 停止脚本

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/server.pid"

STOPPED=false

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "✅ Agent Cockpit (PID: $PID) 已安全停止"
        STOPPED=true
    else
        rm -f "$PID_FILE"
    fi
fi

# 备用清理：仅检查监听 5999 端口的服务端进程（避免误杀浏览器等客户端连接）
PORT_PIDS=$(lsof -tiTCP:5999 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$PORT_PIDS" ]; then
    kill $PORT_PIDS 2>/dev/null || true
    echo "✅ 监听端口 5999 的后台服务进程已清理"
    STOPPED=true
fi

if [ "$STOPPED" = false ]; then
    echo "ℹ️  未检测到正在运行的 Agent Cockpit 服务"
fi
