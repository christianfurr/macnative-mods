import AppKit
import Combine
import Foundation

struct ManagedMod: Decodable, Identifiable, Sendable {
    let id: String
    let name: String
    let enabled: Bool
    let valid: Bool
    let description: String?
    let detail: String
    let replaced: Int
    let added: Int
    let conflicts: [String]
    let dependencyIssues: [String]?

    enum CodingKeys: String, CodingKey {
        case id, name, enabled, valid, description, detail, replaced, added, conflicts
        case dependencyIssues = "dependency_issues"
    }
}

struct ModsReport: Decodable, Sendable {
    let ok: Bool
    let message: String
    let version: String?
    let canMakeDemos: Bool?
    let gameRunning: Bool?
    let pending: Bool?
    let appliedFiles: Int?
    let backup: String?
    let blockedReason: String?
    let mods: [ManagedMod]?
    let profiles: [String]?
    let selectedProfile: String?
    let dependencyBlocker: String?
    let mergedPaths: [String]?

    enum CodingKeys: String, CodingKey {
        case ok, message, version, pending, backup, mods, profiles
        case selectedProfile = "selected_profile"
        case dependencyBlocker = "dependency_blocker"
        case mergedPaths = "merged_paths"
        case canMakeDemos = "can_make_demos"
        case gameRunning = "game_running"
        case appliedFiles = "applied_files"
        case blockedReason = "blocked_reason"
    }
}

enum ModDirection: String, Sendable { case up, down }

struct FlamebladeStats: Sendable {
    let attack: Int?
    let durability: Int?
    let fireCapacity: Int?

    var arguments: [String] {
        var result = [String]()
        if let attack { result += ["--attack", String(attack)] }
        if let durability { result += ["--durability", String(durability)] }
        if let fireCapacity { result += ["--fire-capacity", String(fireCapacity)] }
        return result
    }
}

private enum ModsAction: Sendable {
    case status, importPack(URL, FlamebladeStats?), toggle(String, Bool), move(String, ModDirection), remove(String), apply, demos
    case createProfile(String, copy: Bool), selectProfile(String), renameProfile(String), deleteProfile(String), launch
    case importBNP([URL], name: String)
    case exportProfile(URL), importProfile(URL)
    case moveTo(String, anchor: String, after: Bool)

    var arguments: [String] {
        switch self {
        case .status: return ["status"]
        case .importPack(let url, let stats): return ["import", url.path] + (stats?.arguments ?? [])
        case .toggle(let id, let enabled): return ["toggle", id, enabled ? "on" : "off"]
        case .move(let id, let direction): return ["move", id, direction.rawValue]
        case .remove(let id): return ["remove", id]
        case .apply: return ["apply"]
        case .demos: return ["demos"]
        case .createProfile(let name, let copy): return ["profile-create"] + (copy ? ["--copy"] : []) + ["--", name]
        case .selectProfile(let name): return ["profile-select", "--", name]
        case .renameProfile(let name): return ["profile-rename", "--", name]
        case .deleteProfile(let name): return ["profile-delete", "--", name]
        case .launch: return ["prepare-launch"]
        case .importBNP(let urls, let name):
            return ["import-bnp"] + (name.isEmpty ? [] : ["--name=\(name)"]) + ["--"] + urls.map(\.path)
        case .exportProfile(let url): return ["profile-export", "--", url.path]
        case .importProfile(let url): return ["profile-import", "--", url.path]
        case .moveTo(let id, let anchor, let after): return ["move-to", id, anchor, after ? "after" : "before"]
        }
    }
    var activity: String {
        switch self {
        case .status: return "Checking the mod library…"
        case .importPack: return "Importing mod…"
        case .toggle: return "Updating mod selection…"
        case .move, .moveTo: return "Updating load order…"
        case .remove: return "Removing mod…"
        case .apply: return "Preparing mods for the next launch…"
        case .demos: return "Generating demo mods…"
        case .createProfile, .selectProfile, .renameProfile, .deleteProfile: return "Updating profiles…"
        case .launch: return "Preparing the game…"
        case .importBNP: return "Merging Switch BNP packs with BCML…"
        case .exportProfile: return "Exporting profile…"
        case .importProfile: return "Matching profile mods…"
        }
    }
    var isStatus: Bool { if case .status = self { return true }; return false }
}

private enum ModsToolError: LocalizedError {
    case missingHelper, missingPython, invalidResponse

    var errorDescription: String? {
        switch self {
        case .missingHelper: return "The mod manager is missing. Open a complete MacNative Mods app bundle."
        case .missingPython: return "Install Python 3.14 from the MacNativeGames setup before using Mods."
        case .invalidResponse: return "The mod manager returned an unreadable result. Refresh the library before trying again."
        }
    }
}

private struct ModsExecution: Sendable {
    let reply: ModsReport
    let snapshot: ModsReport?
}

private enum ModsTool {
    static let pythonPaths = ["/opt/homebrew/bin/python3.14", "/usr/local/bin/python3.14"]
    static let responseLimit = 8 * 1024 * 1024

    static func execute(_ action: ModsAction, helper: URL?, target: ModTarget, checkout: String) throws -> ModsExecution {
        let reply = try invoke(action, helper: helper, target: target, checkout: checkout)
        if reply.mods != nil { return ModsExecution(reply: reply, snapshot: reply) }
        if action.isStatus { return ModsExecution(reply: reply, snapshot: nil) }
        let status = try? invoke(.status, helper: helper, target: target, checkout: checkout)
        return ModsExecution(reply: reply, snapshot: status?.mods == nil ? nil : status)
    }

    private static func invoke(_ action: ModsAction, helper: URL?, target: ModTarget, checkout: String) throws -> ModsReport {
        let files = FileManager.default
        guard let helper, files.isReadableFile(atPath: helper.path) else { throw ModsToolError.missingHelper }
        guard let interpreter = pythonPaths.first(where: files.isExecutableFile(atPath:)) else { throw ModsToolError.missingPython }

        let selectedURLs: [URL]
        switch action {
        case .importPack(let url, _): selectedURLs = [url]
        case .exportProfile(let url), .importProfile(let url): selectedURLs = [url]
        case .importBNP(let urls, _): selectedURLs = urls
        default: selectedURLs = []
        }
        let scoped = selectedURLs.filter { $0.startAccessingSecurityScopedResource() }
        defer { scoped.forEach { $0.stopAccessingSecurityScopedResource() } }

        // Separate temporary files let the child write either stream without filling a pipe.
        let temporary = files.temporaryDirectory.appendingPathComponent("BOTWEditor-Mods-\(UUID().uuidString)", isDirectory: true)
        try files.createDirectory(at: temporary, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? files.removeItem(at: temporary) }
        let outputURL = temporary.appendingPathComponent("result.json")
        let errorURL = temporary.appendingPathComponent("stderr.txt")
        try Data().write(to: outputURL)
        try Data().write(to: errorURL)
        let output = try FileHandle(forWritingTo: outputURL)
        defer { try? output.close() }
        let errors = try FileHandle(forWritingTo: errorURL)
        defer { try? errors.close() }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: interpreter)
        process.arguments = ["-E", "-s", helper.path, "--app", target.url.path]
            + (checkout.isEmpty ? [] : ["--repo", checkout]) + action.arguments
        process.currentDirectoryURL = helper.deletingLastPathComponent()
        process.standardOutput = output
        process.standardError = errors
        process.standardInput = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()

        guard process.terminationReason == .exit,
              let size = try outputURL.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              (1...responseLimit).contains(size),
              let reply = try? JSONDecoder().decode(ModsReport.self, from: Data(contentsOf: outputURL)),
              process.terminationStatus == 0 || !reply.ok else { throw ModsToolError.invalidResponse }
        return reply
    }
}

@MainActor
final class ModsModel: ObservableObject {
    @Published private(set) var status: ModsReport?
    @Published private(set) var activity: String?
    @Published private(set) var message: String?
    @Published private(set) var failed = false
    @Published private(set) var current = false
    @Published private(set) var backupURL: URL?

    let target: ModTarget
    private let checkout: String
    private let helper: URL?
    private var queuedRefresh = false
    private var queuedImport: (URL, FlamebladeStats?)?

    init(target: ModTarget, checkout: String, helper: URL? = Bundle.main.url(forResource: "mods", withExtension: "py", subdirectory: "Mods")) {
        self.target = target
        self.checkout = checkout
        self.helper = helper
    }

    var mods: [ManagedMod] { status?.mods ?? [] }
    var profiles: [String] { status?.profiles ?? [] }
    var selectedProfile: String { status?.selectedProfile ?? "" }
    var mergedPaths: Set<String> { Set(status?.mergedPaths ?? []) }
    var busy: Bool { activity != nil }
    var canEdit: Bool { current && !busy }
    var blocker: String? {
        guard current else { return nil }
        if let reason = status?.blockedReason, !reason.isEmpty { return reason }
        if let reason = status?.dependencyBlocker { return reason }
        if status?.gameRunning == true, status?.pending == true { return "Quit the game before applying changes." }
        return nil
    }
    var canApply: Bool {
        canEdit && status?.pending == true && status?.gameRunning == false && blocker == nil
    }
    var canLaunch: Bool { canEdit && status?.gameRunning == false && blocker == nil }

    func refresh(keepMessage: Bool = false) { perform(.status, keepMessage: keepMessage) }
    func importPack(_ url: URL, stats: FlamebladeStats? = nil) {
        if busy { queuedImport = (url, stats) }
        else { perform(.importPack(url, stats)) }
    }
    func addDemos() { perform(.demos) }
    func importBNP(_ urls: [URL], name: String) { perform(.importBNP(urls, name: name)) }
    func exportProfile(_ url: URL) { perform(.exportProfile(url)) }
    func importProfile(_ url: URL) { perform(.importProfile(url)) }
    func createProfile(_ name: String, copy: Bool) { perform(.createProfile(name, copy: copy)) }
    func selectProfile(_ name: String) { perform(.selectProfile(name)) }
    func renameProfile(_ name: String) { perform(.renameProfile(name)) }
    func deleteSelectedProfile() { perform(.deleteProfile(selectedProfile)) }
    func launch() {
        guard canLaunch else { return }
        perform(.launch)
    }
    func toggle(_ mod: ManagedMod, enabled: Bool) {
        guard canEdit, mod.valid || !enabled else { return }
        perform(.toggle(mod.id, enabled))
    }
    func move(_ mod: ManagedMod, direction: ModDirection) {
        guard canEdit else { return }
        perform(.move(mod.id, direction))
    }
    func move(_ id: String, relativeTo anchor: String, after: Bool) -> Bool {
        guard canEdit, id != anchor, mods.contains(where: { $0.id == id }),
              mods.contains(where: { $0.id == anchor }) else { return false }
        perform(.moveTo(id, anchor: anchor, after: after))
        return true
    }
    func remove(_ mod: ManagedMod) {
        guard canEdit else { return }
        perform(.remove(mod.id))
    }
    func apply() {
        guard canApply else { return }
        perform(.apply)
    }

    private func perform(_ action: ModsAction, keepMessage: Bool = false) {
        if busy {
            if action.isStatus { queuedRefresh = true }
            return
        }
        activity = action.activity
        let helper = helper
        let target = target
        let checkout = checkout
        Task {
            let result = await Task.detached(priority: .userInitiated) {
                Result { try ModsTool.execute(action, helper: helper, target: target, checkout: checkout) }
            }.value
            switch result {
            case .success(let execution):
                accept(execution, action: action, keepMessage: keepMessage)
                if case .launch = action, execution.reply.ok, current {
                    await openGame()
                    queuedRefresh = true
                }
            case .failure(let error):
                current = false
                failed = true
                message = error.localizedDescription
            }
            activity = nil
            if let (url, stats) = queuedImport {
                queuedImport = nil
                importPack(url, stats: stats)
            } else if queuedRefresh {
                queuedRefresh = false
                refresh(keepMessage: true)
            }
        }
    }

    private func openGame() async {
        activity = "Opening \(target.name)…"
        do {
            let app = try await NSWorkspace.shared.openApplication(at: target.url,
                                                                   configuration: NSWorkspace.OpenConfiguration())
            failed = app.isTerminated
            message = failed ? "\(target.name) exited during launch." : "Opened \(target.name)."
        } catch {
            failed = true
            message = "Could not open \(target.name). \(error.localizedDescription)"
        }
    }

    private func accept(_ execution: ModsExecution, action: ModsAction, keepMessage: Bool) {
        current = execution.snapshot != nil
        if let snapshot = execution.snapshot { status = snapshot }
        if let backup = execution.reply.backup ?? execution.snapshot?.backup {
            backupURL = backupLocation(backup)
        }
        if !execution.reply.ok {
            failed = true
            message = execution.reply.message
        } else if !current {
            failed = true
            message = "\(execution.reply.message) Refresh the mod library to verify its current state."
        } else if !action.isStatus || !keepMessage {
            failed = false
            message = action.isStatus ? nil : execution.reply.message
        }
    }

    private func backupLocation(_ name: String) -> URL? {
        guard !name.isEmpty, name != ".", name != "..", !name.contains("/"), !name.contains("\\") else { return nil }
        let folder = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/MacNativeGames/\(target.dataFolder)/mods", isDirectory: true)
        let url = folder.appendingPathComponent(name, isDirectory: true)
        var directory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &directory), directory.boolValue else { return nil }
        return url
    }
}
