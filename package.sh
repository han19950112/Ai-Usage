#!/usr/bin/env bash
# 一键打包 Agent Cockpit 为便携迁移压缩包
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
DIR_NAME="$(basename "$DIR")"
PARENT_DIR="$(cd "$DIR/.." && pwd)"
PACKAGE_NAME="Agent-Cockpit-macOS.zip"
OUTPUT_PATH="$PARENT_DIR/$PACKAGE_NAME"

echo "=========================================="
echo "📦 正在打包 Agent Cockpit 迁移归档包..."
echo "=========================================="

# 确保最新版本 .app 已构建
"$DIR/build_app.sh"

cd "$PARENT_DIR"
rm -f "$OUTPUT_PATH"

echo "🗜️ 正在压缩项目文件..."
zip -r -q -X "$PACKAGE_NAME" "$DIR_NAME" \
    -x "$DIR_NAME/.git/*" \
    -x "$DIR_NAME/config.json" \
    -x "$DIR_NAME/checkin_history.json" \
    -x "$DIR_NAME/server.log" \
    -x "$DIR_NAME/server_err.log" \
    -x "$DIR_NAME/server.pid" \
    -x "$DIR_NAME/*.pyc" \
    -x "$DIR_NAME/__pycache__/*" \
    -x "$DIR_NAME/monitors/__pycache__/*" \
    -x "$DIR_NAME/.DS_Store"

echo "=========================================="
echo "🎉 归档打包完成！"
echo "📦 迁移压缩包位置: $OUTPUT_PATH"
ls -lh "$OUTPUT_PATH"
echo "💡 迁移方法:"
echo "   1. 将 $PACKAGE_NAME 拷贝到目标工作电脑"
echo "   2. 解压后，双击其中的 'Agent Cockpit.app' 即可直接运行"
echo "   3. 或运行 ./install_service.sh 注册为开机后台自动守护服务"
echo "=========================================="
