#!/usr/bin/env bash
# macOS launchd 开机自启与后台保活安装脚本
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.agentcockpit.hub.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME"
PYTHON_BIN="$(which python3)"

mkdir -p "$HOME/Library/LaunchAgents"

# 若已有运行则先卸载
if launchctl list | grep -q "com.agentcockpit.hub"; then
    launchctl unload "$TARGET_PLIST" 2>/dev/null || true
fi

cat > "$TARGET_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agentcockpit.hub</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$DIR/server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$DIR/server.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/server_err.log</string>
</dict>
</plist>
EOF

launchctl load "$TARGET_PLIST"

echo "=============================================="
echo "✅ macOS 开机自启守护服务安装成功！"
echo "📌 Plist 路径: $TARGET_PLIST"
echo "👉 仪表盘已启动并在开机时自动保活: http://localhost:5999"
echo "🛑 如需卸载开机自启，请运行: ./uninstall_service.sh"
echo "=============================================="
