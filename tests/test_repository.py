from pathlib import Path

import pytest

from sample_librarian.db import repository
from sample_librarian.db.repository import SampleRecord


def _record(current_path: str, **overrides) -> SampleRecord:
    defaults = dict(
        current_path=current_path,
        bucket="orphan",
        source_path=current_path,
        is_symlink_at_current=False,
        stub_left_at_source=True,
        vendor_name=None,
        original_filename="Kick.wav",
        cleaned_filename="Kick.wav",
        file_ext=".wav",
        file_size_bytes=1234,
        classification_method="filename_heuristic",
        bpm=120.0,
        bpm_source="filename_regex",
        musical_key=None,
        key_source=None,
        acid_chunk_present=False,
        duration_seconds=1.5,
        sample_rate=44100,
        channels=1,
        tags=("kick", "drum"),
    )
    defaults.update(overrides)
    return SampleRecord(**defaults)


def test_new_sample_defaults_to_rating_zero(tmp_path: Path):
    with repository.open_db(tmp_path / "library.sqlite3") as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = repository.upsert_sample(conn, _record(str(tmp_path / "Kick.wav")), scan_run_id)
        row = conn.execute("SELECT rating FROM samples WHERE id = ?", (sample_id,)).fetchone()
        assert row["rating"] == 0


def test_set_rating_then_rescan_upsert_does_not_reset_it(tmp_path: Path):
    """A rescan re-upserting an already-known file (same current_path) must
    never clobber a rating the user set from the app -- rating isn't a scan
    output.
    """
    with repository.open_db(tmp_path / "library.sqlite3") as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        path = str(tmp_path / "Kick.wav")
        sample_id = repository.upsert_sample(conn, _record(path), scan_run_id)

        repository.set_rating(conn, sample_id, 2)
        assert conn.execute("SELECT rating FROM samples WHERE id = ?", (sample_id,)).fetchone()["rating"] == 2

        # simulate a rescan re-upserting the same file
        second_scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        repository.upsert_sample(conn, _record(path, bpm=121.0), second_scan_run_id)

        row = conn.execute("SELECT rating, bpm FROM samples WHERE id = ?", (sample_id,)).fetchone()
        assert row["rating"] == 2  # untouched
        assert row["bpm"] == 121.0  # scan-derived fields still update normally


def test_set_rating_rejects_out_of_range(tmp_path: Path):
    with repository.open_db(tmp_path / "library.sqlite3") as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = repository.upsert_sample(conn, _record(str(tmp_path / "Kick.wav")), scan_run_id)
        with pytest.raises(ValueError):
            repository.set_rating(conn, sample_id, 3)
