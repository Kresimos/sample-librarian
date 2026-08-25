import SwiftUI
import SampleLibrarianCore

@MainActor
final class BrowserViewModel: ObservableObject {
    @Published var searchText: String = "" {
        didSet { reload() }
    }
    @Published var selectedType: String? = nil {
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
    @Published private(set) var availableTypes: [String] = []
    @Published var errorMessage: String?
    @Published var selection: SampleRecord.ID?

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

    func reload() {
        guard let database else { return }
        do {
            samples = try database.search(
                text: searchText.isEmpty ? nil : searchText,
                sampleType: selectedType,
                bpmMin: Double(bpmMinText.trimmingCharacters(in: .whitespaces)),
                bpmMax: Double(bpmMaxText.trimmingCharacters(in: .whitespaces)),
                musicalKey: keyText.trimmingCharacters(in: .whitespaces).isEmpty ? nil : keyText
            )
            availableTypes = try database.distinctSampleTypes()
            errorMessage = nil
        } catch {
            errorMessage = "Search failed: \(error)"
        }
    }
}

struct BrowserView: View {
    @StateObject private var viewModel = BrowserViewModel()

    var body: some View {
        VStack(spacing: 0) {
            SearchFilterBar(
                searchText: $viewModel.searchText,
                selectedType: $viewModel.selectedType,
                bpmMinText: $viewModel.bpmMinText,
                bpmMaxText: $viewModel.bpmMaxText,
                keyText: $viewModel.keyText,
                availableTypes: viewModel.availableTypes
            )

            if let errorMessage = viewModel.errorMessage {
                ContentUnavailableMessage(message: errorMessage)
            } else if viewModel.samples.isEmpty {
                ContentUnavailableMessage(message: "No samples match. Try a different search, or run `samplelib scan --apply` first.")
            } else {
                // List gives arrow-key navigation + selection highlighting for
                // free once it has focus -- no custom key handling needed.
                List(viewModel.samples, selection: $viewModel.selection) { sample in
                    SampleRowView(sample: sample)
                }
                .listStyle(.plain)
                .font(.system(.body, design: .monospaced))
            }
        }
        .frame(minWidth: 520, minHeight: 360)
        .background(Color(nsColor: .textBackgroundColor))
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
