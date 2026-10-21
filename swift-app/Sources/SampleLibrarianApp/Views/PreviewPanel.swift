import SampleLibrarianCore
import SwiftUI

/// Shows the currently-selected sample's filename and waveform, with a
/// playhead synced to AudioPlayerController. Waveform generation is debounced
/// so flicking through the list with the arrow keys doesn't trigger a decode
/// per row passed over -- only once the user actually pauses on one.
struct PreviewPanel: View {
    let sample: SampleRecord?
    @ObservedObject var player: AudioPlayerController
    @State private var peaks: [WaveformGenerator.Peak] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(sample?.cleanedFilename ?? "No sample selected")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            WaveformView(peaks: peaks, playheadFraction: playheadFraction)
                .frame(height: 64)
        }
        .padding(8)
        .background(.thinMaterial)
        .task(id: sample?.id) {
            peaks = []
            guard let sample else { return }
            try? await Task.sleep(nanoseconds: 150_000_000)
            guard !Task.isCancelled else { return }

            let url = sample.resolvedFileURL
            let generated = await Task.detached(priority: .userInitiated) {
                (try? WaveformGenerator.generate(fileURL: url)) ?? []
            }.value
            guard !Task.isCancelled else { return }
            peaks = generated
        }
    }

    private var playheadFraction: Double? {
        guard player.duration > 0, player.currentURL == sample?.resolvedFileURL else { return nil }
        return player.currentTime / player.duration
    }
}
