"""Format-dispatching metadata extraction: embedded metadata first, filename
regex as fallback for whichever of bpm/key it didn't find.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sample_librarian.audio import compressed_tags, filename_regex, probe, riff_chunks


class UnsupportedFormatError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedMetadata:
    bpm: float | None
    bpm_source: str | None  # 'embedded_acid' | 'embedded_id3' | 'filename_regex' | None
    musical_key: str | None
    key_source: str | None
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    acid_chunk_present: bool


def _sniff_format(path: Path) -> str | None:
    """A file's extension isn't always trustworthy -- found in the wild:
    a Logic Pro export that's genuinely AIFF content (its header literally
    says 'Creator: Logic Pro') sitting on disk with a .m4a extension. Sniff
    magic bytes and prefer that over the extension when they disagree.
    Returns 'wav' | 'aiff' | 'flac' | 'mp4' | 'mp3' | None (inconclusive).
    """
    try:
        with path.open("rb") as f:
            header = f.read(12)
    except OSError:
        return None

    if len(header) < 12:
        return None
    if header[0:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    if header[0:4] == b"FORM" and header[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if header[0:4] == b"fLaC":
        return "flac"
    if header[4:8] == b"ftyp":
        return "mp4"
    if header[0:3] == b"ID3" or (header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


_EXTENSION_TO_FORMAT = {
    ".wav": "wav",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".mp3": "mp3",
    ".m4a": "mp4",
    ".flac": "flac",
}


def extract(path: Path) -> ExtractedMetadata:
    fmt = _sniff_format(path) or _EXTENSION_TO_FORMAT.get(path.suffix.lower())
    if fmt == "wav":
        return _extract_wav(path)
    if fmt == "aiff":
        return _extract_aiff(path)
    if fmt in ("mp3", "flac", "mp4"):
        return _extract_compressed(path)
    raise UnsupportedFormatError(path.suffix.lower())


def _with_filename_fallback(path: Path, bpm, bpm_source, key, key_source):
    if bpm is None:
        fallback_bpm = filename_regex.extract_bpm(path.name)
        if fallback_bpm is not None:
            bpm, bpm_source = fallback_bpm, "filename_regex"
    if key is None:
        fallback_key = filename_regex.extract_key(path.name)
        if fallback_key is not None:
            key, key_source = fallback_key, "filename_regex"
    return bpm, bpm_source, key, key_source


def _extract_wav(path: Path) -> ExtractedMetadata:
    chunks = riff_chunks.read_chunks(path)
    fmt = riff_chunks.read_fmt(chunks)
    duration = riff_chunks.read_duration_seconds(chunks)
    acid = riff_chunks.read_acid(chunks)

    bpm = bpm_source = key = key_source = None
    acid_present = acid is not None
    if acid is not None:
        if acid.tempo and acid.tempo > 0:
            bpm, bpm_source = acid.tempo, "embedded_acid"
        if acid.root_pitch_class is not None:
            key, key_source = acid.root_pitch_class, "embedded_acid"

    bpm, bpm_source, key, key_source = _with_filename_fallback(path, bpm, bpm_source, key, key_source)

    return ExtractedMetadata(
        bpm=bpm,
        bpm_source=bpm_source,
        musical_key=key,
        key_source=key_source,
        duration_seconds=duration,
        sample_rate=fmt.sample_rate if fmt else None,
        channels=fmt.channels if fmt else None,
        acid_chunk_present=acid_present,
    )


def _extract_aiff(path: Path) -> ExtractedMetadata:
    # No AIFF-specific chunk parser yet (AIFF's tempo/root-note equivalent lives
    # in INST/basc chunks, not implemented in v1) -- ffprobe covers duration/
    # sample-rate/channels fine, filename regex is the only bpm/key source.
    result = probe.probe(path)
    bpm, bpm_source, key, key_source = _with_filename_fallback(path, None, None, None, None)
    return ExtractedMetadata(
        bpm=bpm,
        bpm_source=bpm_source,
        musical_key=key,
        key_source=key_source,
        duration_seconds=result.duration_seconds,
        sample_rate=result.sample_rate,
        channels=result.channels,
        acid_chunk_present=False,
    )


def _extract_compressed(path: Path) -> ExtractedMetadata:
    bpm, key = compressed_tags.read_tempo_key(path)
    bpm_source = "embedded_id3" if bpm is not None else None
    key_source = "embedded_id3" if key is not None else None

    bpm, bpm_source, key, key_source = _with_filename_fallback(path, bpm, bpm_source, key, key_source)

    result = probe.probe(path)
    return ExtractedMetadata(
        bpm=bpm,
        bpm_source=bpm_source,
        musical_key=key,
        key_source=key_source,
        duration_seconds=result.duration_seconds,
        sample_rate=result.sample_rate,
        channels=result.channels,
        acid_chunk_present=False,
    )
