"""Process whatever's sitting in inbox/, moving results into unsorted/ and
leaving inbox/ empty again. Reuses run_apply_sweep's exact per-file logic,
just scoped to a single small folder -- this is the whole point of the
inbox/unsorted split: keeping the library current never requires walking the
whole disk again, only this one folder.
"""

from __future__ import annotations

import sqlite3

from sample_librarian.classify.classifier import TypeRule
from sample_librarian.config import Settings
from sample_librarian.pipeline.initial_sweep import SweepReport, run_apply_sweep


def run_inbox_rescan(
    settings: Settings,
    taxonomy_rules: list[TypeRule],
    conn: sqlite3.Connection,
) -> SweepReport:
    return run_apply_sweep(
        settings,
        taxonomy_rules,
        conn,
        run_type="inbox_rescan",
        scan_roots_override=(settings.inbox_dir,),
        leave_stub_on_move=False,
    )
