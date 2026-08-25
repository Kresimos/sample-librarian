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
from sample_librarian.db.repository import SampleRecord
from sample_librarian.organize.manifest import ManifestWriter, manifest_path_for_run
from sample_librarian.pipeline.per_file_pipeline import PlannedAction, execute_action, plan_file
from sample_librarian.scanner.walker import iter_audio_files


def _seed_existing_unsorted_stems(unsorted_dir: Path) -> set[str]:
    """Collision detection must account for files already sitting in
    unsorted/ from a previous run, not just duplicates within this run --
    otherwise a repeated inbox_rescan could silently overwrite/collide with
    something the first sweep already put there.
    """
    if not unsorted_dir.exists():
        return set()
    return {p.stem for p in unsorted_dir.iterdir() if p.is_file() or p.is_symlink()}


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
    existing_unsorted_stems = _seed_existing_unsorted_stems(settings.unsorted_dir)

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


def run_apply_sweep(
    settings: Settings,
    taxonomy_rules: list[TypeRule],
    conn: sqlite3.Connection,
    *,
    run_type: str = "initial_sweep",
    scan_roots_override: tuple[Path, ...] | None = None,
    leave_stub_on_move: bool = True,
) -> SweepReport:
    """Real run: actually moves/symlinks files and writes tempo metadata back,
    recording every action to a manifest and the samples table as it goes.

    Only ever call this after a dry run has been reviewed -- see the project
    plan's mandatory gate before any real --apply run. `run_type`/
    `scan_roots_override` let inbox_rescan reuse this exact same logic scoped
    to just settings.inbox_dir instead of the full scan_roots list.
    """
    scan_roots = scan_roots_override if scan_roots_override is not None else settings.scan_roots
    # exclude_root guards a general disk sweep against re-ingesting the
    # library's own content; inbox/vendor rescans deliberately scan *inside*
    # library_root, so that guard would wrongly exclude everything there.
    exclude_root = settings.library_root if scan_roots_override is None else None
    scan_run_id = repository.start_scan_run(conn, run_type, dry_run=False)
    manifest_path = manifest_path_for_run(settings.logs_dir, scan_run_id, run_type)
    report = SweepReport(scan_run_id=scan_run_id)
    existing_unsorted_stems = _seed_existing_unsorted_stems(settings.unsorted_dir)
    files_moved = 0
    files_symlinked = 0

    with ManifestWriter(manifest_path) as manifest:
        for path in iter_audio_files(scan_roots, settings.audio_extensions, exclude_root=exclude_root):
            try:
                action = plan_file(
                    path, settings, taxonomy_rules, existing_unsorted_stems=existing_unsorted_stems
                )
            except Exception as exc:  # noqa: BLE001 -- one bad file shouldn't abort the sweep
                report.errors.append((path, str(exc)))
                continue

            outcome = execute_action(action, manifest, leave_stub_on_move=leave_stub_on_move)
            if not outcome.success:
                report.errors.append((path, outcome.error or "unknown error"))
                continue

            report.actions.append(action)
            if action.bucket == "vendor":
                files_symlinked += 1
            else:
                files_moved += 1

            record = SampleRecord(
                current_path=str(action.target_path),
                bucket=action.bucket,
                source_path=str(action.source_path),
                is_symlink_at_current=(action.bucket == "vendor"),
                stub_left_at_source=(action.bucket == "orphan" and leave_stub_on_move),
                vendor_name=action.vendor_name,
                original_filename=path.name,
                cleaned_filename=action.cleaned_filename,
                file_ext=path.suffix.lower(),
                file_size_bytes=action.file_size_bytes,
                classification_method="filename_heuristic",
                bpm=action.bpm,
                bpm_source=action.bpm_source,
                musical_key=action.musical_key,
                key_source=action.key_source,
                acid_chunk_present=action.acid_chunk_present or outcome.wrote_tempo_metadata,
                duration_seconds=action.duration_seconds,
                sample_rate=action.sample_rate,
                channels=action.channels,
                tags=action.tags,
            )
            repository.upsert_sample(conn, record, scan_run_id)

    repository.finish_scan_run(
        conn,
        scan_run_id,
        files_scanned=report.files_scanned,
        files_moved=files_moved,
        files_symlinked=files_symlinked,
        errors_count=len(report.errors),
        manifest_path=str(manifest_path),
    )
    return report
