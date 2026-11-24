#!/usr/bin/env bash
# macOS launchd 开机自启服务卸载脚本

PLIST_NAME="com.agentcockpit.hub.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME"

if [ -f "$TARGET_PLIST" ]; then
    launchctl unload "$TARGET_PLIST" 2>/dev/null || true
    rm -f "$TARGET_PLIST"
    echo "✅ 已卸载开机自启服务: $TARGET_PLIST"
else
    echo "ℹ️  未安装开机自启服务"
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/stop.sh"
