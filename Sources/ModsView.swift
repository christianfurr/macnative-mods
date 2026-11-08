import AppKit
import CoreTransferable
import SwiftUI
import UniformTypeIdentifiers

struct ModsView: View {
    @ObservedObject var model: ModsModel
    @Binding var openedBNPs: [URL]
    @State private var selectedID: String?
    @State private var removal: ManagedMod?
    @State private var flamebladeImport: FlamebladeImport?
    @State private var search = ""
    @State private var libraryFilter: LibraryFilter = .all
    @State private var bnpBatch: BNPBatch?
    @State private var showShortcuts = false
    @State private var dragScope = UUID()
    @State private var dropLine: ModDropLine?
    @AppStorage("showModInspector") private var showInspector = true
    @FocusState private var focusedID: String?
    @FocusState private var searchFocused: Bool

    private enum LibraryFilter: String, CaseIterable { case all = "All Mods", enabled = "Enabled", conflicts = "Needs Attention" }

    private let bcmlGuide = URL(string: "https://github.com/NiceneNerd/BCML/blob/master/docs/export.md")!
    private var selected: ManagedMod? { model.mods.first { $0.id == selectedID } }
    private var supportsModels: Bool { model.target.dataFolder == "BotW" && model.target.version == "1.6.0" }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            libraryTools
            HSplitView {
                library.frame(minWidth: 385, maxWidth: .infinity)
                if showInspector {
                    inspector.frame(minWidth: 230, idealWidth: 260, maxWidth: 385)
                }
            }
            .frame(maxHeight: .infinity)
            .background(ModTint.panel)
            .clipShape(RoundedRectangle(cornerRadius: 9))
            .overlay { RoundedRectangle(cornerRadius: 9).strokeBorder(ModTint.line).allowsHitTesting(false) }
            footer
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task { model.refresh(keepMessage: true) }
        .onChange(of: openedBNPs, initial: true) { _, _ in reviewOpenedBNPs() }
        .onChange(of: model.busy) { _, _ in reviewOpenedBNPs() }
        .onChange(of: bnpBatch == nil) { _, _ in reviewOpenedBNPs() }
        .onChange(of: model.mods.map(\.id), initial: true) { old, new in
            if !old.isEmpty, let imported = new.first(where: { !old.contains($0) }) {
                search = ""
                libraryFilter = .all
                selectedID = imported
            } else if !new.contains(where: { $0 == selectedID }) {
                selectedID = visibleMods.first?.element.id
            }
        }
        .onChange(of: visibleMods.map(\.element.id)) { _, ids in
            if !ids.contains(where: { $0 == selectedID }) { selectedID = ids.first }
        }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didLaunchApplicationNotification)) { refreshGameState($0) }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didTerminateApplicationNotification)) { refreshGameState($0) }
        .alert(item: $removal) { mod in
            Alert(title: Text("Remove \(mod.name)?"),
                  message: Text("Remove the editor’s imported copy. Apply to prepare the updated mod set for the next launch."),
                  primaryButton: .destructive(Text("Remove copy")) { model.remove(mod) },
                  secondaryButton: .cancel())
        }
        .sheet(item: $flamebladeImport) { selection in
            FlamebladeImportSheet(url: selection.url) { stats in
                model.importPack(selection.url, stats: stats)
            }
        }
        .sheet(item: $bnpBatch) { batch in
            BNPImportSheet(packs: batch.packs) { model.importBNP($0, name: $1) }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text(model.target.name).font(.system(size: 25, weight: .semibold))
                Text(model.selectedProfile.isEmpty ? "Switch \(model.target.version)"
                     : "\(model.selectedProfile)  ·  Switch \(model.target.version)")
                    .font(.system(size: 12)).foregroundStyle(ModTint.muted)
            }
            Spacer()
            Label(gameLabel, systemImage: model.status?.gameRunning == true ? "play.circle" : "circle")
                .font(.system(size: 11)).foregroundStyle(model.status?.gameRunning == true ? ModTint.gold : ModTint.muted)
            Menu {
                Button(supportsModels ? "Folder, archive or weapon OBJ…" : "Switch mod folder or archive…") { chooseImport() }
                if supportsModels {
                    Button("Merge BCML BNP packs…") { chooseBNPs() }
                    Link("BCML export guide", destination: bcmlGuide)
                }
                if model.status?.canMakeDemos == true {
                    Divider()
                    Button("Add demo mods") { model.addDemos() }
                }
            } label: {
                Label("Import", systemImage: "tray.and.arrow.down")
            }
            .fixedSize().disabled(model.busy)
            Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.bordered).disabled(model.busy)
                .help("Refresh mod library and game status").accessibilityLabel("Refresh mod library")
        }
    }

    private var libraryTools: some View {
        HStack(spacing: 10) {
            Picker("Show mods", selection: $libraryFilter) {
                ForEach(LibraryFilter.allCases, id: \.self) { filter in
                    Text(filter.rawValue).tag(filter)
                }
            }
            .labelsHidden().pickerStyle(.segmented).fixedSize()
            Spacer(minLength: 8)
            HStack(spacing: 6) {
                Button { searchFocused = true } label: { Image(systemName: "magnifyingglass") }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
                    .keyboardShortcut("f", modifiers: .command)
                    .accessibilityLabel("Find a mod")
                TextField("Search mods", text: $search).textFieldStyle(.plain)
                    .focused($searchFocused)
                    .onExitCommand { search = ""; searchFocused = false }
                if !search.isEmpty {
                    Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).accessibilityLabel("Clear search")
                }
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .frame(minWidth: 110, idealWidth: 190, maxWidth: 245)
            .background(ModTint.panel, in: RoundedRectangle(cornerRadius: 6))
            .overlay { RoundedRectangle(cornerRadius: 6).strokeBorder(searchFocused ? ModTint.cyan : ModTint.line) }
            Button { showInspector.toggle() } label: { Image(systemName: "sidebar.right") }
                .buttonStyle(.bordered)
                .help(showInspector ? "Hide mod details" : "Show mod details")
                .accessibilityLabel(showInspector ? "Hide mod details" : "Show mod details")
            Button { showShortcuts.toggle() } label: { Image(systemName: "keyboard") }
                .buttonStyle(.bordered)
                .help("Keyboard shortcuts")
                .accessibilityLabel("Keyboard shortcuts")
                .popover(isPresented: $showShortcuts, arrowEdge: .bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Mod shortcuts").font(.headline)
                        Text("↑ / ↓    Select a mod")
                        Text("Space    Enable or disable")
                        Text("Delete    Remove with confirmation")
                        Text("⌘↑ / ⌘↓    Change load order")
                        Text("⌘F    Search")
                        Text("Drag the grip beside a mod to move it in the load order.")
                            .foregroundStyle(.secondary)
                    }.font(.system(size: 12)).padding(15)
                }
        }
        .controlSize(.small)
    }

    private var visibleMods: [(offset: Int, element: ManagedMod)] {
        let term = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return model.mods.enumerated().filter { _, mod in
            (term.isEmpty || mod.name.localizedStandardContains(term))
                && (libraryFilter != .enabled || mod.enabled)
                && (libraryFilter != .conflicts || !mod.valid || hasFileConflicts(mod)
                    || !(mod.dependencyIssues ?? []).isEmpty)
        }
    }

    private func hasFileConflicts(_ mod: ManagedMod) -> Bool {
        mod.conflicts.contains { !model.mergedPaths.contains($0) }
    }

    private var gameLabel: String {
        guard model.current, let running = model.status?.gameRunning else { return "Game status unavailable" }
        return running ? "Game running" : "Game closed"
    }

    private var library: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Text("#").frame(width: 26, alignment: .center).help("Load order")
                Text("Mod").frame(maxWidth: .infinity, alignment: .leading)
                Text("Status").frame(width: 85, alignment: .leading)
                Text("On").frame(width: 36)
            }
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(ModTint.muted)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(Color.primary.opacity(0.035))
            Rectangle().fill(ModTint.line).frame(height: 1)

            if model.mods.isEmpty {
                placeholder(model.current ? "No mods imported" : "Mod library",
                            detail: model.current ? "Import a folder or archive, or add the demos." : (model.activity ?? "Refresh to check your mod library."),
                            icon: "shippingbox")
            } else if visibleMods.isEmpty {
                placeholder("No matching mods", detail: "Change the search or filter.", icon: "magnifyingglass")
            } else {
                ScrollViewReader { scroll in
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            ForEach(visibleMods, id: \.element.id) { position, mod in
                                row(mod, position: position + 1)
                                    .id(mod.id)
                                Rectangle().fill(ModTint.line).frame(height: 1)
                                    .padding(.leading, 47)
                            }
                        }
                    }
                    .onChange(of: selectedID) { _, id in
                        if let id { scroll.scrollTo(id) }
                    }
                }
            }
        }.frame(maxHeight: .infinity, alignment: .topLeading)
    }

    private func row(_ mod: ManagedMod, position: Int) -> some View {
        let selected = selectedID == mod.id
        let focused = focusedID == mod.id
        let shared = hasFileConflicts(mod)
        let issue = !mod.valid || !(mod.dependencyIssues ?? []).isEmpty || shared
        let status = !mod.valid ? "Incompatible" : !(mod.dependencyIssues ?? []).isEmpty ? "Needs base"
            : shared ? "Shared files" : !mod.conflicts.isEmpty ? resourceMergeStatus : mod.enabled ? "Enabled" : "Off"
        return HStack(spacing: 10) {
            dragHandle(mod, position: position)
            Button {
                selectedID = mod.id
                focusedID = mod.id
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "shippingbox").frame(width: 16)
                        .foregroundStyle(selected ? ModTint.cyan : ModTint.muted)
                    Text(mod.name).font(.system(size: 13, weight: selected ? .semibold : .medium))
                        .lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                    Text(status).font(.system(size: 11, weight: issue ? .medium : .regular))
                        .foregroundStyle(issue ? ModTint.gold : mod.enabled ? ModTint.cyan : ModTint.muted)
                        .frame(width: 85, alignment: .leading)
                }.frame(minHeight: 44).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .focused($focusedID, equals: mod.id)
            .accessibilityLabel("\(mod.name), load order \(position)")
            .accessibilityValue(status)
            .accessibilityAddTraits(selected ? .isSelected : [])
            .onKeyPress(phases: .down) { press in
                handleModKey(press, mod: mod, position: position)
            }
            .onDeleteCommand {
                if focusedID == mod.id && !searchFocused && model.canEdit { removal = mod }
            }

            Toggle("Enable \(mod.name)", isOn: Binding(get: { mod.enabled }, set: { model.toggle(mod, enabled: $0) }))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
                .frame(width: 36)
                .disabled(!model.canEdit || (!mod.valid && !mod.enabled))
                .help(mod.valid ? "Include \(mod.name) in the next mod set" : mod.detail)
        }
        .padding(.horizontal, 12)
        .background(selected ? ModTint.raised : Color.clear)
        .overlay(alignment: .leading) {
            Rectangle().fill(selected ? ModTint.cyan : Color.clear).frame(width: 3).allowsHitTesting(false)
        }
        .overlay { Rectangle().strokeBorder(focused ? ModTint.cyan.opacity(0.6) : .clear).allowsHitTesting(false) }
        .overlay(alignment: dropLine?.after == true ? .bottom : .top) {
            if dropLine?.id == mod.id {
                Rectangle().fill(ModTint.cyan).frame(height: 2).allowsHitTesting(false)
            }
        }
        .dropDestination(for: ModDrag.self, isEnabled: model.canEdit) { items, session in
            dropLine = nil
            guard items.count == 1, let item = items.first, item.scope == dragScope,
                  item.profile == model.selectedProfile else { return }
            if model.move(item.id, relativeTo: mod.id, after: session.location.y >= session.size.height / 2) {
                selectedID = item.id
            }
        }
        .onDropSessionUpdated { session in
            if model.canEdit && session.localSession != nil
                && (session.phase == .entering || session.phase == .active) {
                dropLine = ModDropLine(id: mod.id, after: session.location.y >= session.size.height / 2)
            } else if dropLine?.id == mod.id {
                dropLine = nil
            }
        }
        .contextMenu {
            Button("Show details") { selectedID = mod.id; showInspector = true }
            Button(mod.enabled ? "Disable" : "Enable") { model.toggle(mod, enabled: !mod.enabled) }
                .disabled(!model.canEdit || (!mod.enabled && !mod.valid))
            Divider()
            Button("Move up") { model.move(mod, direction: .up) }.disabled(!model.canEdit || position == 1)
            Button("Move down") { model.move(mod, direction: .down) }
                .disabled(!model.canEdit || position == model.mods.count)
            Divider()
            Button("Remove…", role: .destructive) { removal = mod }.disabled(!model.canEdit)
        }
    }

    private var resourceMergeStatus: String {
        model.status?.pending == true ? "Will merge" : "Auto-merged"
    }

    @ViewBuilder private func dragHandle(_ mod: ManagedMod, position: Int) -> some View {
        let handle = HStack(spacing: 2) {
            Image(systemName: "line.3.horizontal").font(.system(size: 8, weight: .medium))
            Text("\(position)").font(.system(size: 10)).monospacedDigit()
        }
        .foregroundStyle(ModTint.muted)
        .frame(width: 26, height: 32)
        .contentShape(Rectangle())
        .accessibilityHidden(true)

        if model.canEdit {
            handle.draggable(ModDrag(id: mod.id, profile: model.selectedProfile, scope: dragScope))
                .help("Drag to reorder \(mod.name)")
        } else {
            handle
        }
    }

    private func handleModKey(_ press: KeyPress, mod: ManagedMod, position: Int) -> KeyPress.Result {
        guard focusedID == mod.id, !searchFocused else { return .ignored }
        let modifiers = press.modifiers.intersection([.command, .option, .control, .shift])
        switch (press.key, modifiers) {
        case (.space, []):
            if model.canEdit && (mod.valid || mod.enabled) { model.toggle(mod, enabled: !mod.enabled) }
        case (.delete, []), (.deleteForward, []), (.delete, .command):
            if model.canEdit { removal = mod }
        case (.upArrow, .command):
            if position > 1 { model.move(mod, direction: .up) }
        case (.downArrow, .command):
            if position < model.mods.count { model.move(mod, direction: .down) }
        case (.upArrow, []):
            selectNeighbor(of: mod.id, step: -1)
        case (.downArrow, []):
            selectNeighbor(of: mod.id, step: 1)
        default:
            return .ignored
        }
        return .handled
    }

    private func selectNeighbor(of id: String, step: Int) {
        let ids = visibleMods.map(\.element.id)
        guard let index = ids.firstIndex(of: id), ids.indices.contains(index + step) else { return }
        selectedID = ids[index + step]
        focusedID = selectedID
    }

    @ViewBuilder private var inspector: some View {
        if let mod = selected, let position = model.mods.firstIndex(where: { $0.id == mod.id }) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("Mod details").font(.system(size: 11, weight: .semibold)).foregroundStyle(ModTint.muted)
                    Spacer(minLength: 8)
                    Button("Move up", systemImage: "arrow.up") { model.move(mod, direction: .up) }
                        .disabled(!model.canEdit || position == 0)
                        .keyboardShortcut(focusedID == mod.id && !searchFocused ? KeyboardShortcut(.upArrow) : nil)
                        .help("Move up in load order")
                    Button("Move down", systemImage: "arrow.down") { model.move(mod, direction: .down) }
                        .disabled(!model.canEdit || position == model.mods.count - 1)
                        .keyboardShortcut(focusedID == mod.id && !searchFocused ? KeyboardShortcut(.downArrow) : nil)
                        .help("Move down in load order")
                    Button("Remove…", systemImage: "trash") { removal = mod }
                        .disabled(!model.canEdit)
                        .keyboardShortcut(focusedID == mod.id && !searchFocused
                                          ? KeyboardShortcut(.delete, modifiers: []) : nil)
                        .help("Remove this mod")
                }
                .labelStyle(.iconOnly).buttonStyle(.borderless).controlSize(.small)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(Color.primary.opacity(0.035))
                Rectangle().fill(ModTint.line).frame(height: 1)
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 7) {
                        Text(mod.name).font(.system(size: 19, weight: .semibold))
                            .fixedSize(horizontal: false, vertical: true)
                        if let description = mod.description, !description.isEmpty {
                            Text("Description").font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(ModTint.muted)
                                .accessibilityAddTraits(.isHeader)
                            Text(descriptionText(description))
                                .font(.system(size: 13))
                                .foregroundStyle(ModTint.ivory)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                                .padding(.bottom, 6)
                        }
                        Label(mod.valid ? "RomFS files validated" : "Compatibility issue",
                              systemImage: mod.valid ? "checkmark.circle" : "exclamationmark.circle")
                            .font(.system(size: 11)).foregroundStyle(mod.valid ? ModTint.cyan : ModTint.gold)
                        if !mod.detail.isEmpty && mod.detail != "Ready for Switch RomFS" {
                            Text(mod.detail).font(.system(size: 12)).foregroundStyle(ModTint.muted)
                                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        }
                        ForEach(mod.dependencyIssues ?? [], id: \.self) { issue in
                            Label(issue, systemImage: "exclamationmark.triangle")
                                .font(.system(size: 12)).foregroundStyle(ModTint.gold)
                        }
                    }
                    Rectangle().fill(ModTint.line).frame(height: 1)
                    HStack(spacing: 14) {
                        metric("Replacements", value: mod.replaced)
                        metric("Additions", value: mod.added)
                        metric("Shared", value: mod.conflicts.count)
                    }
                    if !mod.conflicts.isEmpty { overlaps(mod.conflicts) }
                    }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
                }.id(mod.id)
            }.frame(maxHeight: .infinity, alignment: .topLeading)
        } else {
            placeholder("Mod details", detail: "Select a pack to check its files and change its priority.", icon: "doc.text.magnifyingglass")
        }
    }

    private func descriptionText(_ source: String) -> AttributedString {
        var text = (try? AttributedString(markdown: source,
                                          options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(source)
        text.link = nil
        return text
    }

    private func overlaps(_ paths: [String]) -> some View {
        var winners: [String: String] = [:]
        for mod in model.mods where mod.enabled {
            for path in mod.conflicts { winners[path] = mod.name }
        }
        return LazyVStack(alignment: .leading, spacing: 8) {
            Text("Shared files").font(.system(size: 14, weight: .medium))
            ForEach(Array(paths.enumerated()), id: \.offset) { _, path in
                VStack(alignment: .leading, spacing: 2) {
                    Text(path).font(.system(size: 10, design: .monospaced)).lineLimit(2)
                        .truncationMode(.middle).textSelection(.enabled)
                    if model.mergedPaths.contains(path) {
                        Text("Resource sizes merged on Apply").font(.system(size: 10)).foregroundStyle(ModTint.cyan)
                    } else if let winner = winners[path] {
                        Text("Wins: \(winner)").font(.system(size: 10)).foregroundStyle(ModTint.cyan)
                    }
                }
            }
        }.foregroundStyle(ModTint.muted)
    }

    private func metric(_ label: String, value: Int) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value.formatted()).font(.system(size: 23, weight: .light)).monospacedDigit()
            Text(label).font(.system(size: 10)).foregroundStyle(ModTint.muted)
        }.accessibilityElement(children: .combine)
    }

    private func placeholder(_ title: String, detail: String, icon: String) -> some View {
        VStack(spacing: 9) {
            Image(systemName: icon).font(.system(size: 23, weight: .light)).foregroundStyle(ModTint.cyan)
                .accessibilityHidden(true)
            Text(title).font(.system(size: 17, weight: .medium))
            Text(detail).font(.system(size: 11)).foregroundStyle(ModTint.muted).multilineTextAlignment(.center)
        }.padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var footer: some View {
        HStack(alignment: .center, spacing: 12) {
            if model.busy { ProgressView().controlSize(.small).frame(width: 20) }
            else { Image(systemName: statusIcon).foregroundStyle(statusColor).frame(width: 20) }
            VStack(alignment: .leading, spacing: 4) {
                Text(statusTitle).font(.system(size: 13, weight: .medium)).foregroundStyle(statusColor)
                if !model.busy, let message = model.message, !message.isEmpty {
                    Text(message).font(.system(size: 11)).foregroundStyle(model.failed ? ModTint.orange : ModTint.muted)
                        .lineLimit(3).textSelection(.enabled)
                }
                if !model.busy, let blocker = model.blocker, blocker != model.message {
                    Text(blocker).font(.system(size: 11)).foregroundStyle(ModTint.gold).lineLimit(3)
                } else if !model.busy, !model.failed, model.message == nil, model.current {
                    let enabled = model.mods.filter(\.enabled).count
                    Text("\(enabled) of \(model.mods.count) mods enabled")
                        .font(.system(size: 11)).foregroundStyle(ModTint.muted)
                }
            }
            Spacer(minLength: 0)
            if let backup = model.backupURL {
                Button("Show backup") { NSWorkspace.shared.activateFileViewerSelecting([backup]) }
                    .buttonStyle(.bordered).help("Reveal the previous overlay in Finder")
            }
            Button("Apply") { model.apply() }
                .buttonStyle(.bordered).disabled(!model.canApply)
                .help(model.blocker ?? "Prepare the enabled mods for the next game launch")
            Button(model.status?.pending == true ? "Apply & Launch" : "Launch Game", systemImage: "play.fill") { model.launch() }
                .buttonStyle(.borderedProminent).disabled(!model.canLaunch)
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(ModTint.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(ModTint.line).allowsHitTesting(false) }
    }

    private var statusTitle: String {
        if let activity = model.activity { return activity }
        if model.failed { return "Mods need attention" }
        if model.blocker != nil { return "Apply blocked" }
        if model.status?.gameRunning == true { return "Game running" }
        if model.status?.pending == true { return "Changes ready to apply" }
        if (model.status?.appliedFiles ?? 0) > 0 { return "Prepared for next launch" }
        return model.current ? "No changes to apply" : "Mod library unavailable"
    }
    private var statusColor: Color {
        if model.busy { return ModTint.muted }
        if model.failed { return ModTint.orange }
        if model.blocker != nil { return ModTint.gold }
        return model.current ? ModTint.cyan : ModTint.muted
    }
    private var statusIcon: String {
        if model.failed || model.blocker != nil { return "exclamationmark.circle" }
        return (model.status?.appliedFiles ?? 0) > 0 && model.status?.pending == false ? "checkmark.circle" : "tray"
    }

    private func chooseImport() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.resolvesAliases = false
        panel.prompt = "Import"
        panel.message = supportsModels
            ? "Choose a Switch mod folder, ZIP or 7z, or an OBJ such as Weapon_Sword_001 - My Sword.obj."
            : "Choose a Switch RomFS folder, ZIP or 7z archive."
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            let filename = url.deletingPathExtension().lastPathComponent
            if supportsModels, url.pathExtension.lowercased() == "obj",
               filename == "Weapon_Sword_033" || filename.hasPrefix("Weapon_Sword_033 - ") {
                flamebladeImport = FlamebladeImport(url: url)
            } else {
                model.importPack(url)
            }
        }
    }

    private func chooseBNPs() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.resolvesAliases = false
        if let bnp = UTType(filenameExtension: "bnp") { panel.allowedContentTypes = [bnp] }
        panel.prompt = "Review Packs"
        panel.message = "Choose one or more Switch Breath of the Wild BNP packages."
        panel.begin { response in
            if response == .OK, !panel.urls.isEmpty { bnpBatch = BNPBatch(packs: panel.urls) }
        }
    }

    private func reviewOpenedBNPs() {
        guard supportsModels, !model.busy, bnpBatch == nil, !openedBNPs.isEmpty else { return }
        bnpBatch = BNPBatch(packs: openedBNPs)
        openedBNPs = []
    }

    private func refreshGameState(_ notification: Notification) {
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
              app.bundleIdentifier == model.target.bundleID else { return }
        model.refresh(keepMessage: true)
    }
}

private struct ModDrag: Codable, Transferable {
    let id: String
    let profile: String
    let scope: UUID

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: UTType(exportedAs: "dev.christianfurr.macnative-mods.load-order"))
    }
}

private struct ModDropLine {
    let id: String
    let after: Bool
}

struct ModsProfileSidebar: View {
    @ObservedObject var model: ModsModel
    @State private var profileName = ""
    @State private var profilePrompt: ProfilePrompt?
    @State private var editingProfile = false
    @State private var deletingProfile = false

    private enum ProfilePrompt: String {
        case empty = "New empty profile"
        case copy = "Duplicate profile"
        case rename = "Rename profile"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Profiles")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                profileMenu
            }.padding(.horizontal, 9)

            ForEach(model.profiles, id: \.self) { name in
                let selected = model.selectedProfile == name
                Button { model.selectProfile(name) } label: {
                    HStack(spacing: 9) {
                        Image(systemName: "square.stack").frame(width: 17)
                        Text(name).lineLimit(1)
                        Spacer(minLength: 0)
                        if selected { Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)) }
                    }
                    .font(.system(size: 12, weight: selected ? .semibold : .regular))
                    .padding(.horizontal, 9).padding(.vertical, 7)
                    .contentShape(Rectangle())
                    .background(selected ? ModTint.raised : .clear, in: RoundedRectangle(cornerRadius: 6))
                    .foregroundStyle(selected ? ModTint.cyan : ModTint.ivory)
                }
                .buttonStyle(.plain)
                .disabled(!model.canEdit)
                .accessibilityAddTraits(selected ? .isSelected : [])
                .help(name)
            }
            if model.profiles.isEmpty {
                Text(model.busy ? "Loading profiles…" : "Profiles unavailable")
                    .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 9)
            }
        }
        .alert(profilePrompt?.rawValue ?? "Profile name", isPresented: $editingProfile) {
            TextField("Profile name", text: $profileName)
            Button("Cancel", role: .cancel) {}
            Button("Save") {
                let name = profileName.trimmingCharacters(in: .whitespacesAndNewlines)
                if profilePrompt == .rename { model.renameProfile(name) }
                else { model.createProfile(name, copy: profilePrompt == .copy) }
            }.disabled(profileName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .alert("Delete \(model.selectedProfile)?", isPresented: $deletingProfile) {
            Button("Cancel", role: .cancel) {}
            Button("Delete profile", role: .destructive) { model.deleteSelectedProfile() }
        } message: {
            Text("This removes the loadout. Imported mods and game saves stay on this Mac.")
        }
    }

    private var profileMenu: some View {
        Menu {
            Button("New empty profile…") { editProfile(.empty) }
            Button("Duplicate current profile…") { editProfile(.copy) }
            Divider()
            Button("Rename current profile…") { editProfile(.rename) }
            Button("Delete current profile…", role: .destructive) { deletingProfile = true }
                .disabled(model.profiles.count < 2)
            Divider()
            Button("Import profile…") { importProfile() }
            Button("Export current profile…") { exportProfile() }
        } label: {
            Label("Manage Profiles", systemImage: "ellipsis.circle").labelStyle(.iconOnly)
        }
        .menuIndicator(.hidden).menuStyle(.borderlessButton).fixedSize()
        .disabled(!model.canEdit)
        .accessibilityLabel("Manage Profiles")
    }

    private func editProfile(_ prompt: ProfilePrompt) {
        profilePrompt = prompt
        profileName = prompt == .rename ? model.selectedProfile : ""
        editingProfile = true
    }

    private func importProfile() {
        let panel = NSOpenPanel()
        if let type = UTType(filenameExtension: "macnativeprofile") { panel.allowedContentTypes = [type] }
        panel.prompt = "Import Profile"
        panel.message = "Import a loadout. Install its mod packs in this game’s library first."
        panel.begin { response in
            if response == .OK, let url = panel.url { model.importProfile(url) }
        }
    }

    private func exportProfile() {
        let panel = NSSavePanel()
        if let type = UTType(filenameExtension: "macnativeprofile") { panel.allowedContentTypes = [type] }
        let name = model.selectedProfile.replacingOccurrences(of: "/", with: "-").replacingOccurrences(of: ":", with: "-")
        panel.nameFieldStringValue = name + ".macnativeprofile"
        panel.prompt = "Export Profile"
        panel.message = "Share the enabled mods and their load order."
        panel.begin { response in
            if response == .OK, let url = panel.url { model.exportProfile(url) }
        }
    }
}

private struct BNPBatch: Identifiable {
    let id = UUID()
    let packs: [URL]
}

private struct BNPImportSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State var packs: [URL]
    let submit: ([URL], String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Merge Switch BNP Packs").font(.title2.bold())
            Text("Put the base mod first and add-ons below it. BCML merges the selected files into one library entry.")
                .foregroundStyle(.secondary)
            TextField("Name for the merged pack (optional)", text: $name).textFieldStyle(.roundedBorder)
            List {
                ForEach(Array(packs.enumerated()), id: \.element) { index, url in
                    HStack {
                        Text("\(index + 1)").monospacedDigit().foregroundStyle(.secondary)
                        Text(url.lastPathComponent).lineLimit(1)
                        Spacer()
                        Button("Move up", systemImage: "arrow.up") { packs.swapAt(index, index - 1) }
                            .disabled(index == 0)
                        Button("Move down", systemImage: "arrow.down") { packs.swapAt(index, index + 1) }
                            .disabled(index == packs.count - 1)
                    }.labelStyle(.iconOnly).buttonStyle(.borderless)
                }
            }.frame(minHeight: 130, maxHeight: 260)
            Text("Uses each pack’s default options and US English. Separate DLC files are left out.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                Button("Merge & Import") {
                    submit(packs, name.trimmingCharacters(in: .whitespacesAndNewlines))
                    dismiss()
                }.buttonStyle(.borderedProminent).disabled(name.count > 100)
            }
        }.padding(22).frame(width: 505)
    }
}

private struct FlamebladeImport: Identifiable {
    let url: URL
    var id: URL { url }
}

private struct FlamebladeImportSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var attack = ""
    @State private var durability = ""
    @State private var fireCapacity = ""
    let url: URL
    let onImport: (FlamebladeStats) -> Void

    private var canImport: Bool {
        valid(attack, limit: 255) && valid(durability, limit: 255) && valid(fireCapacity, limit: 8)
    }

    private func valid(_ value: String, limit: Int) -> Bool {
        value.isEmpty || (Int(value).map { (1...limit).contains($0) } ?? false)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("Customize Flameblade", systemImage: "flame.fill").font(.title2)
            Text(url.lastPathComponent).foregroundStyle(.secondary)
            Text("Your OBJ replaces the blade. Charged strikes use BOTW’s fire effect and recharge normally.")
            Form {
                TextField("Attack (1–255)", text: $attack, prompt: Text("24"))
                TextField("Durability (1–255)", text: $durability, prompt: Text("36"))
                TextField("Fire capacity (1–8)", text: $fireCapacity, prompt: Text("4"))
            }
            Text("Leave a field blank to use the original value. Capacity changes the fire energy reserve.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Import") {
                    onImport(FlamebladeStats(attack: Int(attack), durability: Int(durability),
                                             fireCapacity: Int(fireCapacity)))
                    dismiss()
                }.keyboardShortcut(.defaultAction).disabled(!canImport)
            }
        }
        .padding(24)
        .frame(width: 430)
    }
}


private enum ModTint {
    static let line = Color.primary.opacity(0.13)
    static let panel = Color(nsColor: .controlBackgroundColor)
    static let raised = Color.accentColor.opacity(0.10)
    static let cyan = Color.accentColor
    static let muted = Color.secondary
    static let gold = Color.orange
    static let orange = Color.red
    static let ivory = Color.primary
}
