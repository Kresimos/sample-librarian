import struct
from pathlib import Path

import pytest

from sample_librarian.audio import metadata_extractor, riff_chunks

from .test_aiff_caf_chunks import build_aiff, build_caf

# A minimal but real AIFF header (FORM/AIFF), enough for ffprobe and our
# sniffer to recognize -- doesn't need real audio data for this test.
_MINIMAL_AIFF_HEADER = (
    b"FORM"
    b"\x00\x00\x00\x2e"  # form chunk size
    b"AIFF"
    b"COMM"
    b"\x00\x00\x00\x12"  # COMM chunk size (18 bytes)
    b"\x00\x01"  # num channels = 1
    b"\x00\x00\x00\x01"  # num sample frames = 1
    b"\x00\x10"  # bits per sample = 16
    b"\x40\x0e\xac\x44\x00\x00\x00\x00\x00\x00"  # sample rate, 80-bit float for 44100
    b"SSND"
    b"\x00\x00\x00\x08"  # SSND chunk size
    b"\x00\x00\x00\x00\x00\x00"  # offset(4) + blocksize(0)... + 2 bytes sample data
)


def test_sniffs_real_aiff_content_despite_m4a_extension(tmp_path: Path):
    """Regression test for a real file found in the wild: a Logic Pro export
    that's genuinely AIFF content sitting on disk with a .m4a extension.
    Extraction must not blindly trust the extension and fail.
    """
    misnamed = tmp_path / "Dance_Funky_3-44k.m4a"
    misnamed.write_bytes(_MINIMAL_AIFF_HEADER)

    # must not raise UnsupportedFormatError / mutagen MP4 parse error
    result = metadata_extractor.extract(misnamed)
    assert result is not None


def test_sniff_format_prefers_content_over_extension(tmp_path: Path):
    aiff_as_wav = tmp_path / "actually_aiff.wav"
    aiff_as_wav.write_bytes(_MINIMAL_AIFF_HEADER)
    assert metadata_extractor._sniff_format(aiff_as_wav) == "aiff"


def test_sniff_format_inconclusive_for_garbage(tmp_path: Path):
    garbage = tmp_path / "not_audio.wav"
    garbage.write_bytes(b"not a real audio file header")
    assert metadata_extractor._sniff_format(garbage) is None


def test_unsupported_extension_with_no_recognizable_content_raises(tmp_path: Path):
    unknown = tmp_path / "mystery.xyz"
    unknown.write_bytes(b"nothing recognizable here")
    with pytest.raises(metadata_extractor.UnsupportedFormatError):
        metadata_extractor.extract(unknown)


def _wav_with_acid_beats(path: Path, *, num_beats: int, tempo: float, num_frames: int) -> Path:
    from .helpers import build_minimal_wav

    path.write_bytes(build_minimal_wav(num_frames=num_frames, sample_rate=44100, channels=1))
    riff_chunks.write_acid(
        path,
        riff_chunks.AcidData(
            is_one_shot=True, root_note_set=False, root_note_midi=0,
            num_beats=num_beats, meter_numerator=4, meter_denominator=4, tempo=tempo,
        ),
    )
    return path


def test_wav_acid_beatgrid_fills_tempo_when_tempo_field_is_zero(tmp_path: Path):
    # The "Sample 02 (Paul Fathy - Funky Baby Love)" case: ACID chunk present,
    # 29 beats, tempo field left at 0, ~14.5s long.
    p = _wav_with_acid_beats(
        tmp_path / "Sample 02 (Paul Fathy - Funky Baby Love).wav",
        num_beats=29, tempo=0.0, num_frames=int(44100 * 14.542),
    )
    meta = metadata_extractor.extract(p)
    assert meta.bpm == 120.0
    assert meta.bpm_source == "embedded_beatgrid"


def test_wav_acid_real_tempo_still_wins_over_beatgrid(tmp_path: Path):
    p = _wav_with_acid_beats(
        tmp_path / "loop.wav", num_beats=29, tempo=124.0, num_frames=int(44100 * 14.0)
    )
    meta = metadata_extractor.extract(p)
    assert meta.bpm == 124.0
    assert meta.bpm_source == "embedded_acid"


def test_wav_acid_beatgrid_skipped_for_percussion_one_shot_name(tmp_path: Path):
    # "Danny Brown - The Cave 808.wav": 8 beats, 3.4s -- an 808 hit, not a loop.
    p = _wav_with_acid_beats(
        tmp_path / "Danny Brown - The Cave 808.wav",
        num_beats=8, tempo=0.0, num_frames=int(44100 * 3.4),
    )
    meta = metadata_extractor.extract(p)
    assert meta.bpm is None


def test_wav_acid_beatgrid_skipped_for_low_beat_count(tmp_path: Path):
    p = _wav_with_acid_beats(
        tmp_path / "Snare Roll.wav", num_beats=4, tempo=0.0, num_frames=int(44100 * 2.0)
    )
    meta = metadata_extractor.extract(p)
    assert meta.bpm is None


def test_caf_extract_end_to_end(tmp_path: Path):
    p = tmp_path / "Bumping Disco Guitar.caf"
    p.write_bytes(build_caf(
        valid_frames=176400,
        descriptor={"beat count": 8, "key signature": "E", "key type": "minor"},
    ))
    meta = metadata_extractor.extract(p)
    assert meta.bpm == 120.0
    assert meta.bpm_source == "embedded_beatgrid"
    assert meta.musical_key == "Emin"
    assert meta.key_source == "embedded_beatgrid"


def test_aiff_extract_reads_tempo_marker(tmp_path: Path):
    p = tmp_path / "Breaks Dub Plate Beat 01.aif"
    p.write_bytes(build_aiff(
        num_frames=int(44100 * 5.5),
        mark_text=b"\x00\x01\x00\x01\x00\x00\x00\x00\x0cTempo: 174.0\x00",
    ))
    meta = metadata_extractor.extract(p)
    assert meta.bpm == 174.0
    assert meta.bpm_source == "embedded_beatgrid"
