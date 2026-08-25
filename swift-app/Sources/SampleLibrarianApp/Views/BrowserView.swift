import SwiftUI
import SampleLibrarianCore

@MainActor
final class BrowserViewModel: ObservableObject {
    @Published var searchText: String = "" {
        didSet { reload() }
    }
    @Published private(set) var selectedTags: [String] = [] {
        didSet { reload() }
    }
    @Published var bpmMinText: String = "" {
        didSet { reload() }
    }
    @Published var bpmMaxText: String = "" {
        didSet { reload() }
    }
    @Published var keyText: String = "" {
        didSet { reload() }
    }
    @Published private(set) var samples: [SampleRecord] = []
    @Published private(set) var availableFacets: [(tag: String, count: Int)] = []
    @Published var errorMessage: String?
    @Published var selection: SampleRecord.ID?
    @Published private(set) var isRescanning = false
    @Published var rescanStatusMessage: String?

    private let database: Database?

    init() {
        do {
            database = try Database(path: AppConfig.databasePath)
        } catch {
            database = nil
            errorMessage = "Couldn't open library database at \(AppConfig.databasePath.path): \(error)"
        }
        reload()
    }

    func selectTag(_ tag: String) {
        guard !selectedTags.contains(tag) else { return }
        selectedTags.append(tag)
    }

    func deselectTag(_ tag: String) {
        selectedTags.removeAll { $0 == tag }
    }

    func reload() {
        guard let database else { return }
        do {
            let bpmMin = Double(bpmMinText.trimmingCharacters(in: .whitespaces))
            let bpmMax = Double(bpmMaxText.trimmingCharacters(in: .whitespaces))
            let key = keyText.trimmingCharacters(in: .whitespaces)
            let text = searchText.isEmpty ? nil : searchText

            samples = try database.search(
                text: text, tags: selectedTags, bpmMin: bpmMin, bpmMax: bpmMax,
                musicalKey: key.isEmpty ? nil : key
            )
            availableFacets = try database.tagCounts(
                text: text, tags: selectedTags, bpmMin: bpmMin, bpmMax: bpmMax,
                musicalKey: key.isEmpty ? nil : key
            )
            errorMessage = nil
        } catch {
            errorMessage = "Search failed: \(error)"
        }
    }

    func rescanInbox() {
        guard !isRescanning else { return }
        isRescanning = true
        rescanStatusMessage = nil
        Task {
            do {
                let result = try await InboxRescanner.run()
                rescanStatusMessage = result.succeeded
                    ? "Inbox rescanned."
                    : "Rescan failed: \(result.output.trimmingCharacters(in: .whitespacesAndNewlines))"
                if result.succeeded {
                    reload()
                }
            } catch {
                rescanStatusMessage = "Rescan failed: \(error)"
            }
            isRescanning = false
        }
    }
}

struct BrowserView: View {
    @StateObject private var viewModel = BrowserViewModel()

    var body: some View {
        VStack(spacing: 0) {
            SearchFilterBar(
                searchText: $viewModel.searchText,
                bpmMinText: $viewModel.bpmMinText,
                bpmMaxText: $viewModel.bpmMaxText,
                keyText: $viewModel.keyText
            )

            FacetChipsView(
                selectedTags: viewModel.selectedTags,
                availableFacets: viewModel.availableFacets,
                onSelect: viewModel.selectTag,
                onDeselect: viewModel.deselectTag
            )
            Divider()

            if let errorMessage = viewModel.errorMessage {
                ContentUnavailableMessage(message: errorMessage)
            } else if viewModel.samples.isEmpty {
                ContentUnavailableMessage(message: "No samples match. Try a different search, or run `samplelib scan --apply` first.")
            } else {
                // List gives arrow-key navigation + selection highlighting for
                // free once it has focus -- no custom key handling needed.
                List(viewModel.samples, selection: $viewModel.selection) { sample in
                    SampleRowView(sample: sample, onTagTapped: viewModel.selectTag)
                }
                .listStyle(.plain)
                .font(.system(.body, design: .monospaced))
            }
        }
        .frame(minWidth: 560, minHeight: 380)
        .background(Color(nsColor: .textBackgroundColor))
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    viewModel.rescanInbox()
                } label: {
                    if viewModel.isRescanning {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("Rescan Inbox", systemImage: "arrow.clockwise")
                    }
                }
                .disabled(viewModel.isRescanning)
                .help("Process new files dropped into the inbox/ folder")
            }
        }
        .alert(
            "Inbox Rescan",
            isPresented: Binding(
                get: { viewModel.rescanStatusMessage != nil },
                set: { if !$0 { viewModel.rescanStatusMessage = nil } }
            )
        ) {
            Button("OK") { viewModel.rescanStatusMessage = nil }
        } message: {
            Text(viewModel.rescanStatusMessage ?? "")
        }
    }
}

private struct ContentUnavailableMessage: View {
    let message: String

    var body: some View {
        VStack {
            Spacer()
            Text(message)
                .font(.system(.body, design: .monospaced))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding()
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }
}
