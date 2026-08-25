"""Replay a scan_run's manifest in reverse to undo a real --apply run.

Order matters: entries for a given file are undone in reverse of how they
were recorded, so a write_tempo_metadata entry (recorded after its file's
move) gets undone on the file at its post-move location *before* the move
itself gets reversed and the file goes back to where it came from.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from sample_librarian.organize.manifest import ManifestEntry, read_manifest
from sample_librarian.pipeline.per_file_pipeline import undo_tempo_metadata


class UndoError(Exception):
    pass


@dataclass
class UndoReport:
    scan_run_id: int
    reversed_count: int = 0
    skipped: list[tuple[ManifestEntry, str]] = field(default_factory=list)


def undo_scan_run(conn: sqlite3.Connection, scan_run_id: int) -> UndoReport:
    row = conn.execute("SELECT manifest_path FROM scan_runs WHERE id = ?", (scan_run_id,)).fetchone()
    if row is None:
        raise UndoError(f"no scan_run with id {scan_run_id}")
    manifest_path = row["manifest_path"]
    if not manifest_path:
        raise UndoError(f"scan_run {scan_run_id} has no manifest (was it a dry run?)")

    entries = [e for e in read_manifest(Path(manifest_path)) if e.success]
    report = UndoReport(scan_run_id=scan_run_id)
    reversed_paths: set[str] = set()

    for entry in reversed(entries):
        try:
            _undo_entry(entry)
            report.reversed_count += 1
            if entry.action in ("move", "symlink"):
                reversed_paths.add(entry.dest)
        except Exception as exc:  # noqa: BLE001 -- one bad entry shouldn't abort the rest
            report.skipped.append((entry, str(exc)))

    # Only drop rows whose move/symlink was actually, successfully reversed.
    # If reversing one entry failed (e.g. the target was already moved out
    # from under us), that file is still really sitting in the library, and
    # unconditionally deleting by scan_run_id alone would silently make it
    # vanish from the database while it's still physically there.
    if reversed_paths:
        placeholders = ",".join("?" for _ in reversed_paths)
        conn.execute(
            f"DELETE FROM samples WHERE scan_run_id = ? AND current_path IN ({placeholders})",
            (scan_run_id, *reversed_paths),
        )
        conn.commit()

    return report


def _undo_entry(entry: ManifestEntry) -> None:
    if entry.action == "symlink":
        dest = Path(entry.dest)
        if dest.is_symlink():
            dest.unlink()
        return

    if entry.action == "move":
        dest = Path(entry.dest)
        original_source = Path(entry.sample_source_path)
        had_stub = original_source.is_symlink()
        if had_stub:
            # Must remove the stub before moving dest back: it currently
            # symlinks *at* dest, so leaving it in place would make src and
            # dst the same underlying file as far as shutil.move/copyfile is
            # concerned (SameFileError on the cross-volume copy fallback).
            original_source.unlink()
        if dest.exists():
            original_source.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(dest), str(original_source))
            except Exception:
                # Best-effort: don't leave the original location completely
                # empty (no stub, no file) just because the restore failed --
                # put the stub back so the file is still reachable from
                # there, then let the failure propagate and get reported.
                if had_stub and not original_source.exists():
                    original_source.symlink_to(dest)
                raise
        return

    if entry.action == "write_tempo_metadata":
        target = Path(entry.dest)
        if target.exists() and entry.previous_state is not None:
            undo_tempo_metadata(target, entry.previous_state)
        return

    raise UndoError(f"unknown manifest action: {entry.action}")
