PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS scan_runs (
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

CREATE TABLE IF NOT EXISTS samples (
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
    -- User-set from the Stage 2 app (-2..+2), not a scan/classification
    -- output -- upsert_sample() must never overwrite this on a rescan.
    rating                       INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN -2 AND 2)
);

CREATE INDEX IF NOT EXISTS idx_samples_bucket ON samples(bucket);
CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);
-- idx_samples_rating and idx_samples_browse_rating are created in
-- repository._migrate(), not here: this script runs unconditionally (even
-- against a pre-existing DB whose samples table predates the rating column),
-- and CREATE INDEX IF NOT EXISTS still errors against a column that doesn't
-- exist yet on that old table.

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_tags (
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (sample_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_sample_tags_tag_id ON sample_tags(tag_id);

-- Search (Stage 2) uses plain LIKE/JOIN queries, not FTS5: an external-content
-- FTS5 table needs its triggers to see the *current* indexed values on every
-- delete/update (including tag changes, which happen in a separate table the
-- samples-row triggers can't see), and getting that right without a live
-- system to verify against is exactly the kind of subtle bug not worth
-- risking here.
--
-- The cost of that choice, measured at 24k samples / 109k sample_tags: a
-- substring search is ~43ms and the full sorted scan ~19ms. Fine, but note
-- these are NOT indexed lookups -- LIKE '%term%' can't use an index at all, so
-- every search is a full scan by construction. What the indexes above do buy
-- is the ORDER BY (see idx_samples_browse_rating), which is what lets the
-- Stage 2 browser's paged LIMIT stop early instead of sorting every match.
-- FTS5 becomes worth revisiting if this grows another order of magnitude.
