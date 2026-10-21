import Accelerate
import AVFoundation
import Foundation

/// Downsamples an audio file into a small array of peak (min/max) amplitude
/// pairs for drawing a waveform, without pulling in a third-party waveform
/// library (matches this project's no-external-SPM-dependency rule). Decodes
/// via AVAudioFile, so it supports whatever formats AVFoundation does (WAV,
/// AIFF, MP3, M4A, FLAC -- the same formats this library organizes).
public enum WaveformGenerator {
    public struct Peak: Sendable {
        public let min: Float
        public let max: Float
        /// This bucket's dominant frequency, already mapped to 0...1 by
        /// log-linear interpolation between real-world landmark frequencies
        /// (60Hz/1000Hz/16kHz -- see SpectrumAnalyzer.normalizedLogPosition),
        /// not a blind sweep across the full 20Hz-20kHz audible range: real
        /// bass content barely reaches down toward 20Hz, so a full-range
        /// sweep left almost no hue room for it and pushed a kick/808's
        /// attack transient into yellow well before it was actually
        /// midrange. See SpectrumAnalyzer.analyze for how "dominant" is
        /// weighted, and WaveformView for how this becomes a single hue. Deliberately
        /// NOT three separate low/mid/high energies blended as RGB
        /// primaries -- an earlier version did that, and additively mixing
        /// red+green+blue light in comparable amounts washes toward grey,
        /// which made a distorted (broadband-harmonic) 808 read as a muddy
        /// grey-purple next to a clean 808 of the same fundamental reading
        /// as pure red, even though both are clearly "bass" sounds. A
        /// single picked hue stays fully saturated regardless of how
        /// broadband the underlying sound is.
        public let dominantFrequencyPosition: Float
        /// 0...1, normalized to this file's own loudest bucket -- how much
        /// spectral energy this bucket carries at all, so a near-silent
        /// bucket can fall back to a neutral color instead of a meaningless
        /// hue picked from noise.
        public let spectralEnergy: Float
    }

    public enum WaveformError: Error {
        case emptyFile
    }

    /// `bucketCount` buckets, each holding the min/max sample value across
    /// its slice of the file -- the standard "peak waveform" technique --
    /// plus a per-bucket dominant-frequency reading for color coding.
    public static func generate(fileURL: URL, bucketCount: Int = 300) throws -> [Peak] {
        let file = try AVAudioFile(forReading: fileURL)
        let frameCount = AVAudioFrameCount(file.length)
        guard frameCount > 0 else { throw WaveformError.emptyFile }

        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frameCount) else {
            throw WaveformError.emptyFile
        }
        try file.read(into: buffer)

        guard let channelData = buffer.floatChannelData else { throw WaveformError.emptyFile }
        let channelCount = Int(buffer.format.channelCount)
        let sampleCount = Int(buffer.frameLength)
        guard sampleCount > 0 else { throw WaveformError.emptyFile }

        // Average across channels up front so stereo files still produce one
        // waveform (and one frequency analysis), not an interleaved/left-only one.
        var mono = [Float](repeating: 0, count: sampleCount)
        for frame in 0..<sampleCount {
            var sum: Float = 0
            for channel in 0..<channelCount {
                sum += channelData[channel][frame]
            }
            mono[frame] = sum / Float(channelCount)
        }

        let sampleRate = buffer.format.sampleRate
        let analyzer = SpectrumAnalyzer(sampleRate: sampleRate)

        let bucketCount = max(1, min(bucketCount, sampleCount))
        let samplesPerBucket = max(1, sampleCount / bucketCount)

        var bucketMins: [Float] = []
        var bucketMaxes: [Float] = []
        var dominantFrequencies: [Float] = []
        var totalEnergies: [Float] = []

        for bucket in 0..<bucketCount {
            let start = bucket * samplesPerBucket
            let end = bucket == bucketCount - 1 ? sampleCount : min(start + samplesPerBucket, sampleCount)
            guard start < end else { continue }

            var bucketMin: Float = .greatestFiniteMagnitude
            var bucketMax: Float = -.greatestFiniteMagnitude
            for frame in start..<end {
                let value = mono[frame]
                bucketMin = min(bucketMin, value)
                bucketMax = max(bucketMax, value)
            }
            bucketMins.append(bucketMin)
            bucketMaxes.append(bucketMax)

            let analysis = analyzer.analyze(mono: mono, bucketStart: start, bucketEnd: end)
            dominantFrequencies.append(analysis.dominantFrequencyHz)
            totalEnergies.append(analysis.totalEnergy)
        }

        let energyMax = totalEnergies.max() ?? 0

        return (0..<bucketMins.count).map { i in
            Peak(
                min: bucketMins[i],
                max: bucketMaxes[i],
                dominantFrequencyPosition: analyzer.normalizedLogPosition(forHz: dominantFrequencies[i]),
                spectralEnergy: energyMax > 0 ? totalEnergies[i] / energyMax : 0
            )
        }
    }
}

/// Real FFT-based dominant-frequency analysis via Accelerate's vDSP (ships
/// with macOS, no new dependency). Not private: WaveformGeneratorTests
/// exercises `analyze`/`normalizedLogPosition` directly against synthetic
/// tones via `@testable import`.
///
/// Uses a fixed-size analysis window (independent of the caller's bucket
/// width) centered on each bucket, rather than FFT-ing the bucket's own
/// samples directly -- a display bucket can be very short (a few hundred
/// samples for a short file split into 300 buckets), and FFT frequency
/// resolution is sampleRate/N, so a too-short window simply cannot resolve
/// bass content at all. A fixed 4096-sample window resolves ~10.8Hz/bin at
/// 44.1kHz, comfortably separating sub-bass content regardless of how the
/// display buckets are sliced.
final class SpectrumAnalyzer {
    private let n = 4096
    private let log2n: vDSP_Length
    private let setup: FFTSetup
    private let hannWindow: [Float]
    private let sampleRate: Double

    /// Bounds of the log-frequency scale the hue gradient sweeps across --
    /// roughly the audible range. Frequencies are clamped into this range
    /// before their log is taken, so bin 0 (DC) doesn't need special-casing
    /// beyond being skipped entirely (see `analyze`).
    private let minHz: Float = 20
    private let maxHz: Float = 20000

    /// How strongly the weighted average favors the loudest bins over
    /// quieter ones when picking "the" dominant frequency for a bucket.
    /// 1.0 would be a plain energy-weighted centroid, where an evenly
    /// spread (broadband/distorted) signal gets pulled toward the middle
    /// of its spread; this is what a naive centroid gets wrong for a
    /// distorted 808 that still has a clearly dominant bass fundamental
    /// plus a haze of quieter harmonics. Squaring the energy again here
    /// (effectively weighting by magnitude^4) makes the result behave much
    /// more like "whichever frequency is loudest wins" while staying a
    /// smooth function of the spectrum rather than a jittery hard argmax.
    private let dominanceBias: Float = 2.0

    init(sampleRate: Double) {
        self.sampleRate = sampleRate
        self.log2n = vDSP_Length(log2(Double(n)))
        // Created once per file (not once per bucket) -- vDSP_create_fftsetup
        // has real setup cost that would dominate if paid per bucket.
        self.setup = vDSP_create_fftsetup(log2n, FFTRadix(kFFTRadix2))!
        let windowSize = n
        self.hannWindow = (0..<windowSize).map { 0.5 * (1 - cosf(2 * Float.pi * Float($0) / Float(windowSize - 1))) }
    }

    deinit {
        vDSP_destroy_fftsetup(setup)
    }

    /// `dominantFrequencyHz`: a magnitude^(1+dominanceBias)-weighted average
    /// of log-frequency across the spectrum, converted back to Hz. `totalEnergy`:
    /// overall energy in this window, for the caller to normalize/threshold against.
    func analyze(mono: [Float], bucketStart: Int, bucketEnd: Int) -> (dominantFrequencyHz: Float, totalEnergy: Float) {
        let center = (bucketStart + bucketEnd) / 2
        let readStart = center - n / 2

        var windowed = [Float](repeating: 0, count: n)
        for i in 0..<n {
            let sourceIndex = readStart + i
            guard sourceIndex >= 0, sourceIndex < mono.count else { continue }
            windowed[i] = mono[sourceIndex] * hannWindow[i]
        }

        var realp = [Float](repeating: 0, count: n / 2)
        var imagp = [Float](repeating: 0, count: n / 2)
        var magnitudesSquared = [Float](repeating: 0, count: n / 2)

        realp.withUnsafeMutableBufferPointer { realPtr in
            imagp.withUnsafeMutableBufferPointer { imagPtr in
                var splitComplex = DSPSplitComplex(realp: realPtr.baseAddress!, imagp: imagPtr.baseAddress!)
                windowed.withUnsafeBufferPointer { windowedPtr in
                    windowedPtr.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: n / 2) { complexPtr in
                        vDSP_ctoz(complexPtr, 2, &splitComplex, 1, vDSP_Length(n / 2))
                    }
                }
                vDSP_fft_zrip(setup, &splitComplex, 1, log2n, FFTDirection(FFT_FORWARD))
                vDSP_zvmags(&splitComplex, 1, &magnitudesSquared, 1, vDSP_Length(n / 2))
            }
        }

        let binHz = Float(sampleRate / Double(n))
        var weightedLogFreqSum: Float = 0
        var weightSum: Float = 0
        var totalEnergy: Float = 0

        // Bin 0 is skipped: it's DC (frequency 0, log undefined), and the
        // real-FFT packing trick also folds the Nyquist bin's value into
        // its imaginary slot -- both negligible to skip for this purpose.
        for bin in 1..<(n / 2) {
            let freq = min(max(Float(bin) * binHz, minHz), maxHz)
            let magnitudeSquared = magnitudesSquared[bin]
            totalEnergy += magnitudeSquared
            let weight = pow(magnitudeSquared, 1 + dominanceBias)
            weightedLogFreqSum += weight * log2(freq)
            weightSum += weight
        }

        let dominantFrequencyHz = weightSum > 0 ? exp2(weightedLogFreqSum / weightSum) : minHz
        return (dominantFrequencyHz, sqrt(totalEnergy))
    }

    /// Landmark frequencies, spread evenly (0, 0.5, 1) across the 0...1
    /// position this maps to -- NOT the extremes of the audible range (20Hz,
    /// 20kHz). A single log-linear sweep across the full 20Hz-20kHz span
    /// spends most of its low end on sub-20Hz-adjacent frequencies almost
    /// nothing in this library ever reaches, so real bass content (a kick
    /// or 808's ~40-150Hz fundamental) only occupied the first ~15-20% of
    /// that range -- meaning a kick/808's broadband attack transient, whose
    /// energy centers a bit higher than the sustain tone's pure fundamental
    /// (a normal feature of a percussive attack, not a bug), was enough to
    /// cross out of "red" into orange/yellow well before the sound was
    /// actually midrange. Anchoring to 60Hz (a typical sub-bass/808/kick
    /// fundamental), 1000Hz (a standard "presence"/midrange reference), and
    /// 16kHz (near the top of perceptually relevant treble/cymbal content)
    /// keeps real bass content compressed into a narrow, solidly red band
    /// instead of spread across a wide swath that bleeds into yellow.
    private static let hueAnchorsHz: [Float] = [60, 1000, 16000]

    /// Maps a frequency to 0...1 by log-linear interpolation between
    /// `hueAnchorsHz` (clamped at the ends), for the caller to turn into a
    /// hue -- position 0/0.5/1.0 line up exactly with the 3 anchors.
    func normalizedLogPosition(forHz hz: Float) -> Float {
        let anchors = Self.hueAnchorsHz
        if hz <= anchors[0] { return 0 }
        if hz >= anchors[anchors.count - 1] { return 1 }

        let segmentCount = anchors.count - 1
        for i in 0..<segmentCount {
            let lo = anchors[i]
            let hi = anchors[i + 1]
            guard hz <= hi else { continue }
            let t = (log2(hz) - log2(lo)) / (log2(hi) - log2(lo))
            return (Float(i) + t) / Float(segmentCount)
        }
        return 1
    }
}
