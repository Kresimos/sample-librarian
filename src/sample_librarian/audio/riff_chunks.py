"""Hand-rolled RIFF/WAV chunk reader and writer.

No maintained Python library both reads AND writes the ACID chunk (tempo/root
note) that Logic Pro reads to auto-conform a dragged loop's tempo -- and
Python 3.13+ removed the stdlib `chunk`/`aifc`/`audioop` modules this would
once have leaned on -- so this parses the RIFF container directly.

Only WAV (RIFF/WAVE) is handled here. Reads are tolerant (skip unknown
chunks); writes only ever touch the 'acid' chunk, appending it if absent or
replacing it in place if present, and always write via a temp file + atomic
rename so a crash mid-write can never leave a half-written file behind.
"""

from __future__ import annotations

import struct
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_ACID_STRUCT = struct.Struct("<IHHfIHHf")  # type_of_file, root_note, reserved1, reserved2, num_beats, meter_denom, meter_numer, tempo
_ACID_ONE_SHOT_FLAG = 0x01
_ACID_ROOT_SET_FLAG = 0x02
_ACID_STRETCH_FLAG = 0x04


class RiffError(Exception):
    pass


@dataclass(frozen=True)
class RiffChunk:
    chunk_id: str  # 4-char id, e.g. 'fmt ', 'data', 'acid'
    offset: int  # byte offset of this chunk's data (after the 8-byte id+size header)
    size: int  # data size in bytes, excludes any padding byte
    data: bytes


@dataclass(frozen=True)
class FmtInfo:
    channels: int
    sample_rate: int
    bits_per_sample: int


@dataclass(frozen=True)
class AcidData:
    is_one_shot: bool
    root_note_set: bool
    root_note_midi: int
    num_beats: int
    meter_numerator: int
    meter_denominator: int
    tempo: float

    @property
    def root_pitch_class(self) -> str | None:
        if not self.root_note_set:
            return None
        return _PITCH_CLASSES[self.root_note_midi % 12]


def read_chunks(path: Path) -> list[RiffChunk]:
    data = path.read_bytes()
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RiffError(f"{path} is not a RIFF/WAVE file")

    chunks: list[RiffChunk] = []
    pos = 12
    end = len(data)
    while pos + 8 <= end:
        chunk_id = data[pos : pos + 4].decode("ascii", errors="replace")
        (size,) = struct.unpack_from("<I", data, pos + 4)
        data_start = pos + 8
        data_end = data_start + size
        if data_end > end:
            break  # truncated/corrupt trailing chunk, stop rather than raise
        chunks.append(RiffChunk(chunk_id, data_start, size, data[data_start:data_end]))
        pos = data_end + (size % 2)  # chunks are word-aligned, skip pad byte

    return chunks


def get_chunk(chunks: list[RiffChunk], chunk_id: str) -> RiffChunk | None:
    for chunk in chunks:
        if chunk.chunk_id == chunk_id:
            return chunk
    return None


def read_fmt(chunks: list[RiffChunk]) -> FmtInfo | None:
    fmt = get_chunk(chunks, "fmt ")
    if fmt is None or len(fmt.data) < 16:
        return None
    _audio_format, channels, sample_rate, _byte_rate, _block_align, bits_per_sample = (
        struct.unpack_from("<HHIIHH", fmt.data, 0)
    )
    return FmtInfo(channels=channels, sample_rate=sample_rate, bits_per_sample=bits_per_sample)


def read_duration_seconds(chunks: list[RiffChunk]) -> float | None:
    fmt = read_fmt(chunks)
    data_chunk = get_chunk(chunks, "data")
    if fmt is None or data_chunk is None or fmt.sample_rate == 0:
        return None
    bytes_per_frame = fmt.channels * (fmt.bits_per_sample // 8)
    if bytes_per_frame == 0:
        return None
    num_frames = data_chunk.size / bytes_per_frame
    return num_frames / fmt.sample_rate


def read_acid(chunks: list[RiffChunk]) -> AcidData | None:
    acid = get_chunk(chunks, "acid")
    if acid is None or len(acid.data) < _ACID_STRUCT.size:
        return None
    type_of_file, root_note, _reserved1, _reserved2, num_beats, meter_denom, meter_numer, tempo = (
        _ACID_STRUCT.unpack_from(acid.data, 0)
    )
    return AcidData(
        is_one_shot=bool(type_of_file & _ACID_ONE_SHOT_FLAG),
        root_note_set=bool(type_of_file & _ACID_ROOT_SET_FLAG),
        root_note_midi=root_note,
        num_beats=num_beats,
        meter_numerator=meter_numer,
        meter_denominator=meter_denom,
        tempo=tempo,
    )


def read_bext_description(chunks: list[RiffChunk]) -> str | None:
    """Read-only: the free-text 'description' field of a BEXT chunk, if present."""
    bext = get_chunk(chunks, "bext")
    if bext is None or len(bext.data) < 256:
        return None
    raw = bext.data[0:256]
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return text or None


def read_ixml_raw(chunks: list[RiffChunk]) -> str | None:
    """Read-only: raw iXML chunk contents as text (it's an embedded XML document)."""
    ixml = get_chunk(chunks, "iXML")
    if ixml is None:
        return None
    return ixml.data.rstrip(b"\x00").decode("utf-8", errors="replace") or None


def default_acid(tempo: float) -> AcidData:
    """A fresh ACID chunk carrying only a tempo -- used when a file has none yet."""
    return AcidData(
        is_one_shot=False,
        root_note_set=False,
        root_note_midi=0,
        num_beats=0,
        meter_numerator=4,
        meter_denominator=4,
        tempo=tempo,
    )


def _encode_acid(acid: AcidData) -> bytes:
    type_of_file = _ACID_STRETCH_FLAG
    if acid.is_one_shot:
        type_of_file |= _ACID_ONE_SHOT_FLAG
    if acid.root_note_set:
        type_of_file |= _ACID_ROOT_SET_FLAG
    return _ACID_STRUCT.pack(
        type_of_file,
        acid.root_note_midi,
        0,
        0.0,
        acid.num_beats,
        acid.meter_denominator,
        acid.meter_numerator,
        acid.tempo,
    )


def write_acid(path: Path, acid: AcidData) -> None:
    """Write (adding or replacing) the 'acid' chunk, preserving every other chunk."""
    chunks = read_chunks(path)
    new_chunk_data = _encode_acid(acid)

    existing = get_chunk(chunks, "acid")
    if existing is not None:
        chunks = [
            replace(c, data=new_chunk_data, size=len(new_chunk_data)) if c.chunk_id == "acid" else c
            for c in chunks
        ]
    else:
        chunks = [*chunks, RiffChunk("acid", offset=-1, size=len(new_chunk_data), data=new_chunk_data)]

    _write_wav(path, chunks)


def merge_tempo(path: Path, tempo: float) -> None:
    """Set tempo on the file's ACID chunk, preserving any other existing ACID fields."""
    chunks = read_chunks(path)
    existing = read_acid(chunks)
    acid = replace(existing, tempo=tempo) if existing is not None else default_acid(tempo)
    write_acid(path, acid)


def _write_wav(path: Path, chunks: list[RiffChunk]) -> None:
    body = bytearray()
    for chunk in chunks:
        id_bytes = chunk.chunk_id.encode("ascii")[:4].ljust(4, b" ")
        body += id_bytes
        body += struct.pack("<I", len(chunk.data))
        body += chunk.data
        if len(chunk.data) % 2:
            body += b"\x00"

    riff_size = 4 + len(body)  # 'WAVE' + all chunks
    header = b"RIFF" + struct.pack("<I", riff_size) + b"WAVE"

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp-wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(header)
            f.write(body)
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
