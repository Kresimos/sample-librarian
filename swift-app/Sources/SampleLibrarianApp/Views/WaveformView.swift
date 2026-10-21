import SampleLibrarianCore
import SwiftUI

/// Draws a peak (min/max) waveform plus a playhead. Peaks are precomputed by
/// WaveformGenerator off the main thread (see PreviewPanel) -- this view is
/// pure rendering.
struct WaveformView: View {
    let peaks: [WaveformGenerator.Peak]
    /// 0...1, or nil while nothing is loaded/playing.
    let playheadFraction: Double?

    // Hue sweeps from red (bass) to blue (treble) across 0...240 degrees of
    // the wheel -- stopping short of the full 360 so the top end lands on
    // blue/violet rather than wrapping back around toward red.
    private static let hueSweepDegrees = 240.0

    var body: some View {
        Canvas { context, size in
            guard !peaks.isEmpty else { return }

            let midY = size.height / 2
            let barWidth = size.width / CGFloat(peaks.count)

            for (index, peak) in peaks.enumerated() {
                let x = CGFloat(index) * barWidth
                let topY = midY - CGFloat(peak.max) * midY
                let bottomY = midY - CGFloat(peak.min) * midY
                let barRect = CGRect(x: x, y: min(topY, bottomY), width: max(barWidth - 1, 1), height: max(abs(bottomY - topY), 1))
                context.fill(Path(barRect), with: .color(Self.color(for: peak).opacity(0.75)))
            }

            if let playheadFraction {
                let x = CGFloat(playheadFraction) * size.width
                var playhead = Path()
                playhead.move(to: CGPoint(x: x, y: 0))
                playhead.addLine(to: CGPoint(x: x, y: size.height))
                context.stroke(playhead, with: .color(.primary), lineWidth: 1.5)
            }
        }
    }

    /// Picks a single hue from this bucket's dominant frequency. Falls back
    /// to a neutral grey for a near-silent bucket -- not .accentColor (which
    /// renders as blue and got confused for a real "treble" reading) -- so
    /// quiet gaps read as unmistakably "nothing here" rather than a
    /// meaningless hue picked from noise. Deliberately a single saturated
    /// hue rather than blending 3 fixed RGB primaries by energy share -- see
    /// Peak.dominantFrequencyPosition's doc comment for why that
    /// additive-mixing approach washed broadband/distorted sounds toward grey.
    private static func color(for peak: WaveformGenerator.Peak) -> Color {
        guard peak.spectralEnergy > 0.05 else { return .gray }
        let hue = Double(peak.dominantFrequencyPosition) * (hueSweepDegrees / 360.0)
        return Color(hue: hue, saturation: 0.85, brightness: 0.9)
    }
}
