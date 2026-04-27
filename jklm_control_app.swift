import AppKit
import Foundation

let projectDir = "/Users/raphacara/VSCode/jklm"
let settingsPath = "\(projectDir)/jklm_settings.json"
let serverScript = "\(projectDir)/jklm_local_server.py"
let serverHealthURL = URL(string: "http://127.0.0.1:8765/health")!
let serverShutdownURL = URL(string: "http://127.0.0.1:8765/shutdown")!
let ollamaHealthURL = URL(string: "http://127.0.0.1:11434/api/tags")!
let defaultModel = "qwen2.5:3b-instruct-q3_K_M"
let nativeLogPath = "/tmp/jklm-bot-native.log"
let launchPath = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

func nativeLog(_ message: String) {
    let line = "[\(Date())] \(message)\n"
    if let data = line.data(using: .utf8) {
        if FileManager.default.fileExists(atPath: nativeLogPath),
           let handle = try? FileHandle(forWritingTo: URL(fileURLWithPath: nativeLogPath)) {
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
            try? handle.close()
        } else {
            try? data.write(to: URL(fileURLWithPath: nativeLogPath))
        }
    }
}

func processEnvironment() -> [String: String] {
    var environment = ProcessInfo.processInfo.environment
    environment["PATH"] = launchPath
    if environment["HOME"] == nil || environment["HOME"]?.isEmpty == true {
        environment["HOME"] = NSHomeDirectory()
    }
    if environment["USER"] == nil || environment["USER"]?.isEmpty == true {
        environment["USER"] = NSUserName()
    }
    if environment["LOGNAME"] == nil || environment["LOGNAME"]?.isEmpty == true {
        environment["LOGNAME"] = NSUserName()
    }
    if environment["TMPDIR"] == nil || environment["TMPDIR"]?.isEmpty == true {
        environment["TMPDIR"] = NSTemporaryDirectory()
    }
    environment["PYTHONUNBUFFERED"] = "1"
    return environment
}

func runSelfTests() -> Int32 {
    let environment = processEnvironment()
    let requiredKeys = ["PATH", "HOME", "USER", "LOGNAME", "TMPDIR"]
    var failed = false
    for key in requiredKeys {
        if environment[key]?.isEmpty != false {
            print("FAIL missing environment key: \(key)")
            failed = true
        }
    }
    if environment["PATH"]?.contains("/usr/bin") != true {
        print("FAIL PATH does not contain /usr/bin")
        failed = true
    }
    if environment["PYTHONUNBUFFERED"] != "1" {
        print("FAIL PYTHONUNBUFFERED is not set")
        failed = true
    }
    if !FileManager.default.fileExists(atPath: settingsPath) {
        print("FAIL missing settings: \(settingsPath)")
        failed = true
    }
    if !FileManager.default.fileExists(atPath: serverScript) {
        print("FAIL missing server: \(serverScript)")
        failed = true
    }
    let sample = Data("""
    {"models":[{"name":"gemma3:12b"},{"name":"qwen2.5:3b-instruct-q3_K_M"}]}
    """.utf8)
    let parsedModels = parseOllamaModels(from: sample)
    if parsedModels != Set(["gemma3:12b", "qwen2.5:3b-instruct-q3_K_M"]) {
        print("FAIL Ollama model parser")
        failed = true
    }
    if failed {
        return 1
    }
    print("OK jklm_control_app.swift self-tests")
    return 0
}

func parseOllamaModels(from data: Data) -> Set<String> {
    guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let models = json["models"] as? [[String: Any]] else {
        return []
    }
    return Set(models.compactMap { model in
        if let name = model["name"] as? String, !name.isEmpty {
            return name
        }
        if let name = model["model"] as? String, !name.isEmpty {
            return name
        }
        return nil
    })
}

final class LuxuryButton: NSButton {
    private let enabledBackground: NSColor
    private let disabledBackground: NSColor
    private let enabledText: NSColor
    private let disabledText: NSColor

    init(title: String, background: NSColor, textColor: NSColor, target: AnyObject?, action: Selector?) {
        self.enabledBackground = background
        self.disabledBackground = NSColor(calibratedRed: 0.13, green: 0.15, blue: 0.20, alpha: 1)
        self.enabledText = textColor
        self.disabledText = NSColor(calibratedRed: 0.48, green: 0.51, blue: 0.58, alpha: 1)
        super.init(frame: .zero)
        self.title = title
        self.target = target
        self.action = action
        self.isBordered = false
        self.bezelStyle = .regularSquare
        self.font = NSFont.systemFont(ofSize: 12, weight: .bold)
        self.wantsLayer = true
        self.layer?.cornerRadius = 10
        self.layer?.borderWidth = 1
        updateAppearance()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var isEnabled: Bool {
        didSet {
            updateAppearance()
        }
    }

    override var isHighlighted: Bool {
        didSet {
            updateAppearance()
        }
    }

    private func updateAppearance() {
        let background = isEnabled ? enabledBackground : disabledBackground
        let alpha: CGFloat = isHighlighted && isEnabled ? 0.78 : 1
        layer?.backgroundColor = background.withAlphaComponent(alpha).cgColor
        layer?.borderColor = background.highlight(withLevel: 0.18)?.cgColor ?? background.cgColor
        attributedTitle = NSAttributedString(
            string: title,
            attributes: [
                .foregroundColor: isEnabled ? enabledText : disabledText,
                .font: NSFont.systemFont(ofSize: 12, weight: .bold),
            ]
        )
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var startButton: NSButton!
    private var stopButton: NSButton!
    private var stopOllamaCheckbox: NSButton!
    private var mainStatus: NSTextField!
    private var ollamaStatus: NSTextField!
    private var modelStatus: NSTextField!
    private var serverStatus: NSTextField!
    private var modelLabel: NSTextField!
    private var terminal: NSTextView!
    private var openSiteButton: NSButton!
    private var ollamaProcess: Process?
    private var serverProcess: Process?
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        nativeLog("applicationDidFinishLaunching")
        buildUI()
        refreshStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            self?.refreshStatus()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func buildUI() {
        nativeLog("buildUI start")
        let frame = NSRect(x: 0, y: 0, width: 760, height: 560)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "JKLM bot"
        window.center()
        window.backgroundColor = NSColor(calibratedRed: 0.043, green: 0.051, blue: 0.071, alpha: 1)

        let content = NSView(frame: frame)
        window.contentView = content

        let title = label("JKLM Control", size: 28, weight: .bold, color: .white)
        title.frame = NSRect(x: 28, y: 508, width: 400, height: 34)
        content.addSubview(title)

        let subtitle = label("Local launcher for Ollama and the JKLM bot server", size: 12, weight: .regular, color: muted())
        subtitle.frame = NSRect(x: 29, y: 486, width: 500, height: 20)
        content.addSubview(subtitle)

        openSiteButton = button(
            "Open JKLM.fun",
            x: 596,
            y: 500,
            width: 136,
            height: 34,
            background: NSColor(calibratedRed: 0.18, green: 0.37, blue: 0.74, alpha: 1),
            textColor: .white,
            action: #selector(openSiteClicked)
        )
        content.addSubview(openSiteButton)

        let left = panel(NSRect(x: 28, y: 28, width: 270, height: 432))
        content.addSubview(left)

        let statusTitle = label("STATUS", size: 11, weight: .bold, color: gold())
        statusTitle.frame = NSRect(x: 18, y: 390, width: 200, height: 18)
        left.addSubview(statusTitle)

        ollamaStatus = statusRow("Ollama: inconnu", y: 342, in: left)
        modelStatus = statusRow("Modele: inconnu", y: 302, in: left)
        serverStatus = statusRow("Serveur JKLM: inconnu", y: 262, in: left)

        let line = NSBox(frame: NSRect(x: 18, y: 232, width: 234, height: 1))
        line.boxType = .custom
        line.borderColor = lineColor()
        line.fillColor = lineColor()
        left.addSubview(line)

        let modelTitle = label("Modele configure", size: 11, weight: .bold, color: muted())
        modelTitle.frame = NSRect(x: 18, y: 198, width: 220, height: 18)
        left.addSubview(modelTitle)
        modelLabel = label(readModel(), size: 12, weight: .regular, color: .white)
        modelLabel.frame = NSRect(x: 18, y: 152, width: 234, height: 44)
        modelLabel.lineBreakMode = .byWordWrapping
        modelLabel.maximumNumberOfLines = 2
        left.addSubview(modelLabel)

        stopOllamaCheckbox = NSButton(checkboxWithTitle: "Stopper Ollama avec Stop", target: nil, action: nil)
        stopOllamaCheckbox.frame = NSRect(x: 14, y: 112, width: 230, height: 24)
        stopOllamaCheckbox.state = .on
        stopOllamaCheckbox.contentTintColor = .white
        left.addSubview(stopOllamaCheckbox)

        startButton = button(
            "Start",
            y: 64,
            background: NSColor(calibratedRed: 0.22, green: 0.68, blue: 0.43, alpha: 1),
            textColor: .white,
            action: #selector(startClicked)
        )
        left.addSubview(startButton)
        stopButton = button(
            "Stop",
            y: 18,
            background: NSColor(calibratedRed: 0.82, green: 0.23, blue: 0.25, alpha: 1),
            textColor: .white,
            action: #selector(stopClicked)
        )
        left.addSubview(stopButton)

        mainStatus = label("Pret", size: 12, weight: .regular, color: muted())
        mainStatus.frame = NSRect(x: 28, y: 462, width: 704, height: 20)
        content.addSubview(mainStatus)

        let right = panel(NSRect(x: 316, y: 28, width: 416, height: 432))
        content.addSubview(right)
        let terminalTitle = label("LIVE BOT", size: 11, weight: .bold, color: gold())
        terminalTitle.frame = NSRect(x: 18, y: 390, width: 200, height: 18)
        right.addSubview(terminalTitle)

        let scroll = NSScrollView(frame: NSRect(x: 18, y: 18, width: 380, height: 358))
        scroll.hasVerticalScroller = true
        scroll.borderType = .noBorder
        scroll.drawsBackground = true
        scroll.backgroundColor = NSColor(calibratedRed: 0.031, green: 0.039, blue: 0.059, alpha: 1)
        terminal = NSTextView(frame: scroll.bounds)
        terminal.isEditable = false
        terminal.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        terminal.textColor = .white
        terminal.backgroundColor = scroll.backgroundColor
        terminal.textContainerInset = NSSize(width: 10, height: 10)
        scroll.documentView = terminal
        right.addSubview(scroll)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        nativeLog("buildUI done")
    }

    private func label(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor) -> NSTextField {
        let field = NSTextField(labelWithString: text)
        field.font = NSFont.systemFont(ofSize: size, weight: weight)
        field.textColor = color
        return field
    }

    private func panel(_ frame: NSRect) -> NSView {
        let view = NSView(frame: frame)
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor(calibratedRed: 0.071, green: 0.082, blue: 0.114, alpha: 1).cgColor
        view.layer?.borderColor = lineColor().cgColor
        view.layer?.borderWidth = 1
        view.layer?.cornerRadius = 14
        return view
    }

    private func statusRow(_ text: String, y: CGFloat, in parent: NSView) -> NSTextField {
        let dot = NSView(frame: NSRect(x: 20, y: y + 5, width: 10, height: 10))
        dot.wantsLayer = true
        dot.layer?.cornerRadius = 5
        dot.layer?.backgroundColor = amber().cgColor
        parent.addSubview(dot)

        let field = label(text, size: 12, weight: .regular, color: .white)
        field.frame = NSRect(x: 40, y: y, width: 210, height: 22)
        parent.addSubview(field)
        field.identifier = NSUserInterfaceItemIdentifier(rawValue: "dot:\(text)")
        field.tag = Int(bitPattern: Unmanaged.passUnretained(dot).toOpaque())
        return field
    }

    private func button(_ title: String, y: CGFloat, background: NSColor, textColor: NSColor, action: Selector) -> NSButton {
        button(title, x: 18, y: y, width: 234, height: 36, background: background, textColor: textColor, action: action)
    }

    private func button(
        _ title: String,
        x: CGFloat,
        y: CGFloat,
        width: CGFloat,
        height: CGFloat,
        background: NSColor,
        textColor: NSColor,
        action: Selector
    ) -> NSButton {
        let button = LuxuryButton(title: title, background: background, textColor: textColor, target: self, action: action)
        button.frame = NSRect(x: x, y: y, width: width, height: height)
        return button
    }

    @objc private func startClicked() {
        setBusy(true, "Demarrage en cours...")
        DispatchQueue.global(qos: .userInitiated).async { self.startAll() }
    }

    @objc private func stopClicked() {
        setBusy(true, "Arret en cours...")
        DispatchQueue.global(qos: .userInitiated).async { self.stopAll() }
    }

    @objc private func openSiteClicked() {
        if let url = URL(string: "https://jklm.fun") {
            NSWorkspace.shared.open(url)
        }
    }

    private func startAll() {
        let model = readModel()
        updateModel(model)
        clearLiveActivity()

        guard let ollama = ollamaPath() else {
            setStatus(ollamaStatus, "Ollama: introuvable", bad())
            finish("Ollama introuvable.")
            return
        }

        setStatus(ollamaStatus, "Ollama: verification", amber())
        if !urlOK(ollamaHealthURL) {
            ollamaProcess = launchProcess(ollama, ["serve"], prefix: "ollama")
            waitUntil(timeout: 15) { urlOK(ollamaHealthURL) }
        }

        guard urlOK(ollamaHealthURL) else {
            setStatus(ollamaStatus, "Ollama: offline", bad())
            finish("Ollama ne repond pas.")
            return
        }
        setStatus(ollamaStatus, "Ollama: online", good())

        setStatus(modelStatus, "Modele: verification", amber())
        guard let models = fetchOllamaModels() else {
            setStatus(modelStatus, "Modele: erreur", bad())
            finish("Impossible de verifier le modele.")
            return
        }
        guard models.contains(model) else {
            log("Modele manquant: \(model)")
            log("Installe-le avec: ollama pull \(model)")
            setStatus(modelStatus, "Modele: manquant", bad())
            finish("Modele manquant.")
            return
        }
        setStatus(modelStatus, "Modele: \(model)", good())

        setStatus(serverStatus, "Serveur JKLM: verification", amber())
        if urlOK(serverHealthURL) {
            setStatus(serverStatus, "Serveur JKLM: online", good())
            finish("Tout est pret. Ouvre une room JKLM.")
            return
        }

        let python = pythonPath()
        serverProcess = launchProcess(python, ["-u", serverScript], prefix: "server")
        waitUntil(timeout: 20) { urlOK(serverHealthURL) }

        if urlOK(serverHealthURL) {
            setStatus(serverStatus, "Serveur JKLM: online", good())
            finish("Tout est pret. Ouvre une room JKLM.")
        } else {
            setStatus(serverStatus, "Serveur JKLM: offline", bad())
            finish("Le serveur JKLM n'a pas demarre.")
        }
    }

    private func stopAll() {
        if urlOK(serverHealthURL) {
            var request = URLRequest(url: serverShutdownURL)
            request.httpMethod = "POST"
            request.httpBody = Data("{}".utf8)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            _ = syncRequest(request)
        }

        if let process = serverProcess, process.isRunning {
            process.terminate()
        }
        waitUntil(timeout: 5) { !urlOK(serverHealthURL) }
        setStatus(serverStatus, urlOK(serverHealthURL) ? "Serveur JKLM: online" : "Serveur JKLM: offline", urlOK(serverHealthURL) ? good() : bad())

        if stopOllamaCheckbox.state == .on {
            if let process = ollamaProcess, process.isRunning {
                process.terminate()
            }
            if urlOK(ollamaHealthURL) {
                _ = run("/usr/bin/pkill", ["-f", "ollama serve"])
                Thread.sleep(forTimeInterval: 1.0)
            }
            let online = urlOK(ollamaHealthURL)
            setStatus(ollamaStatus, online ? "Ollama: online" : "Ollama: offline", online ? good() : bad())
        }

        finish("Arret termine.")
    }

    private func refreshStatus() {
        let model = readModel()
        updateModel(model)
        let ollamaOnline = urlOK(ollamaHealthURL)
        let serverOnline = urlOK(serverHealthURL)
        setStatus(ollamaStatus, ollamaOnline ? "Ollama: online" : "Ollama: offline", ollamaOnline ? good() : bad())
        setStatus(serverStatus, serverOnline ? "Serveur JKLM: online" : "Serveur JKLM: offline", serverOnline ? good() : bad())
    }

    private func readModel() -> String {
        guard let data = FileManager.default.contents(atPath: settingsPath),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let model = json["model"] as? String,
              !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return defaultModel
        }
        return model.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func ollamaPath() -> String? {
        for path in ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama"] {
            if FileManager.default.isExecutableFile(atPath: path) { return path }
        }
        let result = run("/usr/bin/which", ["ollama"])
        return result.code == 0 ? result.output.trimmingCharacters(in: .whitespacesAndNewlines) : nil
    }

    private func pythonPath() -> String {
        let venv = "\(projectDir)/.venv/bin/python"
        if FileManager.default.isExecutableFile(atPath: venv) { return venv }
        return "/usr/bin/python3"
    }

    private func launchProcess(_ path: String, _ args: [String], prefix: String) -> Process {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = args
        process.currentDirectoryURL = URL(fileURLWithPath: projectDir)
        process.environment = processEnvironment()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
                guard !line.isEmpty else { continue }
                if prefix == "server" {
                    self?.logServerActivity(String(line))
                }
            }
        }
        do {
            try process.run()
        } catch {
            log("Erreur lancement \(path): \(error.localizedDescription)")
        }
        return process
    }

    private func run(_ path: String, _ args: [String]) -> (code: Int32, output: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = args
        process.currentDirectoryURL = URL(fileURLWithPath: projectDir)
        process.environment = processEnvironment()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "")
        } catch {
            return (1, error.localizedDescription)
        }
    }

    private func urlOK(_ url: URL) -> Bool {
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.5
        guard let status = syncRequest(request)?.statusCode else {
            return false
        }
        return status >= 200 && status < 300
    }

    private func fetchOllamaModels() -> Set<String>? {
        var request = URLRequest(url: ollamaHealthURL)
        request.timeoutInterval = 2.0
        guard let response = syncDataRequest(request),
              response.statusCode >= 200,
              response.statusCode < 300 else {
            return nil
        }
        return parseOllamaModels(from: response.data)
    }

    private func syncRequest(_ request: URLRequest) -> HTTPURLResponse? {
        let semaphore = DispatchSemaphore(value: 0)
        var response: HTTPURLResponse?
        URLSession.shared.dataTask(with: request) { _, res, _ in
            response = res as? HTTPURLResponse
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 2.0)
        return response
    }

    private func syncDataRequest(_ request: URLRequest) -> (statusCode: Int, data: Data)? {
        let semaphore = DispatchSemaphore(value: 0)
        var result: (statusCode: Int, data: Data)?
        URLSession.shared.dataTask(with: request) { data, res, _ in
            if let http = res as? HTTPURLResponse {
                result = (http.statusCode, data ?? Data())
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 2.5)
        return result
    }

    private func waitUntil(timeout: TimeInterval, predicate: () -> Bool) {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if predicate() { return }
            Thread.sleep(forTimeInterval: 0.5)
        }
    }

    private func setBusy(_ busy: Bool, _ text: String) {
        DispatchQueue.main.async {
            self.startButton.isEnabled = !busy
            self.stopButton.isEnabled = !busy
            self.mainStatus.stringValue = text
        }
    }

    private func finish(_ text: String) {
        DispatchQueue.main.async {
            self.startButton.isEnabled = true
            self.stopButton.isEnabled = true
            self.mainStatus.stringValue = text
        }
    }

    private func setStatus(_ field: NSTextField, _ text: String, _ color: NSColor) {
        DispatchQueue.main.async {
            field.stringValue = text
            if let dot = field.superview?.subviews.first(where: { Int(bitPattern: Unmanaged.passUnretained($0).toOpaque()) == field.tag }) {
                dot.layer?.backgroundColor = color.cgColor
            }
        }
    }

    private func updateModel(_ model: String) {
        DispatchQueue.main.async {
            self.modelLabel.stringValue = model
        }
    }

    private func log(_ message: String) {
        DispatchQueue.main.async {
            let formatter = DateFormatter()
            formatter.dateFormat = "HH:mm:ss"
            let line = "[\(formatter.string(from: Date()))] \(message)\n"
            self.terminal.string += line
            self.terminal.scrollToEndOfDocument(nil)
        }
    }

    private func logServerActivity(_ line: String) {
        let cleaned = stripAnsi(line).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }

        if cleaned.hasPrefix("tour  ") {
            let syllable = value(after: "syllabe=", in: cleaned) ?? "?"
            let mode = value(after: "mode=", in: cleaned) ?? "normal"
            let language = value(after: "langue=", in: cleaned) ?? "?"
            log("Syllabe: \(syllable) | \(language) | \(mode)")
            return
        }

        if cleaned.contains("  test   ") {
            log(cleaned.replacingOccurrences(of: "  test   ", with: "  Essai: "))
            return
        }

        if cleaned.contains("     rejet  ") {
            log(cleaned.replacingOccurrences(of: "     rejet  ", with: "  Rejet: "))
            return
        }

        if cleaned.contains("     garde  ") {
            log(cleaned.replacingOccurrences(of: "     garde  ", with: "  Candidat: "))
            return
        }

        if cleaned.hasPrefix("choisi  ") {
            log(cleaned.replacingOccurrences(of: "choisi  ", with: "Mot retenu: "))
            return
        }

        if cleaned.hasPrefix("ok     mot retenu:") {
            log(cleaned.replacingOccurrences(of: "ok     mot retenu:", with: "Mot final:"))
            return
        }

        if cleaned.hasPrefix("echec  ") {
            log(cleaned.replacingOccurrences(of: "echec  ", with: "Echec: "))
            return
        }

        if cleaned.hasPrefix("aucun   ") {
            log(cleaned.replacingOccurrences(of: "aucun   ", with: "Aucun: "))
            return
        }

        if cleaned.hasPrefix("propo  ") {
            log(cleaned.replacingOccurrences(of: "propo  ", with: "Propose: "))
            return
        }

        if cleaned.hasPrefix("frappe ") {
            log(cleaned.replacingOccurrences(of: "frappe ", with: "Frappe: "))
            return
        }

        if cleaned.hasPrefix("envoi  ") {
            log(cleaned.replacingOccurrences(of: "envoi  ", with: "Envoye: "))
            return
        }

        if cleaned.hasPrefix("valide ") {
            log(cleaned.replacingOccurrences(of: "valide ", with: "Valide: "))
            return
        }

        if cleaned.hasPrefix("refus  ") {
            log(cleaned.replacingOccurrences(of: "refus  ", with: "Refuse: "))
            return
        }

        if cleaned.hasPrefix("retry  ") {
            log(cleaned.replacingOccurrences(of: "retry  ", with: "Nouvel essai: "))
            return
        }

        if cleaned.hasPrefix("stop   ") {
            log(cleaned.replacingOccurrences(of: "stop   ", with: "Stop: "))
        }
    }

    private func stripAnsi(_ value: String) -> String {
        value.replacingOccurrences(
            of: #"\u{001B}\[[0-9;]*m"#,
            with: "",
            options: .regularExpression
        )
    }

    private func value(after marker: String, in line: String) -> String? {
        guard let range = line.range(of: marker) else { return nil }
        let rest = line[range.upperBound...]
        return rest.split(separator: " ").first.map(String.init)
    }

    private func clearLiveActivity() {
        DispatchQueue.main.async {
            self.terminal.string = ""
        }
    }

    private func gold() -> NSColor { NSColor(calibratedRed: 0.94, green: 0.78, blue: 0.42, alpha: 1) }
    private func muted() -> NSColor { NSColor(calibratedRed: 0.60, green: 0.64, blue: 0.70, alpha: 1) }
    private func amber() -> NSColor { NSColor(calibratedRed: 0.96, green: 0.72, blue: 0.36, alpha: 1) }
    private func good() -> NSColor { NSColor(calibratedRed: 0.40, green: 0.83, blue: 0.57, alpha: 1) }
    private func bad() -> NSColor { NSColor(calibratedRed: 1.00, green: 0.42, blue: 0.42, alpha: 1) }
    private func lineColor() -> NSColor { NSColor(calibratedRed: 0.16, green: 0.19, blue: 0.25, alpha: 1) }
}

if CommandLine.arguments.contains("--self-test") {
    exit(runSelfTests())
}

let app = NSApplication.shared
nativeLog("native main start")
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
