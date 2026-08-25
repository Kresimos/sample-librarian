import SwiftUI

struct SearchFilterBar: View {
    @Binding var searchText: String
    @Binding var bpmMinText: String
    @Binding var bpmMaxText: String
    @Binding var keyText: String

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search filename or tags...", text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.system(.body, design: .monospaced))
            }

            HStack(spacing: 8) {
                Text("BPM").font(.caption).foregroundStyle(.secondary)
                TextField("min", text: $bpmMinText)
                    .frame(width: 48)
                Text("-").foregroundStyle(.secondary)
                TextField("max", text: $bpmMaxText)
                    .frame(width: 48)

                Divider().frame(height: 14)

                Text("Key").font(.caption).foregroundStyle(.secondary)
                TextField("e.g. C#min", text: $keyText)
                    .frame(width: 90)

                Spacer()
            }
            .textFieldStyle(.roundedBorder)
            .font(.system(.caption, design: .monospaced))
        }
        .padding(8)
        .background(.thinMaterial)
    }
}
