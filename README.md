# 🛸 Agent Cockpit (多智能体统一监控与自动化工作台)

> **专为高频使用多款 AI 编程与办公智能体的开发者打造**。纯 Python 3 原生标准库构建，**零外部第三方 pip/npm 依赖**，跨电脑复制即用，一键常驻后台并提供现代化的本地 Web 监控大屏。
> 
> 全面赋能 **AG-UI Protocol 1.0 (Agent-User Interface Protocol)**：支持毫秒级 SSE 实时事件流、右侧流式打字机指令台、以及 **90% 配额超额安全熔断与人机协同审批 (Human-in-the-Loop)**。

---

## ✨ 核心特性

| 监控与自动化目标 | 支持的功能与实现机制 |
| :--- | :--- |
| **Google Antigravity** | • **官方权威 CDP 直连 + 失败退避**：支持穿透 React Fiber 获取官方 QuotaInfo，离线时自动退避避免高频超时<br>• **双模型池独立监控**：自动识别当前活跃模型（如 Gemini 4 Neon / Flash）与高阶 Claude 配额池<br>• **⏱️ 5小时与 7天滑动订阅窗口及精确倒计时**<br>• **Prompt Caching 缓存省流倍率** + 本地 `transcript.jsonl` 增量文件缓存（毫秒级低开销） |
| **OpenAI Codex** | • 自动检测本地 `~/.codex` 安装环境、订阅类型（如 Plus）与客户端版本<br>• **官方 Session 真实配额**：直读 `~/.codex/sessions/**/*.jsonl` 官方 `rate_limits`（5小时 & 7天真实百分比与重置时间戳）<br>• **本周可用完全重置次数**：自动计算周重置前剩余的完整 5 小时周期数与精准到期节点 |
| **WorkBuddy & 自动签到**<br>*(腾讯全场景 Agent · Buddy 加油站)* | • **💰 真实账户积分同步**：对接 `www.workbuddy.cn` 桌面端接口，实时同步总剩余积分、累计连签天数与**最近积分到期预警**<br>• **内置每日定时防断签引擎**：每天 09:00 静默调用 `/billing/meter/daily-checkin` 自动打卡领 +100 积分<br>• **macOS 原生通知提醒**：签到成功/失败及 Cookie 过期时自动弹出系统通知 |
| **火山引擎 Plan API**<br>*(方舟 Agent Plan / Coding Plan)* | • **OpenAPI (AK/SK) 真实配额直连**：内置纯标准库 Signature V4 签名，调用 `GetAgentPlanAFPUsage` 与 `ListSubscribeTrade`，实时同步 **5h / 7天 / 月度 AFP 燃料值**及**实际订阅到期时间**<br>• **推理 API Key (`ark-`) 0-Token 探测**：未填 AK/SK 时亦可自动切换 `/api/coding/v3` 网关进行毫秒级连通测速 |
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

### 1. 火山引擎 Agent Plan / Coding Plan 配置方式
1. **查看真实 5h / 7天 / 月度 AFP 燃料值与订阅到期日（推荐）**：登录 [火山引擎 IAM 密钥管理](https://console.volcengine.com/iam/keymanage/) 获取具备 `ArkReadOnlyAccess` 权限的 **AccessKey ID (AK)** 和 **SecretAccessKey (SK)**，填入网页设置弹窗保存即可自动拉取真实配额与订阅到期日。
2. **仅测试推理连通性**：在 [火山方舟控制台](https://console.volcengine.com/ark/) 生成 `ark-` 推理 API Key 填入即可（若暂时没有，勾选“启用演示模式”可预览完整效果）。

### 2. WorkBuddy 真实积分与每日自动签到配置方式
1. 在浏览器登录 [WorkBuddy 网页版](https://www.workbuddy.cn/app)，按 `⌘+Option+I` 打开 DevTools → **Network**，点击任意一条 `www.workbuddy.cn` 的 `200` 请求。
2. 复制 Request Headers 里的 **`Cookie`**，以及该浏览器的 **`User-Agent`**（WorkBuddy 网关会校验 Session 与 UA 一致性）。
3. 填入设置面板的 **WorkBuddy Cookie** 与 **WorkBuddy User-Agent**（若在同一浏览器保存可留空 UA 自动沿用），点击保存即可同步真实积分并在每天 09:00 自动打卡领 +100 积分。

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
