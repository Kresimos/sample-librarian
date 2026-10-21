"""One-time (re-runnable, idempotent) backfill that re-extracts tempo/key for
every already-indexed sample that currently has none, using the improved
metadata extractor:

* AIFF Apple Loops -- tempo (and sometimes key) from the MARK-chunk
  "Tempo: 140.0" marker; previously AIFF had no chunk parser at all.
* CAF Apple Loops -- tempo from beat count / duration, key from the `uuid`
  descriptor; previously CAF wasn't read at all.
* WAV -- an ACID chunk that carries a real beat count but left its tempo
  field at 0 (common in acidized loop packs). tempo = beats / (length / 60).

DB-only: never touches a file. It re-reads what's already on disk at
current_path (following the vendor symlink) and writes the resulting
bpm/bpm_source/musical_key/key_source back only where the column was NULL --
an existing value is always left alone. Baking Logic's Smart Tempo chunk into
the newly-known-tempo WAVs is left to `samplelib fix-tempo`, which already
does exactly that for every WAV with a known tempo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sample_librarian.audio import metadata_extractor
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import now_iso
from sample_librarian.organize.manifest import ManifestEntry, ManifestWriter, manifest_path_for_run


@dataclass(frozen=True)
class BpmFillAction:
    sample_id: int
    path: Path
    original_filename: str
    new_bpm: float | None
    new_bpm_source: str | None
    new_key: str | None
    new_key_source: str | None


def plan_bpm_fills(conn) -> list[BpmFillAction]:
    """Pure planning pass -- no DB or filesystem writes. Only rows that would
    actually gain a bpm or a key are returned.
    """
    rows = conn.execute(
        """
        SELECT id, current_path, original_filename, bpm, bpm_source, musical_key, key_source
        FROM samples
        WHERE status = 'active' AND (bpm IS NULL OR musical_key IS NULL)
        """
    ).fetchall()

    actions: list[BpmFillAction] = []
    for row in rows:
        path = Path(row["current_path"])
        if not path.exists():
            continue
        try:
            meta = metadata_extractor.extract(path)
        except Exception:  # noqa: BLE001 -- one unreadable file shouldn't abort the plan
            continue

        new_bpm = meta.bpm if row["bpm"] is None and meta.bpm is not None else None
        new_bpm_source = meta.bpm_source if new_bpm is not None else None
        new_key = meta.musical_key if row["musical_key"] is None and meta.musical_key is not None else None
        new_key_source = meta.key_source if new_key is not None else None

        if new_bpm is None and new_key is None:
            continue

        actions.append(
            BpmFillAction(
                sample_id=row["id"],
                path=path,
                original_filename=row["original_filename"],
                new_bpm=new_bpm,
                new_bpm_source=new_bpm_source,
                new_key=new_key,
                new_key_source=new_key_source,
            )
        )
    return actions


@dataclass
class BpmRemediationReport:
    scan_run_id: int
    bpm_filled: int = 0
    key_filled: int = 0
    errors: list[tuple[str, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def apply_bpm_fills(conn, settings: Settings, actions: list[BpmFillAction]) -> BpmRemediationReport:
    scan_run_id = repository.start_scan_run(conn, "bpm_remediation", dry_run=False)
    manifest_path = manifest_path_for_run(settings.logs_dir, scan_run_id, "bpm_remediation")
    report = BpmRemediationReport(scan_run_id=scan_run_id)

    with ManifestWriter(manifest_path) as manifest:
        for action in actions:
            sets: list[str] = []
            params: list = []
            if action.new_bpm is not None:
                sets += ["bpm = ?", "bpm_source = ?"]
                params += [action.new_bpm, action.new_bpm_source]
            if action.new_key is not None:
                sets += ["musical_key = ?", "key_source = ?"]
                params += [action.new_key, action.new_key_source]
            params.append(action.sample_id)

            try:
                conn.execute(f"UPDATE samples SET {', '.join(sets)} WHERE id = ?", params)
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                manifest.record(
                    ManifestEntry(
                        action="db_metadata_update", source=str(action.path), dest=str(action.path),
                        sample_source_path=str(action.path), timestamp=now_iso(), success=False, error=str(exc),
                    )
                )
                report.errors.append((str(action.path), str(exc)))
                continue

            manifest.record(
                ManifestEntry(
                    action="db_metadata_update", source=str(action.path), dest=str(action.path),
                    sample_source_path=str(action.path), timestamp=now_iso(), success=True,
                    previous_state={
                        "db_bpm_before": None,
                        "db_bpm_source_before": None,
                        "db_key_before": None,
                        "db_key_source_before": None,
                        "wrote_bpm": action.new_bpm is not None,
                        "wrote_key": action.new_key is not None,
                    },
                )
            )
            if action.new_bpm is not None:
                report.bpm_filled += 1
            if action.new_key is not None:
                report.key_filled += 1

    repository.finish_scan_run(
        conn, scan_run_id,
        files_scanned=len(actions), files_moved=0, files_symlinked=0,
        errors_count=len(report.errors), manifest_path=str(manifest_path),
    )
    return report
