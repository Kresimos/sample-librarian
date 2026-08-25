import SwiftUI

struct SearchFilterBar: View {
    @Binding var searchText: String
    @Binding var selectedType: String?
    @Binding var selectedLoopType: String?
    @Binding var bpmMinText: String
    @Binding var bpmMaxText: String
    @Binding var keyText: String
    let availableTypes: [String]

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search filename, type, or tag...", text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.system(.body, design: .monospaced))

                Picker("Loop/One-shot", selection: $selectedLoopType) {
                    Text("Loop or one-shot").tag(String?.none)
                    Text("Loops").tag(String?.some("loop"))
                    Text("One-shots").tag(String?.some("one-shot"))
                }
                .labelsHidden()
                .frame(width: 130)

                Picker("Type", selection: $selectedType) {
                    Text("All types").tag(String?.none)
                    ForEach(availableTypes, id: \.self) { type in
                        Text(type).tag(String?.some(type))
                    }
                }
                .labelsHidden()
                .frame(width: 140)
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
