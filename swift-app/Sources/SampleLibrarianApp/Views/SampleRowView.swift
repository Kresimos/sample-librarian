import SwiftUI
import SampleLibrarianCore

struct SampleRowView: View {
    let sample: SampleRecord
    /// Invoked when the user clicks one of this row's tag chips, to add it
    /// to the active filter -- the faceted-narrowing "click a tag to drill
    /// in" interaction.
    var onTagTapped: (String) -> Void = { _ in }

    private var isSong: Bool { sample.tags.contains("song") }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(sample.cleanedFilename)
                .font(.system(.body, design: .monospaced))
                .lineLimit(1)
                .foregroundStyle(isSong ? .secondary : .primary)
                .italic(isSong)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 4) {
                ForEach(sample.tags, id: \.self) { tag in
                    Text(tag)
                        .font(.system(.caption2, design: .monospaced))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(
                            (tag == "song" ? Color.orange : Color.secondary)
                                .opacity(0.15), in: RoundedRectangle(cornerRadius: 4)
                        )
                        .foregroundStyle(tag == "song" ? Color.orange : .secondary)
                        .onTapGesture { onTagTapped(tag) }
                }
            }
            .frame(width: 220, alignment: .leading)

            Text(bpmLabel)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 56, alignment: .trailing)
            Text(sample.musicalKey ?? "-")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 50, alignment: .trailing)
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
        // First thing to try per the project plan; see DraggableFileArea.swift
        // for the AppKit fallback if this doesn't hold up against Logic Pro.
        // NEEDS HANDS-ON VERIFICATION.
        .onDrag {
            NSItemProvider(contentsOf: sample.resolvedFileURL) ?? NSItemProvider()
        }
    }

    private var bpmLabel: String {
        guard let bpm = sample.bpm else { return "-" }
        return "\(Int(bpm.rounded()))"
    }
}
