import SwiftUI
import SampleLibrarianCore

struct SampleRowView: View {
    let sample: SampleRecord

    private var isSong: Bool { sample.sampleType == "song" }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(sample.cleanedFilename)
                .font(.system(.body, design: .monospaced))
                .lineLimit(1)
                .foregroundStyle(isSong ? .secondary : .primary)
                .italic(isSong)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(sample.sampleType ?? "-")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(isSong ? Color.orange : .secondary)
                .frame(width: 80, alignment: .leading)
            Text(sample.loopType ?? "-")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 66, alignment: .leading)
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
