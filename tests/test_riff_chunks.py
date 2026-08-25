import struct
from pathlib import Path

import pytest

from sample_librarian.audio import riff_chunks as rc


def _build_minimal_wav(*, sample_rate=44100, channels=1, bits_per_sample=16, num_frames=100) -> bytes:
    """Build a minimal valid RIFF/WAVE file: fmt chunk + silent data chunk."""
    block_align = channels * (bits_per_sample // 8)
    byte_rate = sample_rate * block_align
    fmt_data = struct.pack(
        "<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits_per_sample
    )
    data_bytes = b"\x00" * (num_frames * block_align)

    body = b"fmt " + struct.pack("<I", len(fmt_data)) + fmt_data
    body += b"data" + struct.pack("<I", len(data_bytes)) + data_bytes

    riff_size = 4 + len(body)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + body


@pytest.fixture
def wav_path(tmp_path: Path) -> Path:
    p = tmp_path / "test_tone.wav"
    p.write_bytes(_build_minimal_wav())
    return p


def test_read_chunks_finds_fmt_and_data(wav_path: Path):
    chunks = rc.read_chunks(wav_path)
    ids = [c.chunk_id for c in chunks]
    assert "fmt " in ids
    assert "data" in ids


def test_read_fmt(wav_path: Path):
    chunks = rc.read_chunks(wav_path)
    fmt = rc.read_fmt(chunks)
    assert fmt is not None
    assert fmt.channels == 1
    assert fmt.sample_rate == 44100
    assert fmt.bits_per_sample == 16


def test_read_duration_seconds(wav_path: Path):
    chunks = rc.read_chunks(wav_path)
    duration = rc.read_duration_seconds(chunks)
    assert duration == pytest.approx(100 / 44100)


def test_read_acid_absent_on_fresh_file(wav_path: Path):
    chunks = rc.read_chunks(wav_path)
    assert rc.read_acid(chunks) is None


def test_write_and_read_acid_round_trip(wav_path: Path):
    acid = rc.AcidData(
        is_one_shot=False,
        root_note_set=True,
        root_note_midi=61,  # C#
        num_beats=8,
        meter_numerator=4,
        meter_denominator=4,
        tempo=123.45,
    )
    rc.write_acid(wav_path, acid)

    chunks = rc.read_chunks(wav_path)
    read_back = rc.read_acid(chunks)
    assert read_back is not None
    assert read_back.tempo == pytest.approx(123.45, abs=0.01)
    assert read_back.root_note_midi == 61
    assert read_back.root_note_set is True
    assert read_back.root_pitch_class == "C#"
    assert read_back.num_beats == 8

    # fmt/data must survive untouched
    fmt = rc.read_fmt(chunks)
    assert fmt.sample_rate == 44100
    assert rc.read_duration_seconds(chunks) == pytest.approx(100 / 44100)


def test_merge_tempo_preserves_other_acid_fields(wav_path: Path):
    original = rc.AcidData(
        is_one_shot=True,
        root_note_set=True,
        root_note_midi=60,
        num_beats=4,
        meter_numerator=3,
        meter_denominator=4,
        tempo=90.0,
    )
    rc.write_acid(wav_path, original)

    rc.merge_tempo(wav_path, 128.0)

    chunks = rc.read_chunks(wav_path)
    updated = rc.read_acid(chunks)
    assert updated.tempo == pytest.approx(128.0)
    assert updated.root_note_midi == 60
    assert updated.num_beats == 4
    assert updated.meter_numerator == 3
    assert updated.is_one_shot is True


def test_merge_tempo_creates_chunk_when_absent(wav_path: Path):
    rc.merge_tempo(wav_path, 140.0)
    chunks = rc.read_chunks(wav_path)
    acid = rc.read_acid(chunks)
    assert acid is not None
    assert acid.tempo == pytest.approx(140.0)


def test_write_acid_is_atomic_no_tmp_files_left_behind(wav_path: Path):
    rc.merge_tempo(wav_path, 100.0)
    leftovers = list(wav_path.parent.glob("*.tmp-wav"))
    assert leftovers == []
