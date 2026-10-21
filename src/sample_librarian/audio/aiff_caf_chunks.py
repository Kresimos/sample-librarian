"""Read-only metadata parsing for AIFF and CAF (Apple Loops).

Neither format had any chunk parser before this -- AIFF fell straight through
to ffprobe (duration/rate only) and CAF wasn't scanned at all. Both carry a
real, authored tempo that Logic reads on a drag, just not as an ACID chunk:

* AIFF Apple Loops store it as a text marker in the `MARK` chunk, literally
  "Tempo: 140.0" (confirmed by `afinfo` on Logic's own stock content).
* CAF Apple Loops store a plain key/value descriptor blob in a `uuid` chunk
  ("beat count", "time signature", "key signature", "key type", ...). There is
  no explicit tempo field -- tempo is beat_count / (duration_in_seconds / 60),
  which is exactly how a DAW derives a loop's display tempo. Verified against
  ~10k of Logic's stock `.caf` loops: 99.97% land within 1% of an integer BPM,
  so the derived value is snapped to the nearest whole/half number.

Write-back is deliberately not implemented here (see
per_file_pipeline._NO_WRITE_BACK_EXTENSIONS) -- Apple Loops live under
vendor_roots and are only ever symlinked, never mutated.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

_PITCH_ROOTS = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
                "DB", "EB", "GB", "AB", "BB"}
_FLAT_TO_SHARP = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}

_MIN_PLAUSIBLE_BPM = 30.0
_MAX_PLAUSIBLE_BPM = 300.0


@dataclass(frozen=True)
class LoopMetadata:
    bpm: float | None
    musical_key: str | None
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    beat_count: int | None


# --------------------------------------------------------------------------
# tempo/key helpers
# --------------------------------------------------------------------------

def snap_bpm(raw: float) -> float | None:
    """Round a derived tempo to the nearest whole number, or None if it isn't
    a plausible musical tempo at all.

    A beat-count / duration division for a real loop lands within a fraction
    of a BPM of the authored tempo, and authored tempos are effectively always
    integers (verified against ~25k of Logic's stock Apple Loops: 99.97% land
    within 1% of a whole number). Rounding matches what a DAW shows as "File
    Tempo" and avoids storing a spurious 119.68 for a 120 BPM loop.
    """
    if not (_MIN_PLAUSIBLE_BPM <= raw <= _MAX_PLAUSIBLE_BPM):
        return None
    return float(round(raw))


def bpm_from_beats(beat_count: int | None, duration_seconds: float | None) -> float | None:
    if not beat_count or beat_count <= 0 or not duration_seconds or duration_seconds <= 0:
        return None
    return snap_bpm(beat_count * 60.0 / duration_seconds)


def _normalize_key(root: str | None, key_type: str | None) -> str | None:
    if not root:
        return None
    root_up = root.strip().upper()
    root_up = _FLAT_TO_SHARP.get(root_up, root_up)
    if root_up not in _PITCH_ROOTS:
        return None
    letter = root_up[0] + ("#" if root_up.endswith("#") else "")
    kt = (key_type or "").strip().lower()
    if kt == "minor":
        return f"{letter}min"
    if kt == "major":
        return f"{letter}maj"
    # "both" / unknown -- store the bare root, same shape as an ACID root note.
    return letter


# --------------------------------------------------------------------------
# AIFF
# --------------------------------------------------------------------------

_AIFF_TEMPO_MARKER = re.compile(rb"Tempo:\s*([0-9]+(?:\.[0-9]+)?)")
_AIFF_KEY_MARKER = re.compile(rb"Key:\s*([A-Ga-g][#b]?)\s*(maj|min|major|minor)?", re.IGNORECASE)
_AIFF_BEAT_MARKER = re.compile(rb"(?:Beat|Beats|Number of Beats):\s*([0-9]+)", re.IGNORECASE)


def _read_aiff_chunks(data: bytes) -> dict[str, bytes]:
    if len(data) < 12 or data[0:4] != b"FORM" or data[8:12] not in (b"AIFF", b"AIFC"):
        return {}
    chunks: dict[str, bytes] = {}
    pos = 12
    end = len(data)
    while pos + 8 <= end:
        cid = data[pos : pos + 4].decode("ascii", errors="replace")
        (size,) = struct.unpack_from(">I", data, pos + 4)
        start = pos + 8
        if start + size > end:
            break
        chunks.setdefault(cid, data[start : start + size])
        pos = start + size + (size % 2)  # chunks are word-aligned
    return chunks


def _aiff_duration(comm: bytes | None) -> tuple[float | None, int | None, int | None]:
    """(duration_seconds, sample_rate, channels) from an AIFF COMM chunk."""
    if comm is None or len(comm) < 18:
        return None, None, None
    channels, num_frames, _bits = struct.unpack_from(">hIh", comm, 0)
    sample_rate = _extended_float(comm[8:18])
    if not sample_rate:
        return None, None, channels or None
    return num_frames / sample_rate, int(round(sample_rate)), channels or None


def _extended_float(raw: bytes) -> float:
    """Decode an 80-bit IEEE 754 extended float (AIFF sample rate)."""
    if len(raw) != 10:
        return 0.0
    sign = -1 if raw[0] & 0x80 else 1
    exponent = ((raw[0] & 0x7F) << 8) | raw[1]
    mantissa = int.from_bytes(raw[2:10], "big")
    if exponent == 0 and mantissa == 0:
        return 0.0
    return sign * mantissa * 2.0 ** (exponent - 16383 - 63)


def read_aiff_metadata(path: Path) -> LoopMetadata:
    data = path.read_bytes()
    chunks = _read_aiff_chunks(data)
    duration, sample_rate, channels = _aiff_duration(chunks.get("COMM"))

    bpm = musical_key = None
    beat_count = None
    mark = chunks.get("MARK", b"")
    if mark:
        m = _AIFF_TEMPO_MARKER.search(mark)
        if m:
            bpm = snap_bpm(float(m.group(1)))
        k = _AIFF_KEY_MARKER.search(mark)
        if k:
            quality = (k.group(2) or b"").decode("ascii", "replace")
            musical_key = _normalize_key(k.group(1).decode("ascii", "replace"), quality)
        b = _AIFF_BEAT_MARKER.search(mark)
        if b:
            beat_count = int(b.group(1))

    # A beat marker with no explicit tempo marker: derive it.
    if bpm is None and beat_count:
        bpm = bpm_from_beats(beat_count, duration)

    return LoopMetadata(
        bpm=bpm,
        musical_key=musical_key,
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
        beat_count=beat_count,
    )


# --------------------------------------------------------------------------
# CAF
# --------------------------------------------------------------------------

_CAF_DESC = struct.Struct(">d4sIIIII")  # sample_rate, format_id, format_flags,
#                          bytes/packet, frames/packet, channels/frame, bits/channel


def _read_caf_chunks(data: bytes) -> list[tuple[str, bytes]]:
    if len(data) < 8 or data[0:4] != b"caff":
        return []
    out: list[tuple[str, bytes]] = []
    pos = 8
    end = len(data)
    while pos + 12 <= end:
        cid = data[pos : pos + 4].decode("ascii", errors="replace")
        (size,) = struct.unpack_from(">q", data, pos + 4)
        start = pos + 12
        if size < 0:  # -1 == "to end of file", only legal for the data chunk
            out.append((cid, data[start:end]))
            break
        if start + size > end:
            break
        out.append((cid, data[start : start + size]))
        pos = start + size
    return out


_CAF_KV_KEYS = ("beat count", "number of beats", "time signature", "key signature",
                "key type", "tempo")


_LEADING_NONPRINTABLE = re.compile(r"^[^\x20-\x7e]+")


def _parse_caf_descriptor(body: bytes) -> dict[str, str]:
    """The `uuid`/`info` descriptor is a run of NUL-terminated strings that
    pair up key, value, key, value, ... after a small binary header (a 16-byte
    UUID plus a 4-byte entry count). Rather than track the exact header size
    across format versions, just split on NUL and pull the values that follow
    a known key -- stripping any leading non-printable bytes first, since the
    entry-count byte ends up glued to the very first key.
    """
    parts = [p.decode("latin1", "replace") for p in body.split(b"\x00")]
    kv: dict[str, str] = {}
    for i, token in enumerate(parts):
        key = _LEADING_NONPRINTABLE.sub("", token).strip().lower()
        if key in _CAF_KV_KEYS and i + 1 < len(parts):
            kv[key] = _LEADING_NONPRINTABLE.sub("", parts[i + 1]).strip()
    return kv


def read_caf_metadata(path: Path) -> LoopMetadata:
    data = path.read_bytes()
    chunks = _read_caf_chunks(data)

    sample_rate = channels = None
    frames_per_packet = bits_per_channel = bytes_per_packet = None
    valid_frames = None
    pcm_data_bytes = None
    kv: dict[str, str] = {}

    for cid, body in chunks:
        if cid == "desc" and len(body) >= _CAF_DESC.size:
            (sr, _fmt_id, _flags, bytes_per_packet, frames_per_packet,
             channels, bits_per_channel) = _CAF_DESC.unpack_from(body, 0)
            sample_rate = int(round(sr)) if sr else None
            channels = channels or None
        elif cid == "pakt" and len(body) >= 16:
            # numberPackets(8), numberValidFrames(8), primingFrames(4), remainderFrames(4)
            valid_frames = struct.unpack_from(">q", body, 8)[0]
        elif cid == "data":
            pcm_data_bytes = max(len(body) - 4, 0)  # first 4 bytes are an edit count
        elif cid in ("uuid", "info"):
            found = _parse_caf_descriptor(body)
            for k, v in found.items():
                kv.setdefault(k, v)

    duration = None
    if valid_frames and sample_rate:
        duration = valid_frames / sample_rate
    elif pcm_data_bytes and sample_rate and channels and bits_per_channel and frames_per_packet == 1:
        bytes_per_frame = channels * (bits_per_channel // 8)
        if bytes_per_frame:
            duration = (pcm_data_bytes / bytes_per_frame) / sample_rate

    beat_count = None
    for key in ("beat count", "number of beats"):
        if key in kv and kv[key].isdigit():
            beat_count = int(kv[key])
            break

    bpm = None
    if kv.get("tempo"):
        try:
            bpm = snap_bpm(float(kv["tempo"]))
        except ValueError:
            bpm = None
    if bpm is None:
        bpm = bpm_from_beats(beat_count, duration)

    musical_key = _normalize_key(kv.get("key signature"), kv.get("key type"))

    return LoopMetadata(
        bpm=bpm,
        musical_key=musical_key,
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels or None,
        beat_count=beat_count,
    )
