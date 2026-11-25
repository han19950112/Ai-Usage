import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var loadingLabel: NSTextField!
    var statusItem: NSStatusItem!
    var statusTimer: Timer?
    var retryCount = 0
    let maxRetries = 15
    let targetURL = URL(string: "http://127.0.0.1:5999")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMainMenu()
        setupStatusBar()
        setupWindow()
        ensureServerAndLoad()
        startStatusBarPolling()
    }

    func setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let btn = statusItem.button {
            btn.title = "🛸 Cockpit"
            btn.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
        }
        rebuildStatusMenu(agLine: "⚡ Antigravity: 读取中...", cdxLine: "🧠 Codex: 读取中...", wbLine: "🤖 WorkBuddy: 读取中...", volcLine: "🌋 火山引擎: 读取中...", pendingCount: 0)
    }

    func rebuildStatusMenu(agLine: String, cdxLine: String, wbLine: String, volcLine: String, pendingCount: Int) {
        let menu = NSMenu()
        let header = NSMenuItem(title: "🛸 Agent Cockpit 实时配额", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(NSMenuItem.separator())

        for line in [agLine, cdxLine, wbLine, volcLine] {
            let item = NSMenuItem(title: line, action: #selector(showMainWindow), keyEquivalent: "")
            item.target = self
            menu.addItem(item)
        }
        if pendingCount > 0 {
            menu.addItem(NSMenuItem.separator())
            let appr = NSMenuItem(title: "🛡️ 待人工审批: \(pendingCount) 条 (点击处理)", action: #selector(showMainWindow), keyEquivalent: "")
            appr.target = self
            menu.addItem(appr)
        }
        menu.addItem(NSMenuItem.separator())
        let showItem = NSMenuItem(title: "🪟 打开驾驶舱主窗口", action: #selector(showMainWindow), keyEquivalent: "")
        showItem.target = self
        menu.addItem(showItem)
        let refreshItem = NSMenuItem(title: "🔄 立即刷新配额", action: #selector(pollStatusBarNow), keyEquivalent: "")
        refreshItem.target = self
        menu.addItem(refreshItem)
        menu.addItem(NSMenuItem.separator())
        let quitItem = NSMenuItem(title: "退出 Agent Cockpit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quitItem)
        statusItem.menu = menu
    }

    @objc func showMainWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func startStatusBarPolling() {
        pollStatusBarNow()
        statusTimer = Timer.scheduledTimer(timeInterval: 15.0, target: self, selector: #selector(pollStatusBarNow), userInfo: nil, repeats: true)
    }

    @objc func pollStatusBarNow() {
        var req = URLRequest(url: URL(string: "http://127.0.0.1:5999/api/status")!)
        req.timeoutInterval = 3.0
        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let self = self, let data = data,
                  let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

            let ag = root["antigravity"] as? [String: Any] ?? [:]
            let agQ = ag["quota"] as? [String: Any] ?? [:]
            let ag5 = agQ["five_hour_usage"] as? [String: Any] ?? [:]
            let agW = agQ["weekly_usage"] as? [String: Any] ?? [:]
            let agRem5 = (ag5["remaining_percent"] as? Double) ?? max(0, 100 - ((ag5["percent"] as? Double) ?? 0))
            let agRemW = (agW["remaining_percent"] as? Double) ?? max(0, 100 - ((agW["percent"] as? Double) ?? 0))

            let cdx = root["codex"] as? [String: Any] ?? [:]
            let cdx5 = cdx["five_hour_usage"] as? [String: Any] ?? [:]
            let cdxW = cdx["weekly_usage"] as? [String: Any] ?? [:]
            let cdxRC = cdx["reset_credits"] as? [String: Any] ?? [:]
            let cdxRem5 = (cdx5["remaining_percent"] as? Double) ?? max(0, 100 - ((cdx5["percent"] as? Double) ?? 0))
            let cdxRemW = (cdxW["remaining_percent"] as? Double) ?? max(0, 100 - ((cdxW["percent"] as? Double) ?? 0))
            let cdxAvail = (cdxRC["available_count"] as? Int) ?? 0

            let wb = root["workbuddy"] as? [String: Any] ?? [:]
            let wbPts = (wb["total_points"] as? Double) ?? 0
            let wbDays = (wb["consecutive_days"] as? Int) ?? 0

            let volc = root["volcengine"] as? [String: Any] ?? [:]
            let volc5 = (volc["five_hour_quota"] as? [String: Any])?["percent"] as? Double ?? 0
            let volcW = (volc["weekly_quota"] as? [String: Any])?["percent"] as? Double ?? 0

            let mc = root["mission_control"] as? [String: Any] ?? [:]
            let mcSum = mc["summary"] as? [String: Any] ?? [:]
            let pending = (mcSum["pending_approvals"] as? Int) ?? 0

            let cb = root["circuit_breaker"] as? [String: Any] ?? [:]
            let cbTripped = (cb["triggered"] as? Bool) ?? false

            let prefix = (cbTripped || pending > 0) ? "🚨" : "🛸"
            let titleStr = String(format: "%@ AG %.0f%% · CDX %.0f%%", prefix, agRem5, cdxRem5)
            let agLine = String(format: "⚡ Antigravity: 5h剩 %.0f%% · 周剩 %.0f%%", agRem5, agRemW)
            let cdxLine = String(format: "🧠 Codex: 5h剩 %.0f%% · 周剩 %.0f%% (重置可用 %d)", cdxRem5, cdxRemW, cdxAvail)
            let wbLine = String(format: "🤖 WorkBuddy: %.1f 积分 · 连续 %d 天", wbPts, wbDays)
            let volcLine = String(format: "🌋 火山引擎: 5h已用 %.1f%% · 7d已用 %.1f%%", volc5, volcW)

            DispatchQueue.main.async {
                self.statusItem.button?.title = titleStr
                self.rebuildStatusMenu(agLine: agLine, cdxLine: cdxLine, wbLine: wbLine, volcLine: volcLine, pendingCount: pending)
            }
        }.resume()
    }

    func setupMainMenu() {
        let mainMenu = NSMenu()
        
        // App Menu
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 Agent Cockpit", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "隐藏 Agent Cockpit", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = NSMenuItem(title: "隐藏其他", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(withTitle: "显示全部", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "退出 Agent Cockpit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)
        
        // Edit Menu (Essential for copy/paste in WebView)
        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        let redoItem = NSMenuItem(title: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        redoItem.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redoItem)
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        // View Menu
        let viewMenuItem = NSMenuItem()
        let viewMenu = NSMenu(title: "视图")
        let reloadItem = NSMenuItem(title: "刷新驾驶舱", action: #selector(reloadWebView), keyEquivalent: "r")
        viewMenu.addItem(reloadItem)
        let fullScreenItem = NSMenuItem(title: "进入全屏幕", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fullScreenItem.keyEquivalentModifierMask = [.command, .control]
        viewMenu.addItem(fullScreenItem)
        viewMenuItem.submenu = viewMenu
        mainMenu.addItem(viewMenuItem)

        NSApp.mainMenu = mainMenu
    }

    func setupWindow() {
        let initialRect = NSRect(x: 0, y: 0, width: 1220, height: 860)
        window = NSWindow(
            contentRect: initialRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.delegate = self
        window.center()
        window.title = "Agent Cockpit 智能体驾驶舱"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 900, height: 600)
        window.backgroundColor = NSColor(red: 0.05, green: 0.07, blue: 0.12, alpha: 1.0)

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground") // 让背景透明，消除白屏闪烁
        window.contentView?.addSubview(webView)

        // Loading indicator text
        loadingLabel = NSTextField(frame: NSRect(x: (window.frame.width - 320) / 2, y: (window.frame.height - 60) / 2, width: 320, height: 60))
        loadingLabel.isEditable = false
        loadingLabel.isSelectable = false
        loadingLabel.isBezeled = false
        loadingLabel.drawsBackground = false
        loadingLabel.alignment = .center
        loadingLabel.font = NSFont.systemFont(ofSize: 15, weight: .medium)
        loadingLabel.textColor = NSColor(red: 0.55, green: 0.65, blue: 0.8, alpha: 1.0)
        loadingLabel.stringValue = "🚀 正在启动 Agent Cockpit 服务..."
        loadingLabel.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin, .maxYMargin]
        window.contentView?.addSubview(loadingLabel)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func reloadWebView() {
        webView.reload()
    }

    func ensureServerAndLoad() {
        checkServerRunning { [weak self] isRunning in
            guard let self = self else { return }
            if isRunning {
                DispatchQueue.main.async {
                    self.loadingLabel.isHidden = true
                    self.webView.load(URLRequest(url: self.targetURL))
                }
            } else {
                self.startLocalServer()
                self.pollUntilServerReady()
            }
        }
    }

    func checkServerRunning(completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:5999/api/status")!)
        request.timeoutInterval = 1.0
        let task = URLSession.shared.dataTask(with: request) { _, response, error in
            if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 {
                completion(true)
            } else {
                completion(false)
            }
        }
        task.resume()
    }

    func locateProjectDirectory() -> String {
        let bundlePath = Bundle.main.bundleURL
        
        // 1. 同级目录（如解压到某个文件夹后双击 app）
        let candidateSameDir = bundlePath.deletingLastPathComponent().path
        if FileManager.default.fileExists(atPath: "\(candidateSameDir)/server.py") {
            return candidateSameDir
        }
        
        // 2. 父级目录
        let candidateParentDir = bundlePath.deletingLastPathComponent().deletingLastPathComponent().path
        if FileManager.default.fileExists(atPath: "\(candidateParentDir)/server.py") {
            return candidateParentDir
        }

        // 3. App Bundle 内部内置后端资源（完全单 App 便携运行）
        let internalBackend = bundlePath.appendingPathComponent("Contents/Resources/backend").path
        if FileManager.default.fileExists(atPath: "\(internalBackend)/server.py") {
            return internalBackend
        }

        // 4. 用户系统标准工作路径
        let defaultHomeDir = NSString(string: "~/.gemini/antigravity/scratch/agent-cockpit").expandingTildeInPath
        if FileManager.default.fileExists(atPath: "\(defaultHomeDir)/server.py") {
            return defaultHomeDir
        }

        return candidateSameDir
    }

    func startLocalServer() {
        let projectDir = locateProjectDirectory()
        let startScript = "\(projectDir)/start.sh"
        if FileManager.default.isExecutableFile(atPath: startScript) {
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/bin/bash")
            proc.arguments = [startScript, "--daemon"]
            proc.currentDirectoryURL = URL(fileURLWithPath: projectDir)
            try? proc.run()
        } else {
            // Direct python3 fallback
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            proc.arguments = ["\(projectDir)/server.py"]
            proc.currentDirectoryURL = URL(fileURLWithPath: projectDir)
            try? proc.run()
        }
    }

    func pollUntilServerReady() {
        if retryCount >= maxRetries {
            DispatchQueue.main.async {
                self.loadingLabel.stringValue = "⚠️ 后台服务启动超时，请在终端运行 ./start.sh 检查"
            }
            return
        }

        retryCount += 1
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.4) { [weak self] in
            guard let self = self else { return }
            self.checkServerRunning { isRunning in
                if isRunning {
                    DispatchQueue.main.async {
                        self.loadingLabel.isHidden = true
                        self.webView.load(URLRequest(url: self.targetURL))
                    }
                } else {
                    self.pollUntilServerReady()
                }
            }
        }
    }

    // WKNavigationDelegate
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loadingLabel.isHidden = true
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        loadingLabel.isHidden = false
        loadingLabel.stringValue = "连接失败，正在重试..."
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            webView.load(URLRequest(url: self.targetURL))
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            showMainWindow()
        }
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
