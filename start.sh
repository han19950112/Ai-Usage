#!/usr/bin/env bash
# Agent Cockpit 启动脚本
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/server.pid"
LOG_FILE="$DIR/server.log"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  Agent Cockpit 已经在运行中 (PID: $PID)"
        echo "👉 访问地址: http://localhost:5999"
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# 检查 Python 3
if ! command -v python3 > /dev/null 2>&1; then
    echo "❌ 未检测到 Python 3，请先安装 Python 3"
    exit 1
fi

# 初始化 config.json (若不存在)
if [ ! -f "$DIR/config.json" ]; then
    cp "$DIR/config.example.json" "$DIR/config.json"
    echo "ℹ️  已根据模板自动生成 config.json"
fi

if [ "$1" == "--daemon" ] || [ "$1" == "-d" ]; then
    nohup python3 "$DIR/server.py" > "$LOG_FILE" 2>&1 &
    NEW_PID=$!
    echo "$NEW_PID" > "$PID_FILE"
    echo "=============================================="
    echo "🚀 Agent Cockpit 已在后台成功启动 (PID: $NEW_PID)"
    echo "👉 浏览器访问: http://localhost:5999"
    echo "📄 运行日志文件: $LOG_FILE"
    echo "🛑 停止命令:     ./stop.sh"
    echo "=============================================="
else
    echo "=============================================="
    echo "🚀 正在前台启动 Agent Cockpit (Ctrl+C 退出)..."
    echo "💡 如需后台静默常驻运行，请执行: ./start.sh --daemon"
    echo "=============================================="
    exec python3 "$DIR/server.py"
fi
