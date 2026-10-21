import XCTest
@testable import SampleLibrarianCore

final class WaveformGeneratorTests: XCTestCase {
    /// A minimal 16-bit PCM mono WAV alternating between two fixed amplitudes,
    /// so every multi-sample bucket predictably contains both the min and max.
    private func writeAlternatingWav(sampleCount: Int, amplitude: Int16 = 16000) throws -> URL {
        let sampleRate: UInt32 = 44100
        let channels: UInt16 = 1
        let bitsPerSample: UInt16 = 16
        let blockAlign = channels * (bitsPerSample / 8)
        let byteRate = sampleRate * UInt32(blockAlign)

        var samples: [Int16] = []
        samples.reserveCapacity(sampleCount)
        for i in 0..<sampleCount {
            samples.append(i % 2 == 0 ? amplitude : -amplitude)
        }
        var dataBytes = Data()
        for sample in samples {
            withUnsafeBytes(of: sample.littleEndian) { dataBytes.append(contentsOf: $0) }
        }

        var fmtBody = Data()
        withUnsafeBytes(of: UInt16(1).littleEndian) { fmtBody.append(contentsOf: $0) }  // PCM
        withUnsafeBytes(of: channels.littleEndian) { fmtBody.append(contentsOf: $0) }
        withUnsafeBytes(of: sampleRate.littleEndian) { fmtBody.append(contentsOf: $0) }
        withUnsafeBytes(of: byteRate.littleEndian) { fmtBody.append(contentsOf: $0) }
        withUnsafeBytes(of: blockAlign.littleEndian) { fmtBody.append(contentsOf: $0) }
        withUnsafeBytes(of: bitsPerSample.littleEndian) { fmtBody.append(contentsOf: $0) }

        var body = Data()
        body.append(contentsOf: "fmt ".utf8)
        withUnsafeBytes(of: UInt32(fmtBody.count).littleEndian) { body.append(contentsOf: $0) }
        body.append(fmtBody)
        body.append(contentsOf: "data".utf8)
        withUnsafeBytes(of: UInt32(dataBytes.count).littleEndian) { body.append(contentsOf: $0) }
        body.append(dataBytes)

        var file = Data()
        file.append(contentsOf: "RIFF".utf8)
        withUnsafeBytes(of: UInt32(4 + body.count).littleEndian) { file.append(contentsOf: $0) }
        file.append(contentsOf: "WAVE".utf8)
        file.append(body)

        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension("wav")
        try file.write(to: url)
        return url
    }

    func testGeneratesRequestedBucketCount() throws {
        let url = try writeAlternatingWav(sampleCount: 4410)
        defer { try? FileManager.default.removeItem(at: url) }

        let peaks = try WaveformGenerator.generate(fileURL: url, bucketCount: 100)
        XCTAssertEqual(peaks.count, 100)
    }

    func testPeaksCaptureBothExtremesOfAlternatingSignal() throws {
        let url = try writeAlternatingWav(sampleCount: 4410, amplitude: 16000)
        defer { try? FileManager.default.removeItem(at: url) }

        let peaks = try WaveformGenerator.generate(fileURL: url, bucketCount: 50)
        let expected: Float = 16000.0 / 32768.0

        for peak in peaks {
            XCTAssertEqual(peak.max, expected, accuracy: 0.01)
            XCTAssertEqual(peak.min, -expected, accuracy: 0.01)
        }
    }

    func testBucketCountNeverExceedsSampleCount() throws {
        let url = try writeAlternatingWav(sampleCount: 10)
        defer { try? FileManager.default.removeItem(at: url) }

        let peaks = try WaveformGenerator.generate(fileURL: url, bucketCount: 300)
        XCTAssertLessThanOrEqual(peaks.count, 10)
        XCTAssertFalse(peaks.isEmpty)
    }

    /// SpectrumAnalyzer.analyze should recover a pure tone's actual
    /// frequency, not just bucket it into a broad band -- this is what lets
    /// WaveformView pick one confident, fully-saturated hue per bucket
    /// instead of blending fixed RGB primaries (see Peak's doc comment for
    /// why that blending approach washed distorted/broadband sounds toward
    /// grey). ~10.8Hz/bin resolution at 44.1kHz/4096 easily resolves a pure
    /// tone to within a bin or two, hence the tight accuracy here.
    func testSubBassToneRecoversItsOwnFrequency() {
        let sampleRate = 44100.0
        let mono = sineWave(frequencyHz: 60, sampleRate: sampleRate, sampleCount: 4096 * 4)

        let analyzer = SpectrumAnalyzer(sampleRate: sampleRate)
        let result = analyzer.analyze(mono: mono, bucketStart: mono.count / 2 - 100, bucketEnd: mono.count / 2 + 100)

        XCTAssertEqual(result.dominantFrequencyHz, 60, accuracy: 15)
    }

    func testTrebleToneRecoversItsOwnFrequency() {
        let sampleRate = 44100.0
        let mono = sineWave(frequencyHz: 10000, sampleRate: sampleRate, sampleCount: 4096 * 4)

        let analyzer = SpectrumAnalyzer(sampleRate: sampleRate)
        let result = analyzer.analyze(mono: mono, bucketStart: mono.count / 2 - 100, bucketEnd: mono.count / 2 + 100)

        XCTAssertEqual(result.dominantFrequencyHz, 10000, accuracy: 500)
    }

    /// The actual bug report this exists to prevent regressing: a loud bass
    /// tone plus a much quieter high-frequency haze (a synthetic stand-in
    /// for a distorted 808's harmonic overtones) should still read as
    /// dominantly bass, not get pulled toward the middle the way a plain
    /// (unbiased) energy-weighted centroid would.
    func testDominantFrequencyBiasesTowardTheLouderTone() {
        let sampleRate = 44100.0
        let sampleCount = 4096 * 4
        var mono = [Float](repeating: 0, count: sampleCount)
        for i in 0..<sampleCount {
            let t = Float(i) / Float(sampleRate)
            mono[i] = sinf(2 * Float.pi * 60 * t) + 0.05 * sinf(2 * Float.pi * 8000 * t)
        }

        let analyzer = SpectrumAnalyzer(sampleRate: sampleRate)
        let result = analyzer.analyze(mono: mono, bucketStart: sampleCount / 2 - 100, bucketEnd: sampleCount / 2 + 100)

        XCTAssertLessThan(result.dominantFrequencyHz, 500)
    }

    func testNormalizedLogPositionIsMonotonicAndBounded() {
        let analyzer = SpectrumAnalyzer(sampleRate: 44100)

        let low = analyzer.normalizedLogPosition(forHz: 60)
        let mid = analyzer.normalizedLogPosition(forHz: 1000)
        let high = analyzer.normalizedLogPosition(forHz: 10000)

        XCTAssertLessThan(low, mid)
        XCTAssertLessThan(mid, high)
        XCTAssertGreaterThanOrEqual(low, 0)
        XCTAssertLessThanOrEqual(high, 1)
    }

    /// The exact bug report this exists to prevent regressing: a kick/808's
    /// broadband attack transient naturally centers a bit higher than the
    /// sustain tone's pure fundamental (a normal feature of a percussive
    /// attack). Under the old blind log-linear sweep across the full
    /// 20Hz-20kHz range, ~100Hz landed around hue 55 degrees (yellow). The
    /// 60Hz/1000Hz/16kHz-anchored mapping should keep it comfortably in
    /// red/orange territory (well under the halfway point to green).
    func testTransientCenteredJustAboveSubBassStaysNearRedNotYellow() {
        let analyzer = SpectrumAnalyzer(sampleRate: 44100)

        let position = analyzer.normalizedLogPosition(forHz: 100)
        let hueDegrees = Double(position) * 240

        XCTAssertLessThan(hueDegrees, 30)
    }

    /// The 3 landmark frequencies should land exactly on 0, 0.5, and 1.
    func testAnchorFrequenciesMapExactlyToEvenThirds() {
        let analyzer = SpectrumAnalyzer(sampleRate: 44100)

        XCTAssertEqual(analyzer.normalizedLogPosition(forHz: 60), 0, accuracy: 0.001)
        XCTAssertEqual(analyzer.normalizedLogPosition(forHz: 1000), 0.5, accuracy: 0.001)
        XCTAssertEqual(analyzer.normalizedLogPosition(forHz: 16000), 1, accuracy: 0.001)
    }

    private func sineWave(frequencyHz: Float, sampleRate: Double, sampleCount: Int) -> [Float] {
        (0..<sampleCount).map { sinf(2 * Float.pi * frequencyHz * Float($0) / Float(sampleRate)) }
    }
}
