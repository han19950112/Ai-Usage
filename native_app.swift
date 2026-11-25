import Cocoa
import WebKit

// MARK: - Interactive Menu Bar Popover ViewController (NSPopover)
class CockpitPopoverViewController: NSViewController, NSTextFieldDelegate {
    weak var appDelegate: AppDelegate?

    private let agValLabel = NSTextField(labelWithString: "读取中...")
    private let agBar = NSProgressIndicator()
    private let cdxValLabel = NSTextField(labelWithString: "读取中...")
    private let cdxBar = NSProgressIndicator()
    private let wbValLabel = NSTextField(labelWithString: "读取中...")
    private let wbCheckinBtn = NSButton(title: "签到", target: nil, action: nil)
    private let volcValLabel = NSTextField(labelWithString: "读取中...")
    private let volcBar = NSProgressIndicator()
    private let pendingBanner = NSTextField(labelWithString: "")
    private let quickInput = NSTextField()
    private let dispatchFeedback = NSTextField(labelWithString: "")

    override func loadView() {
        let width: CGFloat = 336
        let height: CGFloat = 376
        let effect = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        effect.material = .popover
        effect.blendingMode = .behindWindow
        effect.state = .active
        self.view = effect

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false
        effect.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: effect.topAnchor, constant: 14),
            stack.leadingAnchor.constraint(equalTo: effect.leadingAnchor, constant: 14),
            stack.trailingAnchor.constraint(equalTo: effect.trailingAnchor, constant: -14),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: effect.bottomAnchor, constant: -12)
        ])

        // 1. Header
        let headerRow = NSStackView()
        headerRow.orientation = .horizontal
        headerRow.distribution = .fill
        let titleLbl = NSTextField(labelWithString: "Agent Cockpit")
        titleLbl.font = NSFont.systemFont(ofSize: 13.5, weight: .semibold)
        let openBtn = NSButton(title: "打开主窗口 ↗", target: self, action: #selector(handleOpenMain))
        openBtn.bezelStyle = .recessed
        openBtn.controlSize = .small
        openBtn.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        headerRow.addArrangedSubview(titleLbl)
        headerRow.addArrangedSubview(NSView())
        headerRow.addArrangedSubview(openBtn)
        stack.addArrangedSubview(headerRow)

        // Pending Approvals Banner (hidden when 0)
        pendingBanner.font = NSFont.systemFont(ofSize: 11.5, weight: .semibold)
        pendingBanner.textColor = NSColor.systemOrange
        pendingBanner.isHidden = true
        stack.addArrangedSubview(pendingBanner)

        // 2. Four Agent Mini Cards
        stack.addArrangedSubview(makeBarCard(title: "Google Antigravity", detailLabel: agValLabel, bar: agBar))
        stack.addArrangedSubview(makeBarCard(title: "OpenAI Codex", detailLabel: cdxValLabel, bar: cdxBar))
        stack.addArrangedSubview(makeWorkBuddyCard())
        stack.addArrangedSubview(makeBarCard(title: "火山引擎 Agent Plan", detailLabel: volcValLabel, bar: volcBar))

        // 3. Quick Task Dispatch Input
        let dispatchBox = NSBox()
        dispatchBox.boxType = .custom
        dispatchBox.cornerRadius = 8
        dispatchBox.borderWidth = 1
        dispatchBox.borderColor = NSColor.separatorColor
        dispatchBox.fillColor = NSColor.controlBackgroundColor.withAlphaComponent(0.45)
        dispatchBox.contentViewMargins = NSSize(width: 8, height: 7)

        let dCol = NSStackView()
        dCol.orientation = .vertical
        dCol.alignment = .width
        dCol.spacing = 5

        let dRow = NSStackView()
        dRow.orientation = .horizontal
        dRow.spacing = 6

        quickInput.placeholderString = "快捷派发任务 (Auto 智能路由)..."
        quickInput.font = NSFont.systemFont(ofSize: 11.5)
        quickInput.bezelStyle = .roundedBezel
        quickInput.controlSize = .small
        quickInput.delegate = self

        let sendBtn = NSButton(title: "派发", target: self, action: #selector(handleQuickDispatch))
        sendBtn.bezelStyle = .rounded
        sendBtn.controlSize = .small
        sendBtn.keyEquivalent = "\r"

        dRow.addArrangedSubview(quickInput)
        dRow.addArrangedSubview(sendBtn)
        dCol.addArrangedSubview(dRow)

        dispatchFeedback.font = NSFont.systemFont(ofSize: 10.5)
        dispatchFeedback.textColor = NSColor.secondaryLabelColor
        dispatchFeedback.isHidden = true
        dCol.addArrangedSubview(dispatchFeedback)

        dispatchBox.contentView = dCol
        stack.addArrangedSubview(dispatchBox)

        // 4. Footer Actions
        let footer = NSStackView()
        footer.orientation = .horizontal
        let refreshBtn = NSButton(title: "刷新状态", target: self, action: #selector(handleRefresh))
        refreshBtn.bezelStyle = .inline
        refreshBtn.font = NSFont.systemFont(ofSize: 11)
        let quitBtn = NSButton(title: "退出 Cockpit", target: self, action: #selector(handleQuit))
        quitBtn.bezelStyle = .inline
        quitBtn.font = NSFont.systemFont(ofSize: 11)
        footer.addArrangedSubview(refreshBtn)
        footer.addArrangedSubview(NSView())
        footer.addArrangedSubview(quitBtn)
        stack.addArrangedSubview(footer)
    }

    private func makeBarCard(title: String, detailLabel: NSTextField, bar: NSProgressIndicator) -> NSView {
        let box = NSBox()
        box.boxType = .custom
        box.cornerRadius = 8
        box.borderWidth = 1
        box.borderColor = NSColor.separatorColor
        box.fillColor = NSColor.controlBackgroundColor.withAlphaComponent(0.38)
        box.contentViewMargins = NSSize(width: 9, height: 7)

        let v = NSStackView()
        v.orientation = .vertical
        v.alignment = .width
        v.spacing = 4

        let top = NSStackView()
        top.orientation = .horizontal
        let tLbl = NSTextField(labelWithString: title)
        tLbl.font = NSFont.systemFont(ofSize: 11.5, weight: .semibold)
        detailLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        detailLabel.textColor = NSColor.secondaryLabelColor
        detailLabel.alignment = .right
        top.addArrangedSubview(tLbl)
        top.addArrangedSubview(NSView())
        top.addArrangedSubview(detailLabel)

        bar.isIndeterminate = false
        bar.minValue = 0
        bar.maxValue = 100
        bar.doubleValue = 0
        bar.controlSize = .small

        v.addArrangedSubview(top)
        v.addArrangedSubview(bar)
        box.contentView = v
        return box
    }

    private func makeWorkBuddyCard() -> NSView {
        let box = NSBox()
        box.boxType = .custom
        box.cornerRadius = 8
        box.borderWidth = 1
        box.borderColor = NSColor.separatorColor
        box.fillColor = NSColor.controlBackgroundColor.withAlphaComponent(0.38)
        box.contentViewMargins = NSSize(width: 9, height: 7)

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY

        let left = NSStackView()
        left.orientation = .vertical
        left.alignment = .leading
        left.spacing = 2
        let tLbl = NSTextField(labelWithString: "WorkBuddy 腾讯全场景")
        tLbl.font = NSFont.systemFont(ofSize: 11.5, weight: .semibold)
        wbValLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        wbValLabel.textColor = NSColor.secondaryLabelColor
        left.addArrangedSubview(tLbl)
        left.addArrangedSubview(wbValLabel)

        wbCheckinBtn.target = self
        wbCheckinBtn.action = #selector(handleCheckin)
        wbCheckinBtn.bezelStyle = .rounded
        wbCheckinBtn.controlSize = .small
        wbCheckinBtn.font = NSFont.systemFont(ofSize: 11)

        row.addArrangedSubview(left)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(wbCheckinBtn)
        box.contentView = row
        return box
    }

    func updateMetrics(agRem5: Double, agRemW: Double, cdxRem5: Double, cdxRemW: Double, cdxAvail: Int, wbPts: Double, wbDays: Int, wbChecked: Bool, volcRem5: Double, volcRemW: Double, pending: Int) {
        let _ = self.view // Ensure loaded
        agValLabel.stringValue = String(format: "5h剩 %.0f%% · 周剩 %.0f%%", agRem5, agRemW)
        agBar.doubleValue = max(0, min(100, 100 - agRem5))

        cdxValLabel.stringValue = String(format: "5h剩 %.0f%% · 周剩 %.0f%% · 券%d", cdxRem5, cdxRemW, cdxAvail)
        cdxBar.doubleValue = max(0, min(100, 100 - cdxRem5))

        wbValLabel.stringValue = String(format: "%.0f 积分 · 连签 %d 天", wbPts, wbDays)
        wbCheckinBtn.title = wbChecked ? "已签到" : "签到"
        wbCheckinBtn.isEnabled = !wbChecked

        volcValLabel.stringValue = String(format: "5h剩 %.0f%% · 7d剩 %.0f%%", volcRem5, volcRemW)
        volcBar.doubleValue = max(0, min(100, 100 - volcRem5))

        if pending > 0 {
            pendingBanner.stringValue = "⚠️ 有 \(pending) 条高危操作待审批，点击右上打开处理"
            pendingBanner.isHidden = false
        } else {
            pendingBanner.isHidden = true
        }
    }

    @objc private func handleOpenMain() {
        appDelegate?.closePopover()
        appDelegate?.showMainWindow()
    }

    @objc private func handleRefresh() {
        appDelegate?.pollStatusBarNow()
    }

    @objc private func handleQuit() {
        NSApplication.shared.terminate(nil)
    }

    @objc private func handleCheckin() {
        wbCheckinBtn.title = "打卡中..."
        wbCheckinBtn.isEnabled = false
        var req = URLRequest(url: URL(string: "http://127.0.0.1:5999/api/checkin/run")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("http://127.0.0.1:5999", forHTTPHeaderField: "Origin")
        req.httpBody = "{\"force\":true}".data(using: .utf8)
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.async {
                self?.appDelegate?.pollStatusBarNow()
            }
        }.resume()
    }

    @objc private func handleQuickDispatch() {
        let prompt = quickInput.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }
        quickInput.stringValue = ""
        dispatchFeedback.stringValue = "正在通过智能路由派发..."
        dispatchFeedback.isHidden = false

        var req = URLRequest(url: URL(string: "http://127.0.0.1:5999/api/agents/dispatch")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("http://127.0.0.1:5999", forHTTPHeaderField: "Origin")
        let body: [String: Any] = ["agent": "auto", "prompt": prompt]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            var msg = "已提交至后台执行"
            if let data = data,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let ok = json["success"] as? Bool, ok,
                   let run = json["run"] as? [String: Any],
                   let ag = run["agent"] as? String {
                    msg = "✅ 已派发给 \(ag.uppercased()) 后台执行"
                } else if let m = json["message"] as? String {
                    msg = "⚠️ \(m)"
                }
            }
            DispatchQueue.main.async {
                self?.dispatchFeedback.stringValue = msg
                self?.dispatchFeedback.isHidden = false
            }
        }.resume()
    }
}

// MARK: - Main Application Delegate
class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var loadingLabel: NSTextField!
    var statusItem: NSStatusItem!
    var popover: NSPopover!
    var popoverVC: CockpitPopoverViewController!
    var statusTimer: Timer?
    var retryCount = 0
    let maxRetries = 15
    let targetURL = URL(string: "http://127.0.0.1:5999")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMainMenu()
        setupStatusBarPopover()
        setupWindow()
        ensureServerAndLoad()
        startStatusBarPolling()
    }

    func setupStatusBarPopover() {
        popoverVC = CockpitPopoverViewController()
        popoverVC.appDelegate = self

        popover = NSPopover()
        popover.contentSize = NSSize(width: 336, height: 376)
        popover.behavior = .transient
        popover.animates = true
        popover.contentViewController = popoverVC

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let btn = statusItem.button {
            btn.title = "◈ Cockpit"
            btn.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
            btn.target = self
            btn.action = #selector(toggleStatusPopover(_:))
            btn.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
    }

    @objc func toggleStatusPopover(_ sender: NSStatusBarButton) {
        if let event = NSApp.currentEvent, event.type == .rightMouseUp {
            let menu = NSMenu()
            menu.addItem(withTitle: "打开驾驶舱主窗口", action: #selector(showMainWindow), keyEquivalent: "")
            menu.addItem(withTitle: "立即刷新配额", action: #selector(pollStatusBarNow), keyEquivalent: "")
            menu.addItem(NSMenuItem.separator())
            menu.addItem(withTitle: "退出 Agent Cockpit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
            statusItem.menu = menu
            statusItem.button?.performClick(nil)
            statusItem.menu = nil
            return
        }
        if popover.isShown {
            closePopover()
        } else if let btn = statusItem.button {
            pollStatusBarNow()
            popover.show(relativeTo: btn.bounds, of: btn, preferredEdge: .minY)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func closePopover() {
        if popover.isShown {
            popover.performClose(nil)
        }
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
            let wbChecked = (wb["today_checked_in"] as? Bool) ?? false

            let volc = root["volcengine"] as? [String: Any] ?? [:]
            let volc5 = (volc["five_hour_quota"] as? [String: Any])?["percent"] as? Double ?? 0
            let volcW = (volc["weekly_quota"] as? [String: Any])?["percent"] as? Double ?? 0
            let volcRem5 = max(0, 100 - volc5)
            let volcRemW = max(0, 100 - volcW)

            let mc = root["mission_control"] as? [String: Any] ?? [:]
            let mcSum = mc["summary"] as? [String: Any] ?? [:]
            let pending = (mcSum["pending_approvals"] as? Int) ?? 0

            let cb = root["circuit_breaker"] as? [String: Any] ?? [:]
            let cbTripped = (cb["triggered"] as? Bool) ?? false

            let prefix = (cbTripped || pending > 0) ? "▲" : "◈"
            let titleStr = String(format: "%@ AG %.0f%% · CDX %.0f%%", prefix, agRem5, cdxRem5)

            DispatchQueue.main.async {
                self.statusItem.button?.title = titleStr
                self.popoverVC.updateMetrics(
                    agRem5: agRem5, agRemW: agRemW,
                    cdxRem5: cdxRem5, cdxRemW: cdxRemW, cdxAvail: cdxAvail,
                    wbPts: wbPts, wbDays: wbDays, wbChecked: wbChecked,
                    volcRem5: volcRem5, volcRemW: volcRemW,
                    pending: pending
                )
            }
        }.resume()
    }

    func setupMainMenu() {
        let mainMenu = NSMenu()

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

        let viewMenuItem = NSMenuItem()
        let viewMenu = NSMenu(title: "视图")
        viewMenu.addItem(withTitle: "刷新驾驶舱", action: #selector(reloadWebView), keyEquivalent: "r")
        let fullScreenItem = NSMenuItem(title: "进入全屏幕", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fullScreenItem.keyEquivalentModifierMask = [.command, .control]
        viewMenu.addItem(fullScreenItem)
        viewMenuItem.submenu = viewMenu
        mainMenu.addItem(viewMenuItem)

        NSApp.mainMenu = mainMenu
    }

    func setupWindow() {
        let initialRect = NSRect(x: 0, y: 0, width: 1260, height: 840)
        window = NSWindow(
            contentRect: initialRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.delegate = self
        window.center()
        window.title = "Agent Cockpit"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 920, height: 620)
        window.isOpaque = false
        window.backgroundColor = NSColor.windowBackgroundColor

        // Native macOS vibrancy backdrop under WebKit
        let visualBackdrop = NSVisualEffectView(frame: window.contentView!.bounds)
        visualBackdrop.autoresizingMask = [.width, .height]
        visualBackdrop.material = .underWindowBackground
        visualBackdrop.blendingMode = .behindWindow
        visualBackdrop.state = .active
        window.contentView?.addSubview(visualBackdrop)

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        window.contentView?.addSubview(webView)

        loadingLabel = NSTextField(frame: NSRect(x: (window.frame.width - 320) / 2, y: (window.frame.height - 60) / 2, width: 320, height: 60))
        loadingLabel.isEditable = false
        loadingLabel.isSelectable = false
        loadingLabel.isBezeled = false
        loadingLabel.drawsBackground = false
        loadingLabel.alignment = .center
        loadingLabel.font = NSFont.systemFont(ofSize: 14, weight: .medium)
        loadingLabel.textColor = NSColor.secondaryLabelColor
        loadingLabel.stringValue = "正在连接 Agent Cockpit 本地服务..."
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
        URLSession.shared.dataTask(with: request) { _, response, _ in
            if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 {
                completion(true)
            } else {
                completion(false)
            }
        }.resume()
    }

    func locateProjectDirectory() -> String {
        let bundlePath = Bundle.main.bundleURL
        let candidateSameDir = bundlePath.deletingLastPathComponent().path
        if FileManager.default.fileExists(atPath: "\(candidateSameDir)/server.py") {
            return candidateSameDir
        }
        let candidateParentDir = bundlePath.deletingLastPathComponent().deletingLastPathComponent().path
        if FileManager.default.fileExists(atPath: "\(candidateParentDir)/server.py") {
            return candidateParentDir
        }
        let internalBackend = bundlePath.appendingPathComponent("Contents/Resources/backend").path
        if FileManager.default.fileExists(atPath: "\(internalBackend)/server.py") {
            return internalBackend
        }
        let defaultRepoDir = NSString(string: "~/Documents/08_个人库/Ai-Usage").expandingTildeInPath
        if FileManager.default.fileExists(atPath: "\(defaultRepoDir)/server.py") {
            return defaultRepoDir
        }
        return candidateSameDir
    }

    func startLocalServer() {
        let projectDir = locateProjectDirectory()
        let startScript = "\(projectDir)/start.sh"
        var env = ProcessInfo.processInfo.environment
        let home = NSHomeDirectory()
        let extraPaths = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        if let existingPath = env["PATH"], !existingPath.isEmpty {
            env["PATH"] = "\(extraPaths):\(existingPath)"
        } else {
            env["PATH"] = extraPaths
        }
        env["HOME"] = home

        if FileManager.default.isExecutableFile(atPath: startScript) {
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/bin/bash")
            proc.arguments = [startScript, "--daemon"]
            proc.currentDirectoryURL = URL(fileURLWithPath: projectDir)
            proc.environment = env
            try? proc.run()
        } else {
            let proc = Process()
            let pyBin = FileManager.default.isExecutableFile(atPath: "/opt/homebrew/bin/python3") ? "/opt/homebrew/bin/python3" : "/usr/bin/python3"
            proc.executableURL = URL(fileURLWithPath: pyBin)
            proc.arguments = ["\(projectDir)/server.py"]
            proc.currentDirectoryURL = URL(fileURLWithPath: projectDir)
            proc.environment = env
            try? proc.run()
        }
    }

    func pollUntilServerReady() {
        if retryCount >= maxRetries {
            DispatchQueue.main.async {
                self.loadingLabel.stringValue = "后台服务启动超时，请在终端运行 ./start.sh 检查"
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
