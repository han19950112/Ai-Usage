# 🛸 Agent Cockpit (多智能体统一监控、任务调度与自动化工作台)

> **专为同时使用多款 AI 编程与全场景智能体的开发者打造**。纯 Python 3 原生标准库 + 单文件 Web 控制台 + Swift/WebKit 原生 macOS 应用构建，**零外部第三方 pip/npm 依赖**，开箱即用、低功耗常驻。

---

## ✨ 核心特性

| 模块 | 支持能力与实现机制 |
| :--- | :--- |
| **⚡ Google Antigravity** | • **官方 `agy` CLI 双窗口直连**：后台异步调用 `agy -p /usage --output-format json`（60s 缓存），无感获取 Gemini 与 Claude/GPT **5小时 + 7天周**官方精确配额及重置时间<br>• **CDP 与本地 Transcript 多级兜底**：支持 CDP 端口直连及本地会话缓存解析，计算 Prompt Caching 省流倍率 |
| **🧠 OpenAI Codex** | • **官方 `wham/usage` + Session 双源同步**：自动读取 `~/.codex/auth.json` 与本地会话 JSONL，实时展示 **5小时 & 7天周**配额与精确重置节点<br>• **官方限额重置次数监控**：只读同步 `wham/rate-limit-reset-credits` 可用完全重置次数及各张重置券到期时间 |
| **🤖 WorkBuddy (腾讯)** | • **官方扫码登录 + Refresh Token 自动续期**：内置 `codebuddy.cn/v2/plugin/auth` 扫码授权与 `X-Refresh-Token` 自动无感续期，彻底告别 7 天手动换 Cookie<br>• **真实积分与每日自动防断签**：对接 `www.workbuddy.cn` 桌面端接口，同步总积分、连签天数、最近到期积分预警，每日定时自动签到领积分 |
| **🌋 火山引擎 Plan API** | • **纯标准库 Signature V4 (AK/SK) 直连**：调用 `GetAgentPlanAFPUsage` 与 `ListSubscribeTrade` 实时同步 **5h / 7天 / 月度 AFP** 用量与套餐到期日<br>• **推理网关 (`ark-`) 连通探测**：支持流式对话与延迟测速 |
| **🚀 多 Agent 任务中心**<br>*(Mission Control)* | • **真实多引擎统一派发**：统一调度 `agy` CLI、`codex exec`、`codebuddy` CLI 与火山引擎流式 API<br>• **🤖 智能路由 (Auto)**：自动挑选当前剩余配额最充裕的就绪引擎执行任务<br>• **🔀 一键并行广播 & 左右并排对比**：同一指令并发派发多个 Agent，弹窗实时并排对比输出，支持一键复制 Markdown、单条重试与 SQLite 跨重启持久化 |
| **🚨 全平台可配置熔断**<br>*(Human-in-the-Loop)* | • **7 大配额窗口全覆盖**：支持在设置中自定义警戒阈值（`50%`–`99%`，默认 `90%`）<br>• **真实联动处置**：支持自动将超额 Agent 后续任务智能分流至空闲引擎，或一键挂起后台调度 |
| **🍎 macOS 原生应用与菜单栏** | • **顶部菜单栏实时组件 (`NSStatusBar`)**：常驻展示 `🛸 AG X% · CDX Y%`，下拉即看 4 大平台详情与待审批提醒，关闭主窗口后后台静默保活 |
| **🔒 默认本机安全加固** | • 默认绑定 `127.0.0.1`、严格校验同源 `Origin` 防止网页跨站调用本地 CLI；如需局域网远程写操作支持配置 `server.api_token` Bearer 鉴权 |

---

## 📂 项目结构

```text
Ai-Usage/
├── server.py               # 核心 HTTP / AG-UI SSE 事件流与安全网关
├── agent_runner.py         # 多 Agent 统一子进程/流式执行、智能路由与并行广播引擎
├── mission_control.py      # SQLite (WAL) 任务看板、审批流、执行日志持久化与趋势快照
├── native_app.swift        # macOS 原生 WebKit 窗口 + NSStatusBar 顶部状态栏组件源码
├── monitors/               # 四大平台监控与鉴权适配器（共享短期 ps 缓存）
│   ├── __init__.py         # 跨模块进程快照短期缓存
│   ├── antigravity.py      # agy CLI / CDP / 本地 Transcript 多级配额引擎
│   ├── codex.py            # OpenAI wham/usage、重置券与本地 Session 监控
│   ├── volcengine.py       # 火山引擎 IAM Signature V4 OpenAPI 与方舟探测
│   └── workbuddy.py        # WorkBuddy 扫码登录、Refresh Token 续期与自动打卡
├── web/
│   └── index.html          # 单文件零依赖响应式控制台界面
├── build_app.sh            # 编译并部署 /Applications/Agent Cockpit.app
├── install_service.sh      # 注册 macOS launchd 开机自启守护服务
├── uninstall_service.sh    # 卸载 launchd 守护服务
├── package.sh              # 打包脱敏便携迁移包 (自动排除个人密钥与本地 SQLite 库)
├── start.sh / stop.sh / status.sh
└── config.example.json     # 配置文件模板
```

---

## 🚀 快速启动与部署

### 1. 注册 macOS 开机自启守护服务（推荐）
```bash
./install_service.sh
```
安装后服务将在后台自动保活，浏览器可直接访问 **http://localhost:5999**。

### 2. 编译并安装 macOS 原生桌面端 + 顶部菜单栏
```bash
./build_app.sh
open "/Applications/Agent Cockpit.app"
```

### 3. 前台/守护脚本控制
```bash
./start.sh --daemon   # 后台启动
./status.sh           # 查看监听状态
./stop.sh             # 停止服务
```

---

## ⚙️ 凭据与安全说明

1. 点击界面左下角或右上角 **「⚙️ 凭据与设置」** 即可可视化配置：
   - **WorkBuddy**：直接点击 **「🔗 WorkBuddy 官方扫码登录」** 即可自动完成授权并开启 Refresh Token 自动续期（无需手动抓包 Cookie）。
   - **火山引擎**：填入具备只读权限的 IAM `AK` / `SK` 可拉取真实 5h / 7d / 月度 AFP 配额与订阅到期日；填入 `api_key` 可用于模型流式对话。
   - **熔断阈值**：支持在 `50%`–`99%` 之间自由调整全局告警水位线。
2. 所有敏感凭据均保存在本地 `config.json`（权限 `0600`，已被 `.gitignore` 与 `package.sh` 严格排除），接口返回自动脱敏。
