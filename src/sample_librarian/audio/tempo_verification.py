"""Verifies a *claimed* BPM against the audio itself, rather than
independently estimating tempo from scratch and comparing -- per Johnny
(2026-08-25): "it may be easier to just see if the labelled bpm matches the
file rather than extracting from the file and seeing if it matches the
label." Verifying a specific hypothesis (does a beat land every 60/bpm
seconds?) is a much more tractable problem than open-ended tempo detection,
which is itself an unsolved-in-general MIR problem prone to octave errors
(reporting half or double the real tempo).

Method: a standard, simple onset-strength autocorrelation. Split the audio
into short frames, compute an RMS energy envelope, take its half-wave
rectified first difference (a basic "energy novelty" onset function -- sharp
energy increases show up as peaks), then check whether that envelope
correlates with itself at a lag equal to the claimed tempo's beat period. If
it does about as well as the *best* lag found across the whole plausible
tempo range, the claimed tempo is well-supported by real periodic content in
the audio. If the true periodicity is somewhere else entirely (or there's no
periodicity at all -- e.g. a one-shot hit with no repeating beat, or the
claimed tempo implies a beat period longer than the whole file), it isn't.

This only ever says "does the audio support this claimed number", not "here
is the true tempo" -- it doesn't attempt to guess a replacement if the
claimed one fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sample_librarian.audio import riff_chunks

_FRAME_SECONDS = 0.010
_MIN_SEARCH_BPM = 40.0
_MAX_SEARCH_BPM = 220.0
_SUPPORTED_RATIO_THRESHOLD = 0.85


@dataclass(frozen=True)
class TempoVerificationResult:
    supported: bool
    # claimed-tempo correlation strength as a fraction of the best
    # correlation found anywhere in the plausible tempo range (0..1ish).
    confidence: float


_PCM_INTEGER = 1
_PCM_FLOAT = 3


def _decode_pcm(raw_bytes: bytes, fmt) -> np.ndarray | None:
    """Interleaved samples, normalized to roughly [-1, 1]. Handles the
    formats actually found in real sample-pack WAVs: 16/24/32-bit integer
    PCM and 32-bit IEEE float. 24-bit has no native numpy dtype, so it's
    unpacked a byte at a time and sign-extended via the standard
    shift-up-then-arithmetic-shift-down trick.
    """
    if fmt.audio_format == _PCM_FLOAT and fmt.bits_per_sample == 32:
        n = len(raw_bytes) // 4
        return np.frombuffer(raw_bytes[: n * 4], dtype="<f4")

    if fmt.audio_format != _PCM_INTEGER:
        return None

    if fmt.bits_per_sample == 16:
        n = len(raw_bytes) // 2
        return np.frombuffer(raw_bytes[: n * 2], dtype="<i2").astype(np.float32) / 32768.0

    if fmt.bits_per_sample == 24:
        n = len(raw_bytes) // 3
        buf = np.frombuffer(raw_bytes[: n * 3], dtype=np.uint8).reshape(-1, 3)
        packed = buf[:, 0].astype(np.uint32) | (buf[:, 1].astype(np.uint32) << 8) | (buf[:, 2].astype(np.uint32) << 16)
        signed = (packed << 8).astype(np.int32) >> 8  # sign-extend the 24-bit value
        return signed.astype(np.float32) / float(1 << 23)

    if fmt.bits_per_sample == 32:
        n = len(raw_bytes) // 4
        return np.frombuffer(raw_bytes[: n * 4], dtype="<i4").astype(np.float32) / float(1 << 31)

    return None


def _read_mono_float_samples(path: Path) -> tuple[np.ndarray, int] | None:
    chunks = riff_chunks.read_chunks(path)
    fmt = riff_chunks.read_fmt(chunks)
    data_chunk = riff_chunks.get_chunk(chunks, "data")
    if fmt is None or data_chunk is None or fmt.channels < 1:
        return None

    raw = _decode_pcm(data_chunk.data, fmt)
    if raw is None:
        return None
    if fmt.channels > 1:
        usable_frames = len(raw) - (len(raw) % fmt.channels)
        raw = raw[:usable_frames].reshape(-1, fmt.channels).mean(axis=1)
    return raw, fmt.sample_rate


def _onset_envelope(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    frame_len = max(1, int(_FRAME_SECONDS * sample_rate))
    num_frames = len(samples) // frame_len
    if num_frames < 2:
        return np.array([])
    trimmed = samples[: num_frames * frame_len].reshape(num_frames, frame_len)
    rms = np.sqrt(np.mean(trimmed.astype(np.float64) ** 2, axis=1))
    flux = np.diff(rms)
    flux[flux < 0] = 0
    return flux - flux.mean()


def _autocorr_at_bpm(envelope: np.ndarray, bpm: float) -> float:
    frame_rate = 1.0 / _FRAME_SECONDS
    lag_frames = round(frame_rate * 60.0 / bpm)
    if lag_frames < 1 or lag_frames >= len(envelope):
        return 0.0
    a, b = envelope[:-lag_frames], envelope[lag_frames:]
    denom = np.sqrt(np.sum(a**2) * np.sum(b**2))
    if denom == 0:
        return 0.0
    return float(np.sum(a * b) / denom)


def verify_tempo(path: Path, claimed_bpm: float) -> TempoVerificationResult | None:
    """None if the file couldn't be analyzed at all (unsupported format, or
    too short/quiet to build any onset envelope) -- callers should treat
    that as "couldn't check", not as a pass or fail.
    """
    loaded = _read_mono_float_samples(path)
    if loaded is None:
        return None
    samples, sample_rate = loaded
    envelope = _onset_envelope(samples, sample_rate)
    if len(envelope) < 8:
        return None

    # Half/double-time is a common, benign labeling ambiguity (a groove felt
    # in half-time is still "correct" at 2x), so either counts as support.
    claimed_score = max(
        _autocorr_at_bpm(envelope, claimed_bpm),
        _autocorr_at_bpm(envelope, claimed_bpm * 2),
        _autocorr_at_bpm(envelope, claimed_bpm / 2) if claimed_bpm / 2 >= _MIN_SEARCH_BPM else 0.0,
    )

    candidate_bpms = np.arange(_MIN_SEARCH_BPM, _MAX_SEARCH_BPM + 1.0, 1.0)
    best_score = max(_autocorr_at_bpm(envelope, bpm) for bpm in candidate_bpms)

    if best_score <= 0:
        return TempoVerificationResult(supported=False, confidence=0.0)

    ratio = min(1.0, claimed_score / best_score)
    return TempoVerificationResult(supported=ratio >= _SUPPORTED_RATIO_THRESHOLD, confidence=ratio)
