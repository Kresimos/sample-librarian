"""Append-only JSONL action log, written as (or just before) each real
filesystem action happens, so `undo` can always replay a scan_run in reverse
even if a run is interrupted partway through.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class ManifestEntry:
    action: str  # 'move' | 'symlink' | 'write_tempo_metadata'
    source: str
    dest: str
    sample_source_path: str  # original discovered path, for undo bookkeeping even after a move
    timestamp: str
    success: bool
    error: str | None = None
    # write_tempo_metadata only: what was there before, so undo can restore it
    # exactly rather than just deleting whatever tempo value happens to be
    # there now. {"chunk_existed_before": bool, "previous_tempo": float|None}.
    previous_state: dict | None = None


def manifest_path_for_run(logs_dir: Path, scan_run_id: int, run_type: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return logs_dir / "manifests" / f"{ts}-{run_type}-{scan_run_id}.jsonl"


class ManifestWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")

    def record(self, entry: ManifestEntry) -> None:
        self._fh.write(json.dumps(asdict(entry)) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "ManifestWriter":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def read_manifest(path: Path) -> Iterator[ManifestEntry]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield ManifestEntry(**json.loads(line))
