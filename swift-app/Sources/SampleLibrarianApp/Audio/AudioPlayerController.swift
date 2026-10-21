import AVFoundation
import Foundation

/// Drives sample preview playback. Deliberately distinct verbs, per how the
/// browser uses this: `play`/`restart` always start from the beginning
/// (autoplay-as-you-browse, and Enter re-triggers the current sample from
/// the top), while `stop` is a real stop -- resets position, does not leave
/// anything paused/resumable -- because Space is specified to stop, not pause.
@MainActor
public final class AudioPlayerController: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published public private(set) var isPlaying = false
    @Published public private(set) var currentTime: TimeInterval = 0
    @Published public private(set) var duration: TimeInterval = 0
    @Published public private(set) var currentURL: URL?

    private var player: AVAudioPlayer?
    private var progressTimer: Timer?

    /// Samples are rarely trimmed to a zero crossing at the *end*, so an
    /// abrupt `AVAudioPlayer.stop()` mid-waveform produces an audible
    /// click/pop when browsing quickly cuts one off to start the next. A
    /// *linear* volume ramp isn't actually enough to fix this: it removes
    /// the value jump but not the slope discontinuity at its endpoints, and
    /// that residual kink shows up as an audible low-frequency thump --
    /// most noticeable exactly where a real fade was supposed to help, on
    /// bass-heavy content. `fade` below drives the ramp manually with a
    /// raised-cosine (Hann) curve instead, which has zero slope at both
    /// ends, so there's no discontinuity of any order to click on. Kept
    /// short enough (20ms) that it's inaudible as added latency -- the next
    /// sample still starts immediately in parallel (see `play`), so rapid
    /// browsing still feels instant. Deliberately one-directional (out
    /// only): a sample's *start* is trusted to already be a clean edit
    /// (that's what the file's own transient is), and fading it in would
    /// blunt the attack -- audible and undesirable on percussive/bass hits.
    private static let fadeDuration: TimeInterval = 0.02
    private static let fadeSteps = 20

    public override init() {}

    public func play(url: URL) {
        if let previous = player, previous.isPlaying {
            Self.fadeOutAndStop(previous)
        }
        do {
            let player = try AVAudioPlayer(contentsOf: url)
            player.delegate = self
            player.prepareToPlay()
            player.volume = 1.0
            player.play()
            self.player = player
            self.currentURL = url
            self.duration = player.duration
            self.isPlaying = true
            startProgressTimer()
        } catch {
            self.player = nil
            self.currentURL = nil
            self.isPlaying = false
        }
    }

    /// Restarts the currently loaded sample from the beginning (Enter key).
    /// If nothing is loaded, this is a no-op -- callers pass the selected
    /// sample's URL explicitly instead when there's any doubt.
    public func restart() {
        guard let player else { return }
        player.currentTime = 0
        player.volume = 1.0
        player.play()
        isPlaying = true
        startProgressTimer()
    }

    /// A true stop, not a pause (Space key): playback halts and position
    /// resets to the beginning, so a later restart/play always starts fresh.
    public func stop() {
        if let player, player.isPlaying {
            Self.fadeOutAndStop(player)
        } else {
            player?.currentTime = 0
        }
        isPlaying = false
        currentTime = 0
        stopProgressTimer()
    }

    /// Ramps `player` to silence, then actually stops it and resets it for
    /// reuse -- once the fade finishes, the player itself is idle again
    /// (position and volume reset) so a later `restart()` on the same
    /// instance still works normally.
    private static func fadeOutAndStop(_ player: AVAudioPlayer) {
        let startVolume = player.volume
        let totalSteps = fadeSteps
        var step = 0
        let interval = fadeDuration / Double(totalSteps)
        let timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { timer in
            step += 1
            let progress = Double(step) / Double(totalSteps)
            // Raised-cosine (Hann) taper -- see the doc comment on
            // `fadeDuration` for why cosine, not linear.
            let eased = Float(0.5 + 0.5 * cos(.pi * progress))
            player.volume = startVolume * eased
            if step >= totalSteps {
                timer.invalidate()
                player.stop()
                player.currentTime = 0
                player.volume = 1.0
            }
        }
        RunLoop.main.add(timer, forMode: .common)
    }

    private func startProgressTimer() {
        stopProgressTimer()
        let timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let player = self.player else { return }
                self.currentTime = player.currentTime
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        progressTimer = timer
    }

    private func stopProgressTimer() {
        progressTimer?.invalidate()
        progressTimer = nil
    }

    public nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.isPlaying = false
            self.currentTime = 0
            self.stopProgressTimer()
        }
    }
}
