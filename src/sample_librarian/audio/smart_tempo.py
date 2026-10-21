"""Logic Pro's "Smart Tempo" per-file analysis result: a zlib-compressed JSON
blob embedded in a 'ResU' chunk. This -- not the generic 'acid' chunk (Sony/
Acid convention, see riff_chunks.py) -- is what actually drives the "File
Tempo" field Logic Pro shows after a plain drag from Finder or this app.

Confirmed empirically (2026-08-25, with Johnny) by: exporting a region from
Logic as AIFF with "Include Tempo Information" checked (which *did* show
correct File Tempo on a plain Finder drag from a location Logic hadn't
indexed), diffing its chunks against the same audio without that export
option, isolating the difference to a 'ResU' chunk, decompressing it to find
plain JSON, confirming Logic reads the value from it (a stripped copy with
'ResU' removed no longer showed a tempo), and finally confirming the same
compressed JSON also works when embedded in a plain WAV file (this format
appears to be a historical AIFF/Mac-resource-fork convention, but Logic's WAV
parser reads it too).

This is unrelated to (and doesn't replace) the ACID chunk: Logic's drag-and-
drop tempo recognition never reads ACID at all, and un-embedding this doesn't
touch the ACID chunk either. AIFF isn't supported here yet -- writing to it
needs its own chunk reader (see riff_chunks.py's WAV-only scope); this only
handles WAV, which is the vast majority of this library.

Every non-tempo/beat/duration field below is a hardcoded constant matching
what a real Logic export contains for a file with a simply *known* tempo
(not one Logic itself auto-detected) -- verified against a real sample.
"""

from __future__ import annotations

import json
import math
import time
import zlib
from pathlib import Path

from sample_librarian.audio import riff_chunks

_CHUNK_ID = "ResU"


def _leaf(*, duration_seconds: float, tempo: float, saved_time: int) -> dict:
    interval = 60.0 / tempo
    num_beats = max(0, math.floor(duration_seconds / interval + 1e-9))
    beats = [{"t": round(i * interval, 6), "conf": -1, "onset": 1} for i in range(num_beats)]

    return {
        "version": 2,
        "offset": 0,
        "duration": duration_seconds,
        "db_time": 0,
        "relevant_start_time": 0,
        "relevant_end_time": 1_000_000_000_000,
        "mtr_end": 1_000_000_000_000,
        "creationTime": 0,
        "modificationTime": 0,
        "savedTime": saved_time,
        "MusicDetectionWasPerformed": 0,
        "ArrangeTapsWereUsedInAnalysis": 0,
        "ResultWasCreatedFromLogicTempoMap": 0,
        "ResultWasCreatedFromLogicArrange": 0,
        "UserEdited": 0,
        "IsDirty": 0,
        "LoopMode": 0,
        "snapToTransients": 0,
        "beats": beats,
        "Tempo": [{"t": 0, "conf": -1, "tempo": tempo}],
        "time_signatures": [{"t": 0, "conf": -1, "signature": "4/4"}],
    }


def build_payload_json(*, duration_seconds: float, tempo: float) -> bytes:
    """The uncompressed JSON payload, matching Logic's own nested shape (an
    'initial' analysis snapshot plus a 'rec_ctx' inside it -- both identical
    to the top level here, since we're providing one single known-tempo
    result, not modeling Logic's own edit history).
    """
    original = _leaf(duration_seconds=duration_seconds, tempo=tempo, saved_time=0)
    current = _leaf(duration_seconds=duration_seconds, tempo=tempo, saved_time=int(time.time()))
    payload = {**current, "initial": {**original, "rec_ctx": original}, "rec_ctx": original}
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def build_chunk_data(*, duration_seconds: float, tempo: float) -> bytes:
    """The compressed bytes actually stored in the chunk."""
    return zlib.compress(build_payload_json(duration_seconds=duration_seconds, tempo=tempo))


def write_smart_tempo(path: Path, *, duration_seconds: float, tempo: float) -> None:
    """Write (adding or replacing) the ResU Smart Tempo chunk in a WAV file."""
    riff_chunks.write_chunk(path, _CHUNK_ID, build_chunk_data(duration_seconds=duration_seconds, tempo=tempo))


def remove_smart_tempo(path: Path) -> None:
    riff_chunks.remove_chunk(path, _CHUNK_ID)


def read_raw_chunk_data(path: Path) -> bytes | None:
    """The raw (still-compressed) chunk bytes, if present -- used by the
    pipeline's undo bookkeeping to restore an existing chunk exactly rather
    than just deleting whatever's there.
    """
    chunks = riff_chunks.read_chunks(path)
    chunk = riff_chunks.get_chunk(chunks, _CHUNK_ID)
    return chunk.data if chunk is not None else None


def read_smart_tempo(path: Path) -> dict | None:
    """Read back and decompress the ResU chunk's JSON, if present -- mainly
    for tests/debugging, not used by the pipeline itself.
    """
    raw = read_raw_chunk_data(path)
    if raw is None:
        return None
    return json.loads(zlib.decompress(raw))
