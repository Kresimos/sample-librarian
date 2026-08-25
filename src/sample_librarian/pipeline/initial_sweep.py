"""Orchestrates a full sweep of settings.scan_roots.

Dry-run mode (the only mode implemented so far) never touches the `samples`
table -- that table represents what's actually, really in the library right
now, and in dry-run nothing has moved yet, so populating it would be
misleading. It only records a scan_runs row (dry_run=1) for provenance, and
returns the full list of planned actions for the caller to report on. Real
`--apply` execution (moving files, writing samples rows) is Milestone 4, not
built yet -- see the project plan.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from sample_librarian.classify.classifier import TypeRule
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.per_file_pipeline import PlannedAction, plan_file
from sample_librarian.scanner.walker import iter_audio_files


@dataclass
class SweepReport:
    scan_run_id: int
    actions: list[PlannedAction] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def files_scanned(self) -> int:
        return len(self.actions) + len(self.errors)

    @property
    def vendor_count(self) -> int:
        return sum(1 for a in self.actions if a.bucket == "vendor")

    @property
    def orphan_count(self) -> int:
        return sum(1 for a in self.actions if a.bucket == "orphan")


def run_dry_run_sweep(
    settings: Settings,
    taxonomy_rules: list[TypeRule],
    conn: sqlite3.Connection,
) -> SweepReport:
    scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=True)
    report = SweepReport(scan_run_id=scan_run_id)
    existing_unsorted_stems: set[str] = set()

    for path in iter_audio_files(
        settings.scan_roots, settings.audio_extensions, exclude_root=settings.library_root
    ):
        try:
            action = plan_file(
                path, settings, taxonomy_rules, existing_unsorted_stems=existing_unsorted_stems
            )
        except Exception as exc:  # noqa: BLE001 -- one bad file shouldn't abort the sweep
            report.errors.append((path, str(exc)))
            continue
        report.actions.append(action)

    repository.finish_scan_run(
        conn,
        scan_run_id,
        files_scanned=report.files_scanned,
        files_moved=0,
        files_symlinked=0,
        errors_count=len(report.errors),
        manifest_path=None,
    )
    return report
