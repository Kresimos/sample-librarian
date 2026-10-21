"""SQLite access: schema init and the read/write operations the pipeline needs.

Opened in WAL mode so a future Swift-side reader can query concurrently while
this process writes.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    schema_sql = _SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    conn.commit()
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """schema.sql's CREATE TABLE IF NOT EXISTS is a no-op against a table that
    already exists with an older shape, so real schema changes need an
    explicit, idempotent migration here too.
    """
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(samples)")}
    # sample_type/loop_type were dropped in favor of everything being a tag
    # (see classify/classifier.py) -- a db file created before that change
    # still has them.
    if "sample_type" in existing_columns:
        conn.execute("DROP INDEX IF EXISTS idx_samples_type")  # DROP COLUMN fails while an index references it
        conn.execute("ALTER TABLE samples DROP COLUMN sample_type")
    if "loop_type" in existing_columns:
        conn.execute("ALTER TABLE samples DROP COLUMN loop_type")

    # rating (Stage 2 app, -2..+2) was added after some DBs already existed.
    if "rating" not in existing_columns:
        conn.execute("ALTER TABLE samples ADD COLUMN rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN -2 AND 2)")
    # Always ensure the index exists (idempotent) -- covers both a DB that
    # just got the column added above and a fresh DB that already had it
    # from schema.sql's CREATE TABLE.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_rating ON samples(rating)")

    # Covers the Stage 2 browser's default sort (rating desc, date_added desc,
    # scoped to status='active'). Without it every search sorts its whole match
    # set through a temp b-tree, which also means the browser's paged LIMIT
    # can't stop early. Ascending serves both directions -- SQLite scans an
    # index backwards, and both columns always share the same direction (see
    # SortOption.orderByClause in the Swift app).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_samples_browse_rating "
        "ON samples(status, rating, date_added)"
    )

    # bpm_source/key_source's CHECK constraint gained 'embedded_beatgrid'
    # (tempo/key derived from an authored beat grid -- ACID num_beats, or an
    # Apple Loops .caf/.aif descriptor) after some DBs already existed. Same
    # deal as scan_runs below: SQLite can't ALTER a CHECK in place, so rebuild
    # the table when the old constraint is detected. foreign_keys must be OFF
    # for the DROP (sample_tags cascades off samples.id); ids are preserved by
    # INSERT ... SELECT *, so every sample_tags/scan_run_id reference stays valid.
    samples_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'samples'"
    ).fetchone()
    if samples_sql is not None and "embedded_beatgrid" not in samples_sql["sql"]:
        conn.commit()  # PRAGMA foreign_keys is a no-op inside a transaction
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            CREATE TABLE samples_new (
                id                        INTEGER PRIMARY KEY,
                current_path              TEXT UNIQUE NOT NULL,
                bucket                    TEXT NOT NULL CHECK (bucket IN ('vendor', 'orphan')),
                source_path               TEXT NOT NULL,
                is_symlink_at_current     INTEGER NOT NULL DEFAULT 0,
                stub_left_at_source       INTEGER NOT NULL DEFAULT 0,
                vendor_name               TEXT,
                original_filename         TEXT NOT NULL,
                cleaned_filename          TEXT NOT NULL,
                file_ext                  TEXT,
                file_size_bytes           INTEGER,
                date_added                TEXT NOT NULL,
                date_modified_on_disk     TEXT,
                classification_method     TEXT NOT NULL DEFAULT 'filename_heuristic'
                                           CHECK (classification_method IN ('filename_heuristic', 'waveform_analysis', 'manual')),
                classification_confidence REAL,
                bpm                       REAL,
                bpm_source                TEXT CHECK (bpm_source IN ('embedded_acid', 'embedded_id3', 'embedded_beatgrid', 'filename_regex', 'manual')),
                musical_key               TEXT,
                key_source                TEXT CHECK (key_source IN ('embedded_acid', 'embedded_id3', 'embedded_beatgrid', 'filename_regex', 'manual')),
                acid_chunk_present         INTEGER NOT NULL DEFAULT 0,
                acid_chunk_written_by_tool INTEGER NOT NULL DEFAULT 0,
                duration_seconds          REAL,
                sample_rate                INTEGER,
                channels                   INTEGER,
                scan_run_id                INTEGER REFERENCES scan_runs(id),
                last_seen_at                TEXT NOT NULL,
                status                       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'missing', 'error')),
                rating                       INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN -2 AND 2)
            );
            INSERT INTO samples_new SELECT * FROM samples;
            DROP TABLE samples;
            ALTER TABLE samples_new RENAME TO samples;
            CREATE INDEX IF NOT EXISTS idx_samples_bucket ON samples(bucket);
            CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);
            CREATE INDEX IF NOT EXISTS idx_samples_rating ON samples(rating);
            CREATE INDEX IF NOT EXISTS idx_samples_browse_rating ON samples(status, rating, date_added);
            """
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"samples migration left dangling foreign keys: {fk_errors}")

    # scan_runs.run_type's CHECK constraint gained 'rename_remediation',
    # 'tempo_remediation', 'retag_remediation', and 'bpm_remediation' after
    # some DBs already existed. SQLite can't ALTER a CHECK constraint in place,
    # so rebuild the table when an older constraint is detected -- checking for
    # the newest value covers every earlier constraint version too.
    scan_runs_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'scan_runs'"
    ).fetchone()
    if scan_runs_sql is not None and "bpm_remediation" not in scan_runs_sql["sql"]:
        # Dropping scan_runs outright while samples.scan_run_id references it
        # violates the FK constraint even mid-migration (verified empirically),
        # so foreign key enforcement has to be off for this rebuild -- must
        # happen outside any transaction, hence the commit() just above.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            CREATE TABLE scan_runs_new (
                id              INTEGER PRIMARY KEY,
                run_type        TEXT NOT NULL CHECK (run_type IN ('initial_sweep', 'inbox_rescan', 'vendor_rescan', 'rename_remediation', 'tempo_remediation', 'retag_remediation', 'bpm_remediation')),
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                dry_run         INTEGER NOT NULL,
                files_scanned   INTEGER NOT NULL DEFAULT 0,
                files_moved     INTEGER NOT NULL DEFAULT 0,
                files_symlinked INTEGER NOT NULL DEFAULT 0,
                errors_count    INTEGER NOT NULL DEFAULT 0,
                manifest_path   TEXT
            );
            INSERT INTO scan_runs_new SELECT * FROM scan_runs;
            DROP TABLE scan_runs;
            ALTER TABLE scan_runs_new RENAME TO scan_runs;
            """
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"scan_runs migration left dangling foreign keys: {fk_errors}")
    conn.commit()


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@dataclass(frozen=True)
class SampleRecord:
    current_path: str
    bucket: str  # 'vendor' | 'orphan'
    source_path: str
    is_symlink_at_current: bool
    stub_left_at_source: bool
    vendor_name: str | None
    original_filename: str
    cleaned_filename: str
    file_ext: str
    file_size_bytes: int
    classification_method: str
    bpm: float | None
    bpm_source: str | None
    musical_key: str | None
    key_source: str | None
    acid_chunk_present: bool
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    tags: tuple[str, ...] = ()


def start_scan_run(conn: sqlite3.Connection, run_type: str, *, dry_run: bool) -> int:
    cur = conn.execute(
        "INSERT INTO scan_runs (run_type, started_at, dry_run) VALUES (?, ?, ?)",
        (run_type, now_iso(), int(dry_run)),
    )
    conn.commit()
    return cur.lastrowid


def last_scan_run_started_at(conn: sqlite3.Connection, run_type: str) -> str | None:
    """Most recent completed (non-dry-run) started_at for a run_type, or None
    if there isn't one yet -- inbox_rescan's incremental cutoff, so the first
    ever run still sees everything and every run after that only reconsiders
    what changed since the previous one.
    """
    row = conn.execute(
        "SELECT started_at FROM scan_runs WHERE run_type = ? AND dry_run = 0 AND finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1",
        (run_type,),
    ).fetchone()
    return row[0] if row else None


def finish_scan_run(
    conn: sqlite3.Connection,
    scan_run_id: int,
    *,
    files_scanned: int,
    files_moved: int,
    files_symlinked: int,
    errors_count: int,
    manifest_path: str | None,
) -> None:
    conn.execute(
        """
        UPDATE scan_runs
        SET finished_at = ?, files_scanned = ?, files_moved = ?,
            files_symlinked = ?, errors_count = ?, manifest_path = ?
        WHERE id = ?
        """,
        (now_iso(), files_scanned, files_moved, files_symlinked, errors_count, manifest_path, scan_run_id),
    )
    conn.commit()


def upsert_sample(conn: sqlite3.Connection, record: SampleRecord, scan_run_id: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO samples (
            current_path, bucket, source_path, is_symlink_at_current, stub_left_at_source,
            vendor_name, original_filename, cleaned_filename, file_ext, file_size_bytes,
            date_added, classification_method, bpm, bpm_source,
            musical_key, key_source, acid_chunk_present, duration_seconds, sample_rate,
            channels, scan_run_id, last_seen_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ON CONFLICT(current_path) DO UPDATE SET
            bucket = excluded.bucket,
            source_path = excluded.source_path,
            is_symlink_at_current = excluded.is_symlink_at_current,
            stub_left_at_source = excluded.stub_left_at_source,
            vendor_name = excluded.vendor_name,
            cleaned_filename = excluded.cleaned_filename,
            classification_method = excluded.classification_method,
            bpm = excluded.bpm,
            bpm_source = excluded.bpm_source,
            musical_key = excluded.musical_key,
            key_source = excluded.key_source,
            acid_chunk_present = excluded.acid_chunk_present,
            duration_seconds = excluded.duration_seconds,
            sample_rate = excluded.sample_rate,
            channels = excluded.channels,
            scan_run_id = excluded.scan_run_id,
            last_seen_at = excluded.last_seen_at,
            status = 'active'
        """,
        (
            record.current_path,
            record.bucket,
            record.source_path,
            int(record.is_symlink_at_current),
            int(record.stub_left_at_source),
            record.vendor_name,
            record.original_filename,
            record.cleaned_filename,
            record.file_ext,
            record.file_size_bytes,
            now_iso(),
            record.classification_method,
            record.bpm,
            record.bpm_source,
            record.musical_key,
            record.key_source,
            int(record.acid_chunk_present),
            record.duration_seconds,
            record.sample_rate,
            record.channels,
            scan_run_id,
            now_iso(),
        ),
    )
    conn.commit()

    # cur.lastrowid is unreliable here: on the ON CONFLICT DO UPDATE path (no
    # row actually inserted), SQLite leaves it holding whatever this
    # connection's *last real insert* rowid was, not 0 and not this row's id.
    # Always look the row up explicitly instead of trying to infer insert-vs-
    # update from it.
    row = conn.execute(
        "SELECT id FROM samples WHERE current_path = ?", (record.current_path,)
    ).fetchone()
    sample_id = row["id"]

    _replace_tags(conn, sample_id, record.tags)
    return sample_id


def set_rating(conn: sqlite3.Connection, sample_id: int, rating: int) -> None:
    """Set a sample's user rating (-2..+2). Mirrors Database.setRating on the
    Swift side, which is what the Stage 2 app actually calls day to day --
    this exists for CLI debugging/scripting parity.
    """
    if not -2 <= rating <= 2:
        raise ValueError(f"rating must be between -2 and 2, got {rating}")
    conn.execute("UPDATE samples SET rating = ? WHERE id = ?", (rating, sample_id))
    conn.commit()


def replace_tags_for_sample(conn: sqlite3.Connection, sample_id: int, tags: tuple[str, ...]) -> None:
    """Public entry point for remediation tools (retag_remediation.py, and
    undo.py restoring a retag) that need to overwrite a sample's tag set
    directly, without going through upsert_sample's full sample-row upsert.
    """
    _replace_tags(conn, sample_id, tags)


def _replace_tags(conn: sqlite3.Connection, sample_id: int, tags: tuple[str, ...]) -> None:
    conn.execute("DELETE FROM sample_tags WHERE sample_id = ?", (sample_id,))
    for tag in tags:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        tag_row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO sample_tags (sample_id, tag_id) VALUES (?, ?)",
            (sample_id, tag_row["id"]),
        )
    conn.commit()


def _base_filter(
    *,
    text: str | None,
    tags: list[str] | None,
    bpm_min: float | None,
    bpm_max: float | None,
    musical_key: str | None,
) -> tuple[list[str], list]:
    """Shared WHERE-clause building for search_samples and tag_counts, so
    faceted narrowing (tag_counts) always reflects exactly the same filter
    semantics as the actual search results.
    """
    clauses = ["s.status = 'active'"]
    params: list = []

    if text:
        clauses.append(
            "(s.cleaned_filename LIKE ? OR EXISTS ("
            "SELECT 1 FROM sample_tags st JOIN tags t ON t.id = st.tag_id "
            "WHERE st.sample_id = s.id AND t.name LIKE ?))"
        )
        like = f"%{text}%"
        params.extend([like, like])

    if tags:
        # Sample must have ALL requested tags (AND, not any-of) -- count how
        # many of the requested tags it has and require that to equal the
        # number requested.
        placeholders = ",".join("?" for _ in tags)
        clauses.append(
            "(SELECT COUNT(DISTINCT t.name) FROM sample_tags st JOIN tags t ON t.id = st.tag_id "
            f"WHERE st.sample_id = s.id AND t.name IN ({placeholders})) = ?"
        )
        params.extend(tags)
        params.append(len(tags))

    if bpm_min is not None:
        clauses.append("s.bpm >= ?")
        params.append(bpm_min)
    if bpm_max is not None:
        clauses.append("s.bpm <= ?")
        params.append(bpm_max)
    if musical_key:
        clauses.append("s.musical_key = ?")
        params.append(musical_key)

    return clauses, params


def search_samples(
    conn: sqlite3.Connection,
    *,
    text: str | None = None,
    tags: list[str] | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    musical_key: str | None = None,
) -> list[sqlite3.Row]:
    """Plain LIKE/JOIN search -- see schema.sql for why this isn't FTS5."""
    clauses, params = _base_filter(text=text, tags=tags, bpm_min=bpm_min, bpm_max=bpm_max, musical_key=musical_key)
    query = "SELECT DISTINCT s.* FROM samples s WHERE " + " AND ".join(clauses) + " ORDER BY s.cleaned_filename"
    return conn.execute(query, params).fetchall()


def tag_counts(
    conn: sqlite3.Connection,
    *,
    text: str | None = None,
    tags: list[str] | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    musical_key: str | None = None,
) -> dict[str, int]:
    """How many currently-matching samples have each tag, for faceted
    narrowing: call with the filters already applied so far to get counts for
    what's still worth offering next. Tags already selected are excluded
    (nothing to learn from re-showing them). Called with no filters at all,
    this is just the overall tag cloud -- used for `stats`.
    """
    clauses, params = _base_filter(text=text, tags=tags, bpm_min=bpm_min, bpm_max=bpm_max, musical_key=musical_key)
    query = (
        "SELECT t.name AS tag, COUNT(DISTINCT s.id) AS n "
        "FROM samples s JOIN sample_tags st ON st.sample_id = s.id JOIN tags t ON t.id = st.tag_id "
        "WHERE " + " AND ".join(clauses) + " GROUP BY t.name ORDER BY n DESC, t.name"
    )
    rows = conn.execute(query, params).fetchall()
    already_selected = set(tags or [])
    return {row["tag"]: row["n"] for row in rows if row["tag"] not in already_selected}


def tags_for_sample(conn: sqlite3.Connection, sample_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN sample_tags st ON st.tag_id = t.id
        WHERE st.sample_id = ?
        ORDER BY t.name
        """,
        (sample_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def count_samples(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM samples").fetchone()["n"]


def count_by_bucket(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT bucket, COUNT(*) AS n FROM samples GROUP BY bucket").fetchall()
    return {row["bucket"]: row["n"] for row in rows}
