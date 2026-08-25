from pathlib import Path

import pytest

from sample_librarian.audio import metadata_extractor

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
