# 🛸 Agent Cockpit (多智能体统一监控与自动化工作台)

> **专为高频使用多款 AI 编程与办公智能体的开发者打造**。纯 Python 3 原生标准库构建，**零外部第三方 pip/npm 依赖**，跨电脑复制即用，一键常驻后台并提供现代化的本地 Web 监控大屏。
> 
> 全面赋能 **AG-UI Protocol 1.0 (Agent-User Interface Protocol)**：支持毫秒级 SSE 实时事件流、右侧流式打字机指令台、以及 **90% 配额超额安全熔断与人机协同审批 (Human-in-the-Loop)**。

---

## ✨ 核心特性

| 监控与自动化目标 | 支持的功能与实现机制 |
| :--- | :--- |
| **Google Antigravity** | • **官方权威 CDP 直连**：穿透连接 React Fiber 节点，消除 Token 缓存估算失真，100% 精确对齐官方 QuotaInfo<br>• **双模型池独立监控**：主力套 Gemini 3.8 Flash vs 高阶套 Claude 3.5 Sonnet / Pro 专属配额池<br>• **⏱️ 5小时滑动订阅窗口与精确倒计时**（到期时间戳 + 自然人类读数）<br>• **Prompt Caching 缓存省流倍率**（如 24.4x 命中，超 5000 万 Token 缓存收益）<br>• **优雅离线 Fallback**：即使 IDE 离线，亦能基于本地 Transcript 实时计算真实滑动用量 |
| **OpenAI Codex** | • 自动检测本地 `~/.codex` 安装环境与客户端版本<br>• **⏱️ 5小时与周额度双窗口监控**：只读分析 SQLite 日志库<br>• **重置次数与释放倒计时**：剩余操作次数（如 2,500 次 / 15,000 次）与周一 UTC 重置时刻 |
| **WorkBuddy & 自动签到**<br>*(腾讯全场景 Agent · Buddy 加油站)* | • **💰 账户积分余额核心面板**：直观展示总积分流水与累计连续打卡天数<br>• **内置每日定时防断签引擎**：每天 09:00 后台自动静默打卡领积分<br>• 提供 **「🎁 立即打卡」** 手动操作与最近打卡历史流水 |
| **火山引擎 Plan API**<br>*(方舟 Coding / Agent Plan)* | • **⏱️ 5小时滑动订阅窗口与周额度消耗**，提前预防方舟阶梯限流<br>• 节点连通性与毫秒级 Ping 往返测速 |
| **AG-UI 实时事件流**<br>*(Protocol 1.0)* | • **Server-Sent Events (SSE)** 高频事件广播：`STATE_SNAPSHOT`、`STATE_DELTA`、`AGENT_TICK`<br>• 毫秒级时钟走秒与倒计时同步，无需任何轮询开销 |
| **💬 智能体流式指令抽屉** | • **快捷键 `⌘K` / `Ctrl+K` 全局一键呼出**（平时完全收起，不遮挡大屏）<br>• **原生打字机流式输出**：`RUN_STARTED` $\to$ `TOOL_CALL` $\to$ `CHUNK` $\to$ `RUN_FINISHED`<br>• **结构化工具卡片**：展开查看参数与执行结果<br>• **综合体检日报**：一键生成四大智能体全景用量分析 Markdown 简报<br>• **LocalStorage 持久化**：聊天记录自动跨刷新保留 |
| **🚨 90% 额度安全熔断**<br>*(Human-in-the-Loop)* | • **90.0% 严格安全警戒线**：超额自动阻断自动化调度<br>• **人机协同审批卡片**：触发红光呼吸警示与 Web Audio 合成科技提示音<br>• **三大授权处置方案**：自动无感切换至备用高阶模型池 / 挂起后台任务等待重置 / 风险放行<br>• 提供 **「🧪 演练90%熔断」** 快速验证测试 |
| **macOS 原生独立应用** | • **原生桌面应用 `Agent Cockpit.app`**（已部署至 `/Applications`）<br>• 纯 Swift 编译的原生 WebKit 独立窗口，无浏览器地址栏干扰，沉浸式深色毛玻璃大屏 |

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

---

## 🤖 AG-UI 协议与智能体指令台指南

Agent Cockpit 全面落地了 **AG-UI Protocol 1.0 (Agent-User Interface Protocol)** 规范：

### 1. 快捷键
* **`⌘K` / `Ctrl+K`**：全局快速呼出 / 收起右侧流式指令台
* **`Esc`**：快速退出指令抽屉或熔断审批模态窗

### 2. 常用自然语言指令与工具调用
您可以在右侧指令台中直接向 Agent 发送如下自然语言命令：
* **`📋 生成今日四大智能体用量综合体检报告`**：自动触发全 Agent 指标聚合，流式输出结构化 Markdown 体检日报。
* **`🎁 立即执行 WorkBuddy 签到打卡并核算积分`**：调用 `workbuddy_auto_checkin` 工具，领积分防断签。
* **`📊 查询 Antigravity 官方当前配额与重置时间`**：直连官方 CDP 探针，核对主力 Gemini 与高阶 Claude 真实配额。
* **`🧠 查询 Codex 剩余操作数与重置时间`**：读取本地 SQLite 库，解析 5小时 2,500 次及周 15,000 次剩余量。
* **`🚨 演练 90% 额度超额熔断保护`**：广播 `HUMAN_INTERACTION_REQUIRED` 事件，体验安全熔断卡片与三大人机审批方案。
