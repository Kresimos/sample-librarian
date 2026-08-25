"""Re-symlink vendor_roots into the library, picking up anything newly
installed since the last sweep. Manual-only, never triggered automatically --
a plugin installer mid-write is exactly the kind of thing this tool must not
interfere with unprompted. Files under vendor_roots always classify as
'vendor' bucket, so this is never anything but symlinking; nothing here ever
moves or renames a file.
"""

from __future__ import annotations

import sqlite3

from sample_librarian.classify.classifier import TypeRule
from sample_librarian.config import Settings
from sample_librarian.pipeline.initial_sweep import SweepReport, run_apply_sweep


def run_vendor_rescan(
    settings: Settings,
    taxonomy_rules: list[TypeRule],
    conn: sqlite3.Connection,
) -> SweepReport:
    return run_apply_sweep(
        settings,
        taxonomy_rules,
        conn,
        run_type="vendor_rescan",
        scan_roots_override=settings.vendor_roots,
    )
