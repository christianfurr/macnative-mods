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
    @State private var games: [ModTarget] = []
    @State private var selection: URL?
    @State private var model: ModsModel?
    @State private var selectionError = false
    @State private var openedBNPs: [URL] = []
    @State private var needsBNPGame = false

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
                    Button("Game tools folder…", systemImage: "gearshape") { chooseCheckout() }
                        .help(checkout.isEmpty ? "Choose your MacNativeGames checkout folder." : checkout)
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
                ContentUnavailableView("Select a game", systemImage: "shippingbox",
                                       description: Text("Add a MacNativeGames app to manage its RomFS mods."))
            }
        }
        .frame(minWidth: 940, minHeight: 545)
        .preferredColorScheme(.dark)
        .task { scan() }
        .onChange(of: selection, initial: true) { _, url in
            if let url { selectedPath = url.path }
            openLibrary()
        }
        .onChange(of: checkout) { openLibrary() }
        .onOpenURL(perform: openBNP)
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
