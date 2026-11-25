#!/usr/bin/env bash
# 一键启动 Antigravity 并开启本地 CDP 端口 (58321)，供 Agent Cockpit 官方权威直连读取真实配额
set -e

PORT="${1:-58321}"

# 检查是否已经带调试端口运行
if ps -axo command | grep -F "Antigravity.app/Contents/MacOS/Antigravity" | grep -q -- "--remote-debugging-port=$PORT"; then
    echo "✅ Antigravity 已在官方配额直连模式运行中 (CDP 端口: $PORT)"
    open -a Antigravity
    exit 0
fi

# 若已在无调试端口模式下运行，提示并优雅重启
if pgrep -f "Antigravity.app/Contents/MacOS/Antigravity" > /dev/null 2>&1; then
    echo "🔄 检测到 Antigravity 未开启 CDP 端口，正在重启为官方直连模式..."
    osascript -e 'tell application "Antigravity" to quit' 2>/dev/null || true
    for _ in {1..15}; do
        if ! pgrep -f "Antigravity.app/Contents/MacOS/Antigravity" > /dev/null 2>&1; then
            break
        fi
        sleep 0.4
    done
fi

echo "🚀 正在启动 Antigravity (CDP 端口: $PORT)..."
open -a Antigravity --args --remote-debugging-port="$PORT"
echo "✅ 已启动！最多 30 秒内 Agent Cockpit 将自动切换为「官方权威直连」模式。"
