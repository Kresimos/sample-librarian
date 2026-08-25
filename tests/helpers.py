import struct
from pathlib import Path


def build_minimal_wav(
    *, sample_rate: int = 44100, channels: int = 1, bits_per_sample: int = 16, num_frames: int = 100
) -> bytes:
    """A minimal valid RIFF/WAVE file: fmt chunk + silent data chunk, no ACID chunk."""
    block_align = channels * (bits_per_sample // 8)
    byte_rate = sample_rate * block_align
    fmt_data = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits_per_sample)
    data_bytes = b"\x00" * (num_frames * block_align)

    body = b"fmt " + struct.pack("<I", len(fmt_data)) + fmt_data
    body += b"data" + struct.pack("<I", len(data_bytes)) + data_bytes

    riff_size = 4 + len(body)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVE" + body


def write_minimal_wav(path: Path, **kwargs) -> Path:
    path.write_bytes(build_minimal_wav(**kwargs))
    return path
