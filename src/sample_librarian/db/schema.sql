PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS scan_runs (
    id              INTEGER PRIMARY KEY,
    run_type        TEXT NOT NULL CHECK (run_type IN ('initial_sweep', 'inbox_rescan', 'vendor_rescan')),
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
    sample_type               TEXT,
    classification_method     TEXT NOT NULL DEFAULT 'filename_heuristic'
                               CHECK (classification_method IN ('filename_heuristic', 'waveform_analysis', 'manual')),
    classification_confidence REAL,
    bpm                       REAL,
    bpm_source                TEXT CHECK (bpm_source IN ('embedded_acid', 'embedded_id3', 'filename_regex', 'manual')),
    musical_key               TEXT,
    key_source                TEXT CHECK (key_source IN ('embedded_acid', 'embedded_id3', 'filename_regex', 'manual')),
    acid_chunk_present         INTEGER NOT NULL DEFAULT 0,
    acid_chunk_written_by_tool INTEGER NOT NULL DEFAULT 0,
    duration_seconds          REAL,
    sample_rate                INTEGER,
    channels                   INTEGER,
    scan_run_id                INTEGER REFERENCES scan_runs(id),
    last_seen_at                TEXT NOT NULL,
    status                       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'missing', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_samples_bucket ON samples(bucket);
CREATE INDEX IF NOT EXISTS idx_samples_type ON samples(sample_type);
CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_tags (
    sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (sample_id, tag_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS samples_fts USING fts5(
    cleaned_filename,
    sample_type,
    tags_text,
    content = 'samples',
    content_rowid = 'id'
);

CREATE TRIGGER IF NOT EXISTS samples_ai AFTER INSERT ON samples BEGIN
    INSERT INTO samples_fts(rowid, cleaned_filename, sample_type, tags_text)
    VALUES (new.id, new.cleaned_filename, new.sample_type, '');
END;

CREATE TRIGGER IF NOT EXISTS samples_ad AFTER DELETE ON samples BEGIN
    INSERT INTO samples_fts(samples_fts, rowid, cleaned_filename, sample_type, tags_text)
    VALUES ('delete', old.id, old.cleaned_filename, old.sample_type, '');
END;

CREATE TRIGGER IF NOT EXISTS samples_au AFTER UPDATE ON samples BEGIN
    INSERT INTO samples_fts(samples_fts, rowid, cleaned_filename, sample_type, tags_text)
    VALUES ('delete', old.id, old.cleaned_filename, old.sample_type, '');
    INSERT INTO samples_fts(rowid, cleaned_filename, sample_type, tags_text)
    VALUES (new.id, new.cleaned_filename, new.sample_type, '');
END;
