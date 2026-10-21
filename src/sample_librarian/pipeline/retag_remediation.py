"""One-time (re-runnable, idempotent) backfill that recomputes every active
sample's tags from scratch against the *current* config/taxonomy.yaml and
per_file_pipeline.py's vendor_name-to-tag mirroring.

Needed because classify() only ever runs at scan time -- a sample swept
before a taxonomy rule (or the vendor-name tag mirror) existed just never
picks it up on its own. This recomputes purely from what's already stored in
the DB (original_filename, source_path's parent folders, duration_seconds,
vendor_name), the same inputs plan_file() feeds classify() for a brand new
file, so the result is exactly what a fresh scan would produce today.

Only ever replaces sample_tags rows -- never touches files, current_path, or
any other samples column.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sample_librarian.classify.classifier import TypeRule, classify, slugify_vendor_name
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import now_iso
from sample_librarian.organize.manifest import ManifestEntry, ManifestWriter, manifest_path_for_run


@dataclass(frozen=True)
class RetagPlan:
    sample_id: int
    current_path: str
    old_tags: tuple[str, ...]
    new_tags: tuple[str, ...]


def plan_retags(conn, taxonomy_rules: list[TypeRule]) -> list[RetagPlan]:
    """Pure planning pass, no DB writes -- safe to call repeatedly to preview.
    Only samples whose recomputed tag set actually differs are included.
    """
    rows = conn.execute(
        """
        SELECT id, current_path, source_path, original_filename, vendor_name, duration_seconds, bpm
        FROM samples WHERE status = 'active'
        """
    ).fetchall()

    plans: list[RetagPlan] = []
    for row in rows:
        sample_id = row["id"]
        old_tags = tuple(repository.tags_for_sample(conn, sample_id))

        source_path = Path(row["source_path"])
        classification = classify(
            row["original_filename"],
            [p.name for p in source_path.parents],
            taxonomy_rules,
            duration_seconds=row["duration_seconds"],
            bpm=row["bpm"],
        )
        new_tags = classification.tags
        if row["vendor_name"] is not None:
            new_tags = (*new_tags, slugify_vendor_name(row["vendor_name"]))

        if set(new_tags) != set(old_tags):
            plans.append(
                RetagPlan(sample_id=sample_id, current_path=row["current_path"], old_tags=old_tags, new_tags=new_tags)
            )

    return plans


@dataclass
class RetagReport:
    scan_run_id: int
    retagged_count: int = 0
    errors: list[tuple[str, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def apply_retags(conn, settings: Settings, plans: list[RetagPlan]) -> RetagReport:
    """Replace each planned sample's tag set, logging the previous tags to the
    manifest (as `previous_state["tags_before"]`) so `samplelib undo` can
    restore them -- see undo.py's "retag" handling.
    """
    scan_run_id = repository.start_scan_run(conn, "retag_remediation", dry_run=False)
    manifest_path = manifest_path_for_run(settings.logs_dir, scan_run_id, "retag_remediation")
    report = RetagReport(scan_run_id=scan_run_id)

    with ManifestWriter(manifest_path) as manifest:
        for plan in plans:
            try:
                repository.replace_tags_for_sample(conn, plan.sample_id, plan.new_tags)
            except Exception as exc:  # noqa: BLE001 -- one bad row shouldn't abort the rest
                manifest.record(
                    ManifestEntry(
                        action="retag",
                        source=plan.current_path,
                        dest=plan.current_path,
                        sample_source_path=plan.current_path,
                        timestamp=now_iso(),
                        success=False,
                        error=str(exc),
                    )
                )
                report.errors.append((plan.current_path, str(exc)))
                continue

            manifest.record(
                ManifestEntry(
                    action="retag",
                    source=plan.current_path,
                    dest=plan.current_path,
                    sample_source_path=plan.current_path,
                    timestamp=now_iso(),
                    success=True,
                    previous_state={"tags_before": list(plan.old_tags)},
                )
            )
            report.retagged_count += 1

    repository.finish_scan_run(
        conn,
        scan_run_id,
        files_scanned=len(plans),
        files_moved=0,
        files_symlinked=0,
        errors_count=len(report.errors),
        manifest_path=str(manifest_path),
    )
    return report
