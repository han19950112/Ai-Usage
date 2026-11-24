import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var loadingLabel: NSTextField!
    var retryCount = 0
    let maxRetries = 15
    let targetURL = URL(string: "http://127.0.0.1:5999")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMainMenu()
        setupWindow()
        ensureServerAndLoad()
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
            proc.arguments = [startScript]
            proc.currentDirectoryURL = URL(fileURLWithPath: projectDir)
            try? proc.run()
        } else {
            // Direct python3 fallback
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            proc.arguments = ["\(projectDir)/server.py", "--daemon"]
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
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
