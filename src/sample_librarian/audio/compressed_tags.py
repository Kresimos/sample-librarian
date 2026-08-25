"""Read/write embedded tempo+key metadata for MP3/M4A/FLAC via mutagen.

WAV/AIFF use riff_chunks.py instead (mutagen has no ACID chunk support).
Only tempo is ever written back (mirrors the ACID write-back behaviour) --
key write-back isn't required by anything downstream yet.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import ID3, TBPM, TKEY, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

_FLAC_BPM_KEY = "BPM"
_FLAC_MUSICAL_KEY = "INITIALKEY"
_MP4_KEY_FREEFORM = "----:com.apple.iTunes:initialkey"


class UnsupportedFormatError(Exception):
    pass


def read_tempo_key(path: Path) -> tuple[float | None, str | None]:
    ext = path.suffix.lower()
    if ext == ".mp3":
        return _read_mp3(path)
    if ext == ".flac":
        return _read_flac(path)
    if ext == ".m4a":
        return _read_mp4(path)
    raise UnsupportedFormatError(ext)


def write_tempo(path: Path, bpm: float) -> None:
    ext = path.suffix.lower()
    if ext == ".mp3":
        _write_mp3_tempo(path, bpm)
    elif ext == ".flac":
        _write_flac_tempo(path, bpm)
    elif ext == ".m4a":
        _write_mp4_tempo(path, bpm)
    else:
        raise UnsupportedFormatError(ext)


def _read_mp3(path: Path) -> tuple[float | None, str | None]:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return None, None
    bpm = None
    if "TBPM" in tags:
        try:
            bpm = float(str(tags["TBPM"].text[0]))
        except (ValueError, IndexError):
            bpm = None
    key = None
    if "TKEY" in tags:
        try:
            key = str(tags["TKEY"].text[0]) or None
        except IndexError:
            key = None
    return bpm, key


def _write_mp3_tempo(path: Path, bpm: float) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TBPM", [TBPM(encoding=3, text=[str(round(bpm))])])
    tags.save(path)


def _read_flac(path: Path) -> tuple[float | None, str | None]:
    audio = FLAC(path)
    bpm = None
    if _FLAC_BPM_KEY in audio:
        try:
            bpm = float(audio[_FLAC_BPM_KEY][0])
        except (ValueError, IndexError):
            bpm = None
    key = audio.get(_FLAC_MUSICAL_KEY, [None])[0]
    return bpm, key


def _write_flac_tempo(path: Path, bpm: float) -> None:
    audio = FLAC(path)
    audio[_FLAC_BPM_KEY] = [str(round(bpm))]
    audio.save()


def _read_mp4(path: Path) -> tuple[float | None, str | None]:
    audio = MP4(path)
    bpm = None
    if "tmpo" in audio:
        try:
            bpm = float(audio["tmpo"][0])
        except (ValueError, IndexError):
            bpm = None
    key = None
    if _MP4_KEY_FREEFORM in audio:
        try:
            key = audio[_MP4_KEY_FREEFORM][0].decode("utf-8") or None
        except (UnicodeDecodeError, IndexError):
            key = None
    return bpm, key


def _write_mp4_tempo(path: Path, bpm: float) -> None:
    audio = MP4(path)
    audio["tmpo"] = [round(bpm)]
    audio.save()
