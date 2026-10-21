"""Process whatever's sitting in inbox/, moving results into unsorted/ and
leaving inbox/ empty again. Reuses run_apply_sweep's exact per-file logic,
just scoped to a single small folder -- this is the whole point of the
inbox/unsorted split: keeping the library current never requires walking the
whole disk again, only this one folder.

inbox_dir can be repurposed to point at an existing dumping-ground folder
(e.g. ~/Downloads via settings.toml's inbox_dir) instead of a dedicated empty
folder under library_root -- in that case the folder can hold thousands of
unrelated files, so every run is scoped to only what changed since the last
completed inbox_rescan (repository.last_scan_run_started_at), rather than
re-walking and re-stat'ing the whole folder every time. The very first run
(no prior inbox_rescan row yet) still sees everything.

Caveat: a file that errors during a run (report.errors) stays in place with
its mtime unchanged, so a later run's cutoff will keep silently skipping it
rather than retrying -- fine for this tool's low personal file volume (an
inbox that isn't draining is easy to notice by eye), but worth knowing if
errors ever start going unnoticed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from sample_librarian.classify.classifier import TypeRule
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.initial_sweep import SweepReport, run_apply_sweep


def run_inbox_rescan(
    settings: Settings,
    taxonomy_rules: list[TypeRule],
    conn: sqlite3.Connection,
) -> SweepReport:
    last_started_at = repository.last_scan_run_started_at(conn, "inbox_rescan")
    min_mtime = datetime.fromisoformat(last_started_at).timestamp() if last_started_at else None

    return run_apply_sweep(
        settings,
        taxonomy_rules,
        conn,
        run_type="inbox_rescan",
        scan_roots_override=(settings.inbox_dir,),
        leave_stub_on_move=False,
        min_mtime=min_mtime,
    )
