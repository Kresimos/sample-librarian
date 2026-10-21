"""One-time (re-runnable, idempotent) correction pass for two related data-
quality issues found in the already-completed initial sweep, both stemming
from the since-removed bare-number BPM fallback (see filename_regex.py):

1. Some files got a filename-derived "tempo" that's actually a catalog/index
   number. Confirmed cases in this library: numbered one-shot hits (a
   one-shot has no real tempo concept at all, regardless of the number's
   value) and anything under 50 BPM (implausibly slow for real music, and
   matches a confirmed vintage-drum-library catalog-numbering pattern found
   here). These get their tempo claim cleared -- in the DB and in the file
   itself (ACID tempo reset to 0/"unknown" rather than the chunk being
   deleted outright, since it may carry other genuine fields like root note;
   Smart Tempo chunk removed if present).

2. Everything else with a genuinely known tempo + duration gets the Smart
   Tempo chunk (audio/smart_tempo.py) baked in if it doesn't already have a
   matching one, so Logic Pro's "File Tempo" field works on a plain drag --
   this applies library-wide, not just to files affected by issue 1.

Deliberately does NOT attempt audio-content tempo verification (tried,
reverted -- unreliable for melodic/non-percussive content, and investigating
the real data showed the two simple rules above already explain every
confirmed bad case in this library without it; see architecture-decisions
memory / CLAUDE.md for the full story).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from sample_librarian.audio import riff_chunks, smart_tempo
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import now_iso
from sample_librarian.organize.manifest import ManifestEntry, ManifestWriter, manifest_path_for_run
from sample_librarian.pipeline.per_file_pipeline import read_previous_tempo_state, write_tempo_metadata

_MIN_PLAUSIBLE_BPM = 50.0


@dataclass(frozen=True)
class ClearAction:
    sample_id: int
    path: Path
    previous_bpm: float
    previous_bpm_source: str
    reason: str  # "under_50bpm" | "one_shot_pattern" -- shown in dry-run output


@dataclass(frozen=True)
class BakeAction:
    sample_id: int
    path: Path
    bpm: float
    duration_seconds: float


@dataclass(frozen=True)
class TempoRemediationPlan:
    clear_actions: list[ClearAction]
    bake_actions: list[BakeAction]


def plan_tempo_fixes(conn) -> TempoRemediationPlan:
    """Pure planning pass, no filesystem/DB writes -- safe to call repeatedly."""
    rows = conn.execute(
        """
        SELECT id, current_path, original_filename, bpm, bpm_source, duration_seconds
        FROM samples
        WHERE bucket = 'orphan' AND status = 'active' AND file_ext = '.wav'
        """
    ).fetchall()

    clear_actions: list[ClearAction] = []
    bake_actions: list[BakeAction] = []

    for row in rows:
        path = Path(row["current_path"])
        bpm = row["bpm"]
        bpm_source = row["bpm_source"]
        duration = row["duration_seconds"]

        if bpm is not None and bpm_source == "filename_regex":
            name_lower = row["original_filename"].lower()
            is_one_shot_pattern = "one shot" in name_lower or "oneshot" in name_lower
            is_implausibly_slow = bpm < _MIN_PLAUSIBLE_BPM
            if is_one_shot_pattern or is_implausibly_slow:
                reason = "one_shot_pattern" if is_one_shot_pattern else "under_50bpm"
                clear_actions.append(
                    ClearAction(
                        sample_id=row["id"], path=path, previous_bpm=bpm,
                        previous_bpm_source=bpm_source, reason=reason,
                    )
                )
                continue

        if bpm is not None and duration is not None:
            existing = smart_tempo.read_smart_tempo(path)
            already_correct = existing is not None and existing.get("Tempo") == [{"t": 0, "conf": -1, "tempo": bpm}]
            if not already_correct:
                bake_actions.append(BakeAction(sample_id=row["id"], path=path, bpm=bpm, duration_seconds=duration))

    return TempoRemediationPlan(clear_actions=clear_actions, bake_actions=bake_actions)


def _clear_tempo_from_file(path: Path) -> None:
    """Reset a WAV's embedded tempo claim to "unknown" without disturbing any
    other ACID fields (root note, one-shot flag) that might be genuinely
    meaningful, and remove any (wrongly-baked) Smart Tempo chunk.
    """
    chunks = riff_chunks.read_chunks(path)
    acid = riff_chunks.read_acid(chunks)
    if acid is not None:
        riff_chunks.write_acid(path, replace(acid, tempo=0.0))
    smart_tempo.remove_smart_tempo(path)


@dataclass
class TempoRemediationReport:
    scan_run_id: int
    cleared_count: int = 0
    baked_count: int = 0
    errors: list[tuple[str, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def apply_tempo_fixes(conn, settings: Settings, plan: TempoRemediationPlan) -> TempoRemediationReport:
    scan_run_id = repository.start_scan_run(conn, "tempo_remediation", dry_run=False)
    manifest_path = manifest_path_for_run(settings.logs_dir, scan_run_id, "tempo_remediation")
    report = TempoRemediationReport(scan_run_id=scan_run_id)

    with ManifestWriter(manifest_path) as manifest:
        for action in plan.clear_actions:
            try:
                previous_state = read_previous_tempo_state(action.path)
                previous_state["db_bpm_before"] = action.previous_bpm
                previous_state["db_bpm_source_before"] = action.previous_bpm_source
                _clear_tempo_from_file(action.path)
            except OSError as exc:
                manifest.record(
                    ManifestEntry(
                        action="write_tempo_metadata", source=str(action.path), dest=str(action.path),
                        sample_source_path=str(action.path), timestamp=now_iso(), success=False, error=str(exc),
                    )
                )
                report.errors.append((str(action.path), str(exc)))
                continue

            manifest.record(
                ManifestEntry(
                    action="write_tempo_metadata", source=str(action.path), dest=str(action.path),
                    sample_source_path=str(action.path), timestamp=now_iso(), success=True,
                    previous_state=previous_state,
                )
            )
            conn.execute(
                "UPDATE samples SET bpm = NULL, bpm_source = NULL WHERE id = ?", (action.sample_id,)
            )
            conn.commit()
            report.cleared_count += 1

        for action in plan.bake_actions:
            try:
                previous_state = read_previous_tempo_state(action.path)
                write_tempo_metadata(action.path, action.bpm, action.duration_seconds)
            except OSError as exc:
                manifest.record(
                    ManifestEntry(
                        action="write_tempo_metadata", source=str(action.path), dest=str(action.path),
                        sample_source_path=str(action.path), timestamp=now_iso(), success=False, error=str(exc),
                    )
                )
                report.errors.append((str(action.path), str(exc)))
                continue

            manifest.record(
                ManifestEntry(
                    action="write_tempo_metadata", source=str(action.path), dest=str(action.path),
                    sample_source_path=str(action.path), timestamp=now_iso(), success=True,
                    previous_state=previous_state,
                )
            )
            report.baked_count += 1

    repository.finish_scan_run(
        conn, scan_run_id,
        files_scanned=len(plan.clear_actions) + len(plan.bake_actions),
        files_moved=0, files_symlinked=0,
        errors_count=len(report.errors), manifest_path=str(manifest_path),
    )
    return report
