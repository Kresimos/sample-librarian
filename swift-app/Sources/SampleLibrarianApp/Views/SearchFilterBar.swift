import SwiftUI

struct SearchFilterBar: View {
    @Binding var searchText: String
    @Binding var selectedType: String?
    let availableTypes: [String]

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
            TextField("Search filename, type, or tag...", text: $searchText)
                .textFieldStyle(.plain)
                .font(.system(.body, design: .monospaced))

            Picker("Type", selection: $selectedType) {
                Text("All types").tag(String?.none)
                ForEach(availableTypes, id: \.self) { type in
                    Text(type).tag(String?.some(type))
                }
            }
            .labelsHidden()
            .frame(width: 140)
        }
        .padding(8)
        .background(.thinMaterial)
    }
}
