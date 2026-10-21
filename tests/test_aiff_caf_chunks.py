"""Synthetic AIFF/CAF fixtures exercising audio/aiff_caf_chunks.py."""

from __future__ import annotations

import struct
from pathlib import Path

from sample_librarian.audio import aiff_caf_chunks as m


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------

def _aiff_extended(sample_rate: float) -> bytes:
    # 80-bit IEEE 754 extended, big-endian -- AIFF's sample-rate encoding.
    if sample_rate == 0:
        return b"\x00" * 10
    import math

    mant, exp = math.frexp(sample_rate)
    exp += 16382
    mant = int(mant * (1 << 64))
    return struct.pack(">HQ", exp, mant)


def build_aiff(*, sample_rate=44100, channels=2, num_frames=44100, mark_text: bytes | None = None) -> bytes:
    comm = struct.pack(">hIh", channels, num_frames, 16) + _aiff_extended(sample_rate)
    chunks = b"COMM" + struct.pack(">I", len(comm)) + comm
    if mark_text is not None:
        chunks += b"MARK" + struct.pack(">I", len(mark_text)) + mark_text
        if len(mark_text) % 2:
            chunks += b"\x00"
    ssnd = b"\x00" * 16
    chunks += b"SSND" + struct.pack(">I", len(ssnd)) + ssnd
    return b"FORM" + struct.pack(">I", 4 + len(chunks)) + b"AIFF" + chunks


def _caf_chunk(cid: bytes, body: bytes) -> bytes:
    return cid + struct.pack(">q", len(body)) + body


def build_caf(*, sample_rate=44100, channels=2, valid_frames=176400, descriptor: dict | None = None) -> bytes:
    header = b"caff" + struct.pack(">HH", 1, 0)
    desc = struct.pack(">d4sIIIII", float(sample_rate), b"lpcm", 0, 4, 1, channels, 16)
    pakt = struct.pack(">qqii", 0, valid_frames, 0, 0)
    parts = [_caf_chunk(b"desc", desc), _caf_chunk(b"pakt", pakt)]
    if descriptor:
        blob = b"\x00" * 16 + struct.pack(">I", len(descriptor))
        for k, v in descriptor.items():
            blob += k.encode() + b"\x00" + str(v).encode() + b"\x00"
        parts.append(_caf_chunk(b"uuid", blob))
    parts.append(_caf_chunk(b"data", b"\x00" * 8))
    return header + b"".join(parts)


# --------------------------------------------------------------------------
# snap_bpm / bpm_from_beats
# --------------------------------------------------------------------------

def test_snap_bpm_rounds_to_integer():
    assert m.snap_bpm(119.68) == 120.0
    assert m.snap_bpm(174.02) == 174.0
    assert m.snap_bpm(93.4) == 93.0


def test_snap_bpm_rejects_implausible():
    assert m.snap_bpm(12.0) is None
    assert m.snap_bpm(650.0) is None


def test_bpm_from_beats():
    assert m.bpm_from_beats(8, 4.0) == 120.0
    assert m.bpm_from_beats(29, 14.542) == 120.0  # the "Paul Fathy" case
    assert m.bpm_from_beats(None, 4.0) is None
    assert m.bpm_from_beats(8, None) is None


# --------------------------------------------------------------------------
# AIFF
# --------------------------------------------------------------------------

def test_aiff_tempo_marker(tmp_path: Path):
    p = tmp_path / "loop.aif"
    p.write_bytes(build_aiff(num_frames=44100 * 4, mark_text=b"\x00\x01\x00\x01\x00\x00\x00\x00\x0cTempo: 140.0\x00"))
    meta = m.read_aiff_metadata(p)
    assert meta.bpm == 140.0
    assert round(meta.duration_seconds, 2) == 4.0
    assert meta.sample_rate == 44100


def test_aiff_no_marker_no_tempo(tmp_path: Path):
    p = tmp_path / "oneshot.aif"
    p.write_bytes(build_aiff(num_frames=22050))
    meta = m.read_aiff_metadata(p)
    assert meta.bpm is None


# --------------------------------------------------------------------------
# CAF
# --------------------------------------------------------------------------

def test_caf_beat_count_derives_tempo_and_key(tmp_path: Path):
    p = tmp_path / "loop.caf"
    p.write_bytes(build_caf(
        valid_frames=176400,
        descriptor={"beat count": 8, "time signature": "4/4", "key signature": "E", "key type": "minor"},
    ))
    meta = m.read_caf_metadata(p)
    assert meta.bpm == 120.0
    assert meta.musical_key == "Emin"
    assert meta.beat_count == 8


def test_caf_leading_nonprintable_on_first_key_is_stripped(tmp_path: Path):
    # The entry-count byte ends up glued to the first key in real Apple files.
    p = tmp_path / "loop.caf"
    body = b"\x00" * 16 + b"\x08beat count\x008\x00key signature\x00A\x00key type\x00both\x00"
    header = b"caff" + struct.pack(">HH", 1, 0)
    desc = struct.pack(">d4sIIIII", 44100.0, b"lpcm", 0, 4, 1, 2, 16)
    pakt = struct.pack(">qqii", 0, 176400, 0, 0)
    p.write_bytes(header + _caf_chunk(b"desc", desc) + _caf_chunk(b"pakt", pakt)
                  + _caf_chunk(b"uuid", body) + _caf_chunk(b"data", b"\x00" * 8))
    meta = m.read_caf_metadata(p)
    assert meta.beat_count == 8
    assert meta.bpm == 120.0
    assert meta.musical_key == "A"  # "both" -> bare root


def test_caf_riser_with_no_beat_count_has_no_tempo(tmp_path: Path):
    p = tmp_path / "riser.caf"
    p.write_bytes(build_caf(descriptor={"time signature": "4/4", "key signature": "C"}))
    meta = m.read_caf_metadata(p)
    assert meta.bpm is None
