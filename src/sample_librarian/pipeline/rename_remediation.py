"""One-time (re-runnable, idempotent) fix for orphan-bucket files that were
already moved into unsorted/ before cleaner.py learned to unmangle Windows-
style backslash paths baked into a single flat filename (see clean_filename).

Only ever touches cleaned_filename/current_path -- classification tags are
left untouched. They don't need recomputing: classify() reads the raw source
filename (which already contained the same backslash-joined folder-name
context, e.g. "...Synth Loop Collection\\Chord Loops\\...") independently of
the cleaned display name, so category tags like `synth`/`chord`/`drum` were
already captured correctly the first time around.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import now_iso
from sample_librarian.naming.cleaner import clean_filename, has_mangled_path_separator, make_unique
from sample_librarian.organize.manifest import ManifestEntry, ManifestWriter, manifest_path_for_run


@dataclass(frozen=True)
class RenamePlan:
    sample_id: int
    old_path: Path
    new_path: Path


def plan_renames(conn) -> list[RenamePlan]:
    """Pure planning pass, no filesystem/DB writes -- safe to call repeatedly
    to preview what would change.
    """
    rows = conn.execute(
        "SELECT id, current_path FROM samples WHERE bucket = 'orphan' AND status = 'active'"
    ).fetchall()

    # Lowercased -- see make_unique's docstring for why (macOS's default
    # filesystem is case-insensitive, so two differently-cased stems can
    # still collide on disk even though they're different Python strings).
    existing_stems = {Path(r["current_path"]).stem.lower() for r in rows}

    plans: list[RenamePlan] = []
    for row in rows:
        old_path = Path(row["current_path"])
        if not has_mangled_path_separator(old_path.stem):
            continue

        existing_stems.discard(old_path.stem.lower())
        new_stem = clean_filename(old_path.stem)
        new_stem = make_unique(new_stem, existing_stems)
        existing_stems.add(new_stem.lower())

        if new_stem == old_path.stem:
            continue  # shouldn't happen given has_mangled_path_separator, but stay a no-op if it does

        new_path = old_path.with_name(f"{new_stem}{old_path.suffix}")
        plans.append(RenamePlan(sample_id=row["id"], old_path=old_path, new_path=new_path))

    return plans


@dataclass
class RenameReport:
    scan_run_id: int
    renamed_count: int = 0
    errors: list[tuple[str, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def apply_renames(conn, settings: Settings, plans: list[RenamePlan]) -> RenameReport:
    """Actually rename each planned file on disk and update its DB row,
    logging every step to a manifest so `samplelib undo <scan_run_id>` can
    reverse it like any other real action this tool takes.
    """
    scan_run_id = repository.start_scan_run(conn, "rename_remediation", dry_run=False)
    manifest_path = manifest_path_for_run(settings.logs_dir, scan_run_id, "rename_remediation")
    report = RenameReport(scan_run_id=scan_run_id)

    with ManifestWriter(manifest_path) as manifest:
        for plan in plans:
            try:
                plan.old_path.rename(plan.new_path)
            except OSError as exc:
                manifest.record(
                    ManifestEntry(
                        action="rename",
                        source=str(plan.old_path),
                        dest=str(plan.new_path),
                        sample_source_path=str(plan.old_path),
                        timestamp=now_iso(),
                        success=False,
                        error=str(exc),
                    )
                )
                report.errors.append((str(plan.old_path), str(exc)))
                continue

            manifest.record(
                ManifestEntry(
                    action="rename",
                    source=str(plan.old_path),
                    dest=str(plan.new_path),
                    sample_source_path=str(plan.old_path),
                    timestamp=now_iso(),
                    success=True,
                )
            )
            conn.execute(
                "UPDATE samples SET current_path = ?, cleaned_filename = ? WHERE id = ?",
                (str(plan.new_path), plan.new_path.name, plan.sample_id),
            )
            conn.commit()
            report.renamed_count += 1

    repository.finish_scan_run(
        conn,
        scan_run_id,
        files_scanned=len(plans),
        files_moved=report.renamed_count,
        files_symlinked=0,
        errors_count=len(report.errors),
        manifest_path=str(manifest_path),
    )
    return report
