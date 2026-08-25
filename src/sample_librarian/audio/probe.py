"""ffprobe wrapper for duration/sample-rate/channels on compressed formats
(MP3/M4A/FLAC). WAV doesn't need this -- riff_chunks.py reads the fmt/data
chunks directly, no external process required.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FfprobeNotFoundError(Exception):
    pass


class ProbeError(Exception):
    pass


@dataclass(frozen=True)
class ProbeResult:
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None


def probe(path: Path) -> ProbeResult:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise FfprobeNotFoundError("ffprobe not found on PATH (brew install ffmpeg)")

    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise ProbeError(f"ffprobe failed on {path}: {exc.stderr}") from exc

    payload = json.loads(result.stdout)
    streams = payload.get("streams") or [{}]
    stream = streams[0]
    fmt = payload.get("format", {})

    sample_rate = int(stream["sample_rate"]) if "sample_rate" in stream else None
    channels = int(stream["channels"]) if "channels" in stream else None
    duration = float(fmt["duration"]) if "duration" in fmt else None

    return ProbeResult(duration_seconds=duration, sample_rate=sample_rate, channels=channels)
