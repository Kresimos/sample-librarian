"""Cross-validate our hand-rolled RIFF writer against an independent parser
(wavinfo). wavinfo has no ACID chunk support (confirmed: nothing in its source
references 'acid'), so this only checks that after we rewrite a file to add/
update the ACID chunk, the container is still a well-formed WAV that another
implementation can parse -- fmt/data intact, nothing corrupted.
"""

import struct
from pathlib import Path

import pytest
from wavinfo import WavInfoReader

from sample_librarian.audio import riff_chunks as rc


def _build_minimal_wav(*, sample_rate=48000, channels=2, bits_per_sample=24, num_frames=50) -> bytes:
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
    p = tmp_path / "cross_validate.wav"
    p.write_bytes(_build_minimal_wav())
    return p


def test_wavinfo_reads_file_before_our_write(wav_path: Path):
    info = WavInfoReader(str(wav_path))
    assert info.fmt.sample_rate == 48000
    assert info.fmt.channel_count == 2
    assert info.data.frame_count == 50


def test_wavinfo_still_reads_fmt_and_data_after_acid_write(wav_path: Path):
    rc.merge_tempo(wav_path, 174.0)

    info = WavInfoReader(str(wav_path))
    assert info.fmt.sample_rate == 48000
    assert info.fmt.channel_count == 2
    assert info.fmt.bits_per_sample == 24
    assert info.data.frame_count == 50
