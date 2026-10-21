import SwiftUI
import SampleLibrarianCore

struct SampleRowView: View {
    let sample: SampleRecord
    /// Called on a plain click. List's own selection-on-click can be
    /// unreliable on the same row that also has .onDrag attached (the drag
    /// gesture recognizer sometimes wins the ambiguity over a quick tap) --
    /// this explicit, always-fires tap gesture is what actually makes
    /// clicking a different row instant and reliable.
    var onSelect: () -> Void = {}

    private var isSong: Bool { sample.tags.contains("song") }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(sample.cleanedFilename)
                .font(.system(.body, design: .monospaced))
                .lineLimit(1)
                .foregroundStyle(isSong ? .secondary : .primary)
                .italic(isSong)
                .frame(maxWidth: .infinity, alignment: .leading)

            RatingBadge(rating: sample.rating)
                .frame(width: 30, alignment: .trailing)

            Text(lengthLabel)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 56, alignment: .trailing)
            Text(bpmLabel)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 56, alignment: .trailing)
            Text(sample.musicalKey ?? "-")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 50, alignment: .trailing)
        }
        .frame(height: 22)
        .contentShape(Rectangle())
        // simultaneousGesture (not onTapGesture) so this never loses a
        // priority fight with the drag gesture below -- both get to see the
        // interaction, and a plain click always registers.
        .simultaneousGesture(TapGesture().onEnded(onSelect))
        // First thing to try per the project plan; see DraggableFileArea.swift
        // for the AppKit fallback if this doesn't hold up against Logic Pro.
        // CONFIRMED WORKING against real Logic (2026-08-25): file lands and
        // now names correctly (suggestedName below). Still unverified:
        // whether Logic renders its normal duration-sized "ghost block"
        // preview while hovering (it does for a Finder drag of the same
        // file, it doesn't for ours yet -- registering the URL as a plain
        // object too, in addition to the content promise, is the most
        // likely-to-help thing to try: NSItemProvider(contentsOf:) sets up a
        // lazy content *promise* under the file's own UTI, whereas Finder's
        // drag also exposes a synchronously-resolvable plain NSURL object
        // (public.file-url) that a receiver can probe immediately on hover
        // without waiting on a promise callback -- plausible that's what
        // Logic's hover-preview code path specifically wants).
        .onDrag {
            let provider = NSItemProvider(contentsOf: sample.resolvedFileURL) ?? NSItemProvider()
            provider.suggestedName = sample.resolvedFileURL.lastPathComponent
            provider.registerObject(sample.resolvedFileURL as NSURL, visibility: .all)
            return provider
        } preview: {
            DragPreviewCard(sample: sample)
        }
    }

    private var bpmLabel: String {
        guard let bpm = sample.bpm else { return "-" }
        return "\(Int(bpm.rounded()))bpm"
    }

    private var lengthLabel: String {
        if let beats = sample.beatCount {
            return "\(Int(beats.rounded()))b"
        }
        if let duration = sample.durationSeconds {
            return String(format: "%.1fs", duration)
        }
        return "-"
    }
}

/// What follows the cursor while dragging a row out -- without an explicit
/// preview, SwiftUI's default .onDrag image can end up looking like nothing
/// is being held at all. This gives clear "you're holding a file" feedback,
/// independent of whatever Logic itself renders as a drop target.
private struct DragPreviewCard: View {
    let sample: SampleRecord

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "waveform")
            Text(sample.cleanedFilename)
                .lineLimit(1)
        }
        .font(.system(.callout, design: .monospaced))
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 6))
        .shadow(radius: 3)
    }
}

/// Compact -2...+2 readout: color communicates good/bad at a glance faster
/// than reading the digit, which matters when scanning a long list fast.
private struct RatingBadge: View {
    let rating: Int

    var body: some View {
        Text(label)
            .font(.system(.caption, design: .monospaced, weight: .semibold))
            .foregroundStyle(color)
    }

    private var label: String {
        switch rating {
        case ..<0: return "\(rating)"
        case 0: return "0"
        default: return "+\(rating)"
        }
    }

    private var color: Color {
        switch rating {
        case -2: return .red
        case -1: return .orange
        case 0: return .secondary
        case 1: return .green
        default: return .green
        }
    }
}
