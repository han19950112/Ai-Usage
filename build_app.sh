#!/usr/bin/env bash
# Agent Cockpit macOS 原生应用程序打包脚本

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Agent Cockpit"
APP_DIR="$DIR/$APP_NAME.app"
SYS_APP_DIR="/Applications/$APP_NAME.app"

echo "=========================================="
echo "🚀 开始构建 $APP_NAME.app 原生桌面程序"
echo "=========================================="

# 1. 确保图标存在
ICON_FILE="$DIR/assets/AppIcon.icns"
if [ ! -f "$ICON_FILE" ]; then
    echo "🎨 正在生成应用高清图标..."
    swift "$DIR/scripts/make_icns.swift"
    iconutil -c icns /tmp/AgentCockpit.iconset -o "$ICON_FILE"
fi

# 2. 编译 Swift 原生二进制文件
echo "🔨 正在编译 macOS 原生应用可执行二进制..."
swiftc -O "$DIR/native_app.swift" -o "/tmp/AgentCockpitBin" -framework Cocoa -framework WebKit

# 3. 创建 App Bundle 目录结构
echo "📁 正在生成 .app 目录结构..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 4. 拷贝二进制与图标及内置自包含后端
cp "/tmp/AgentCockpitBin" "$APP_DIR/Contents/MacOS/$APP_NAME"
chmod +x "$APP_DIR/Contents/MacOS/$APP_NAME"
cp "$ICON_FILE" "$APP_DIR/Contents/Resources/AppIcon.icns"

echo "📦 正在注入自包含后端资源..."
mkdir -p "$APP_DIR/Contents/Resources/backend"
cp -R "$DIR/monitors" "$APP_DIR/Contents/Resources/backend/"
cp -R "$DIR/web" "$APP_DIR/Contents/Resources/backend/"
cp "$DIR/server.py" "$APP_DIR/Contents/Resources/backend/"
cp "$DIR/mission_control.py" "$APP_DIR/Contents/Resources/backend/"
cp "$DIR/start.sh" "$APP_DIR/Contents/Resources/backend/"
cp "$DIR/stop.sh" "$APP_DIR/Contents/Resources/backend/"
cp "$DIR/status.sh" "$APP_DIR/Contents/Resources/backend/"
cp "$DIR/config.example.json" "$APP_DIR/Contents/Resources/backend/"
chmod +x "$APP_DIR/Contents/Resources/backend/"*.sh

# 5. 写入 Info.plist
cat << 'EOF' > "$APP_DIR/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Agent Cockpit</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.gemini.agentcockpit</string>
    <key>CFBundleName</key>
    <string>Agent Cockpit</string>
    <key>CFBundleDisplayName</key>
    <string>Agent Cockpit 智能体驾驶舱</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsArbitraryLoads</key>
        <true/>
    </dict>
</dict>
</plist>
EOF

# 写入 PkgInfo
echo -n "APPL????" > "$APP_DIR/Contents/PkgInfo"

# 6. 复制到 /Applications
echo "📦 正在部署至 /Applications/$APP_NAME.app ..."
rm -rf "$SYS_APP_DIR"
cp -R "$APP_DIR" "$SYS_APP_DIR"

echo "✅ 构建并部署成功！"
echo "  - 项目内应用位置: $APP_DIR"
echo "  - 系统应用位置: $SYS_APP_DIR"
echo "=========================================="
