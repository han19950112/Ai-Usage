# 🛸 Agent Cockpit (多智能体统一监控与自动化工作台)

> **专为高频使用多款 AI 编程与办公智能体的开发者打造**。纯 Python 3 原生标准库构建，**零外部第三方 pip/npm 依赖**，跨电脑复制即用，一键常驻后台并提供现代化的本地 Web 监控大屏。

---

## ✨ 核心特性

| 监控与自动化目标 | 支持的功能与实现机制 |
| :--- | :--- |
| **Google Antigravity** | • 自动检测桌面客户端运行进程与 PID<br>• 监听语言服务器（Language Server）及 Host Bridge 端口<br>• 识别中文双入口启动器状态及本地活跃会话数<br>• **⏱️ 5小时滚动订阅配额窗口（150万 Token 滑动限额与释放倒计时）**<br>• **实时会话上下文窗口（Context Window）水位与占用进度条（100万 Token 窗口）**<br>• **累计输入/输出 Token 统计与 Prompt Caching 省流倍率（如 41x 缓存命中）**<br>• **多模型池配额状态显示（Gemini 3.8 Flash、Gemini Pro、Claude 3.5）** |
| **OpenAI Codex** | • 自动检测本地 `~/.codex` 安装环境与客户端版本<br>• **⏱️ 5小时会话额度窗口（2500 次操作滑动监控与状态预警）**<br>• 实时读取 SQLite 本地日志事件数与最新活动时间戳 |
| **火山引擎 Plan API**<br>*(方舟 Coding / Agent Plan)* | • **⏱️ 5小时订阅额度窗口与精确释放倒计时**，提前预防限流<br>• 监控周配额与月配额消耗水位<br>• 节点连通性与 Ping 延迟实时测速 |
| **WorkBuddy & 自动签到**<br>*(腾讯全场景 Agent · Buddy 加油站)* | • 监控 WorkBuddy 本地客户端进程与账号状态<br>• **⏱️ 5小时任务调度窗口监控**<br>• **内置每日定时自动签到引擎**：每天指定时间（默认 09:00）静默向接口打卡领取积分，防止断签<br>• 仪表盘提供 **「🎁 立即打卡」** 手动按钮与最近打卡历史记录 |
| **macOS 原生独立应用** | • **原生桌面应用 `Agent Cockpit.app`**（已部署至 `/Applications`）<br>• 纯 Swift 编译的原生 WebKit 独立窗口，无浏览器地址栏干扰，沉浸式深色毛玻璃大屏<br>• 启动应用时自动唤醒后台守护服务，关闭即走 |

---

## 📂 项目结构

```text
agent-cockpit/
├── README.md               # 项目使用与迁移指南
├── server.py               # 核心服务主入口与 Web 仪表盘服务
├── start.sh                # 一键启动脚本（支持前台/后台守护）
├── stop.sh                 # 停止服务脚本
├── status.sh               # 查看服务运行状态
├── install_service.sh      # macOS 开机自启守护服务一键安装
├── uninstall_service.sh    # 卸载开机自启服务
├── config.json             # 当前运行配置文件（可由网页直接修改）
├── config.example.json     # 配置模板
├── checkin_history.json    # 签到历史与累计积分记录
├── monitors/               # 各 Agent 状态监视模块
│   ├── __init__.py
│   ├── antigravity.py      # Antigravity 运行与端口探测
│   ├── codex.py            # Codex 状态与会话检测
│   ├── volcengine.py       # 火山引擎 Plan 额度与防限流
│   └── workbuddy.py        # WorkBuddy 状态与自动打卡调度引擎
└── web/
    └── index.html          # 响应式玻璃拟态仪表盘前端界面
```

---

## 🚀 快速启动

进入项目根目录：

```bash
cd agent-cockpit
```

### 1. 后台守护运行（推荐）
```bash
./start.sh --daemon
```
启动后打开浏览器访问：👉 **http://localhost:5999**

### 2. 前台调试运行
```bash
./start.sh
```

### 3. 查看运行状态与停止
```bash
./status.sh  # 查看运行状态
./stop.sh    # 停止后台服务
```

---

## ⚙️ 凭证配置指南

首次启动后，您可以直接在 **网页右上角点击「⚙️ 设置凭据」** 进行可视化配置，也可以直接编辑 `config.json`：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5999
  },
  "volcengine": {
    "enabled": true,
    "demo_mode": false,
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key": "your-volcengine-ark-api-key",
    "model": "doubao-seed-evolving",
    "check_interval_seconds": 300
  },
  "workbuddy": {
    "enabled": true,
    "demo_mode": false,
    "checkin_url": "https://workbuddy.qq.com/api/v1/growth/checkin",
    "token": "your-workbuddy-token-or-cookie",
    "cookie": "",
    "auto_checkin_enabled": true,
    "checkin_time": "09:00"
  }
}
```

### 1. 火山引擎 Plan API 获取方式
1. 登录 [火山方舟大模型控制台](https://console.volcengine.com/ark/)。
2. 在右上角或 API Key 管理页面生成专属的 **Ark API Key**。
3. 填入网页设置中的 API Key 即可（若暂时没有，勾选“启用演示模式”可查看完整进度条模拟效果）。

### 2. WorkBuddy 签到凭据获取方式
1. 打开浏览器登录 WorkBuddy 网页版或在桌面客户端抓取一次请求。
2. 复制 Request Headers 里的 `Authorization: Bearer <token>` 或 `Cookie`。
3. 填入设置面板中，点击保存后即可点击 **「🎁 立即打卡」** 测试签到。

---

## 🖥️ 两种使用模式

### 模式 A：macOS 原生独立桌面应用（推荐）
系统已自动生成并部署了 `/Applications/Agent Cockpit.app`：
1. 在 **启动台（Launchpad）** 或 **应用程序（/Applications）** 目录中直接双击 **Agent Cockpit**。
2. 应用将以独立沉浸式原生窗口启动，具备自动拉起后台服务、暗色半透明视觉效果及系统快捷键支持（`Cmd+Q` 退出、`Cmd+R` 刷新、`Cmd+C/V` 复制粘贴）。

### 模式 B：Web 浏览器控制台 / 局域网访问
1. 执行 `./start.sh --daemon` 启动后台。
2. 浏览器打开 `http://localhost:5999`。
3. 同一局域网内的其他手机或平板电脑也可以通过 `http://<当前内网IP>:5999` 同步查看。

---

## 🍎 设为工作电脑开机自启（macOS launchd）

如果想让这套工具在您的常用工作电脑上**开机自动常驻后台、无需人工干预、每日自动执行签到**，只需运行：

```bash
./install_service.sh
```

脚本会自动在 `~/Library/LaunchAgents` 中生成并注册系统级自启守护（`com.agentcockpit.hub.plist`）。
如需卸载开机自启，运行：
```bash
./uninstall_service.sh
```

---

## 📦 如何迁移到您的常用工作电脑？

由于本项目**完全基于 Python 3 原生标准库 + 原生 Swift/WebKit 构建，零第三方依赖（无需 pip install，无需 node/npm）**，迁移极为轻松：

### 方式 1：一键迁移压缩包
在当前项目目录下运行打包脚本：
```bash
./package.sh
```
将生成的 `Agent-Cockpit-macOS.zip` 拷贝到您的常用工作电脑并解压，直接双击解压后的 `Agent Cockpit.app` 即可使用！

### 方式 2：单独拷贝 .app 应用程序
将 `/Applications/Agent Cockpit.app` 单独复制到目标工作电脑的 `/Applications` 目录下，双击即可直接运行，首次启动会自动在 `~/.agent-cockpit/` 初始化配置文件。
