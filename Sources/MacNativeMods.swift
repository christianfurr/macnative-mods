import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ModTarget: Hashable, Identifiable, Sendable {
    let url: URL
    let bundleID: String
    let name: String
    let dataFolder: String
    let version: String

    var id: URL { url }

    init?(_ url: URL) {
        let path = url.standardizedFileURL.resolvingSymlinksInPath()
        guard let bundle = Bundle(url: path), let id = bundle.bundleIdentifier,
              let version = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String else { return nil }
        switch id {
        case "org.macnativegames.botw": (name, dataFolder) = ("Breath of the Wild", "BotW")
        case "org.macnativegames.totk": (name, dataFolder) = ("Tears of the Kingdom", "TOTK")
        case "org.macnativegames.ot0": (name, dataFolder) = ("Octopath Traveler 0", "OT0")
        default: return nil
        }
        self.url = path
        self.bundleID = id
        self.version = version
    }
}

@main
struct MacNativeModsApp: App {
    var body: some Scene {
        WindowGroup("MacNative Mods") { ModManagerWindow() }
            .defaultSize(width: 1100, height: 680)
            .windowResizability(.contentMinSize)
    }
}

private struct ModManagerWindow: View {
    @AppStorage("checkout") private var checkout = ""
    @AppStorage("selectedGame") private var selectedPath = ""
    @AppStorage("addedGames") private var addedGames = ""
    @AppStorage("seenSetup") private var seenSetup = false
    @State private var games: [ModTarget] = []
    @State private var selection: URL?
    @State private var model: ModsModel?
    @State private var selectionError = false
    @State private var openedBNPs: [URL] = []
    @State private var needsBNPGame = false
    @State private var showSetup = false

    var body: some View {
        NavigationSplitView {
            ScrollView {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Games")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 9).padding(.bottom, 3)
                        .accessibilityAddTraits(.isHeader)
                    ForEach(games) { game in
                        Button { selection = game.id } label: {
                            HStack(spacing: 9) {
                                Image(systemName: "gamecontroller").frame(width: 17)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(game.name).font(.system(size: 12, weight: .medium))
                                    Text(game.version).font(.caption2).foregroundStyle(.secondary)
                                }
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 9).padding(.vertical, 7)
                            .contentShape(Rectangle())
                            .background(selection == game.id ? Color.accentColor.opacity(0.18) : Color.clear,
                                        in: RoundedRectangle(cornerRadius: 6))
                        }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(selection == game.id ? .isSelected : [])
                    }
                    if let model {
                        Divider().padding(.vertical, 10)
                        ModsProfileSidebar(model: model).id(model.target.id)
                    }
                }
                .padding(.horizontal, 10).padding(.vertical, 14)
            }
            .navigationSplitViewColumnWidth(min: 176, ideal: 197, max: 250)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 7) {
                    Divider()
                    Button("Add Game…", systemImage: "plus") { chooseGame() }
                    Button("Setup…", systemImage: "gearshape") { showSetup = true }
                }
                .buttonStyle(.plain)
                .font(.system(size: 12))
                .padding(11)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.bar)
            }
        } detail: {
            if let model {
                ModsView(model: model, openedBNPs: $openedBNPs).id(ObjectIdentifier(model))
            } else {
                ContentUnavailableView {
                    Label("Add a game", systemImage: "gamecontroller")
                } description: {
                    Text("Choose an installed MacNativeGames app to get started.")
                } actions: {
                    Button("Add Game…", action: chooseGame).buttonStyle(.borderedProminent)
                }
            }
        }
        .frame(minWidth: 940, minHeight: 545)
        .preferredColorScheme(.dark)
        .task {
            scan()
            if !seenSetup { showSetup = true }
        }
        .onChange(of: selection, initial: true) { _, url in
            if let url { selectedPath = url.path }
            openLibrary()
        }
        .onChange(of: checkout) { openLibrary() }
        .onOpenURL(perform: openBNP)
        .sheet(isPresented: $showSetup, onDismiss: { seenSetup = true }) {
            ModsSetupView(model: model, chooseGame: chooseGame, chooseCheckout: chooseCheckout) {
                model?.refresh(keepMessage: true)
            }
            .id(model.map(ObjectIdentifier.init))
        }
        .alert("Choose a supported game", isPresented: $selectionError) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Select a MacNativeGames build of Breath of the Wild, Tears of the Kingdom, or Octopath Traveler 0.")
        }
        .alert("Breath of the Wild 1.6.0 required", isPresented: $needsBNPGame) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Add a MacNativeGames Breath of the Wild 1.6.0 app before opening a Switch BNP pack.")
        }
    }

    private func openBNP(_ url: URL) {
        guard url.isFileURL, url.pathExtension.lowercased() == "bnp" else { return }
        if games.isEmpty { scan() }
        let matches = games.filter { $0.dataFolder == "BotW" && $0.version == "1.6.0" }
        guard let game = matches.first(where: { $0.id == selection }) ?? matches.first else {
            needsBNPGame = true
            return
        }
        selection = game.id
        if !openedBNPs.contains(url) { openedBNPs.append(url) }
    }

    private func openLibrary() {
        model = games.first(where: { $0.id == selection }).map { ModsModel(target: $0, checkout: checkout) }
    }

    private func scan() {
        let folders = [URL(fileURLWithPath: "/Applications"),
                       FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications")]
        let localApps = folders.flatMap {
            (try? FileManager.default.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)) ?? []
        }
        let chosen = addedGames.split(separator: "\n").map { URL(fileURLWithPath: String($0)) }
        games = Array(Set((localApps.filter { $0.pathExtension == "app" } + chosen).compactMap(ModTarget.init)))
            .sorted { ($0.name, $0.version, $0.url.path) < ($1.name, $1.version, $1.url.path) }
        selection = games.first { $0.url.path == selectedPath }?.id ?? games.first?.id
    }

    private func chooseGame() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.application]
        panel.prompt = "Add Game"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard let game = ModTarget(url), !game.url.path.contains("\n") else {
            selectionError = true
            return
        }
        if !addedGames.split(separator: "\n").contains(Substring(game.url.path)) {
            addedGames += game.url.path + "\n"
        }
        selectedPath = game.url.path
        scan()
    }

    private func chooseCheckout() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.prompt = "Choose Folder"
        if panel.runModal() == .OK, let url = panel.url { checkout = url.path }
    }
}

private struct ModsSetupView: View {
    let model: ModsModel?
    let chooseGame: () -> Void
    let chooseCheckout: () -> Void
    let refreshLibrary: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var game: SetupCheck?
    @State private var tools: SetupCheck?
    @State private var python: SetupCheck?
    @State private var hasPython = false
    @State private var checking = false
    @State private var checkID = UUID()

    private var ready: Bool { !checking && python?.ready == true && game?.ready == true && tools?.ready == true }

    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            Text("Set up MacNative Mods").font(.title2.bold())
            Text("Check what this Mac needs to manage mods for your selected game.")
                .foregroundStyle(.secondary)
            Divider()
            checkRow("Python 3.14", ready: python?.ready ?? hasPython,
                     detail: python?.detail ?? (hasPython ? "Python was found." : "Install Python 3.14, then check again.")) {
                if !(python?.ready ?? hasPython) {
                    Link("Install Python", destination: URL(string: "https://formulae.brew.sh/formula/python@3.14")!)
                }
            }
            checkRow("Game build", ready: game?.ready == true,
                     detail: game?.detail ?? model.map { "\($0.target.name) \($0.target.version). \(checking ? "Checking…" : "Waiting for Python.")" }
                        ?? "Select an installed MacNativeGames app.") {
                Button("Add Game…", action: chooseGame)
            }
            checkRow("MacNativeGames tools", ready: tools?.ready == true,
                     detail: tools?.detail ?? "Select a game and install Python to verify the tools.") {
                Button("Game tools folder…", action: chooseCheckout)
            }
            Divider()
            HStack {
                Button("Check Again") { checkID = UUID() }.disabled(checking)
                if checking { ProgressView().controlSize(.small) }
                Spacer()
                Button(ready ? "Continue" : "Close") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 510)
        .task(id: checkID) {
            await check()
            if !Task.isCancelled { refreshLibrary() }
        }
    }

    private func checkRow<Actions: View>(_ title: String, ready: Bool, detail: String,
                                        @ViewBuilder actions: () -> Actions) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: ready ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(ready ? Color.green : Color.secondary)
                .accessibilityLabel(ready ? "Ready" : "Needs checking")
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            actions().fixedSize()
        }
    }

    private func check() async {
        hasPython = ModsModel.hasPython
        python = nil
        game = nil
        tools = nil
        checking = hasPython && model != nil
        guard checking, let model else { return }
        do {
            let result = try await model.checkSetup()
            guard !Task.isCancelled else { return }
            python = result.setupPython
            game = result.setupGame
            tools = result.setupTools ?? SetupCheck(ready: false, detail: result.message)
        } catch {
            guard !Task.isCancelled else { return }
            tools = SetupCheck(ready: false, detail: error.localizedDescription)
        }
        checking = false
    }
}
