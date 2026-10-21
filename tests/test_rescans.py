import os
from datetime import datetime, timezone
from pathlib import Path

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.inbox_rescan import run_inbox_rescan
from sample_librarian.pipeline.initial_sweep import run_apply_sweep
from sample_librarian.pipeline.vendor_rescan import run_vendor_rescan

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def _make_settings(tmp_path: Path, *, vendor_roots=(), inbox_dir_override=None) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=tuple(vendor_roots),
        audio_extensions=(".wav",),
        inbox_dir_override=inbox_dir_override,
    )


def test_inbox_rescan_moves_inbox_contents_into_unsorted_and_empties_inbox(tmp_path: Path):
    settings = _make_settings(tmp_path)
    settings.inbox_dir.mkdir(parents=True)
    write_minimal_wav(settings.inbox_dir / "New_Find_128bpm.wav")
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_inbox_rescan(settings, taxonomy_rules, conn)

    assert report.errors == []
    assert report.orphan_count == 1
    assert list(settings.inbox_dir.iterdir()) == []  # empty again
    assert (settings.unsorted_dir / "New Find.wav").exists()

    with repository.open_db(settings.db_path) as conn:
        run_row = conn.execute(
            "SELECT run_type FROM scan_runs WHERE id = ?", (report.scan_run_id,)
        ).fetchone()
    assert run_row["run_type"] == "inbox_rescan"


def test_inbox_rescan_records_stub_left_at_source_as_false(tmp_path: Path):
    """inbox_rescan never leaves a stub symlink behind (see mover.py) --
    the samples table must reflect that accurately, not just hardcode True
    for every orphan-bucket row regardless of which pipeline moved it.
    """
    settings = _make_settings(tmp_path)
    settings.inbox_dir.mkdir(parents=True)
    write_minimal_wav(settings.inbox_dir / "New_Find.wav")
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        run_inbox_rescan(settings, taxonomy_rules, conn)
        row = conn.execute("SELECT stub_left_at_source FROM samples").fetchone()

    assert row["stub_left_at_source"] == 0


def test_inbox_rescan_respects_existing_unsorted_contents_for_collisions(tmp_path: Path):
    settings = _make_settings(tmp_path)
    settings.inbox_dir.mkdir(parents=True)
    settings.unsorted_dir.mkdir(parents=True)
    write_minimal_wav(settings.unsorted_dir / "Kick Heavy.wav")  # from an earlier run
    write_minimal_wav(settings.inbox_dir / "Kick_Heavy.wav")  # cleans to the same name
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_inbox_rescan(settings, taxonomy_rules, conn)

    assert report.errors == []
    names = {p.name for p in settings.unsorted_dir.iterdir()}
    assert names == {"Kick Heavy.wav", "Kick Heavy 2.wav"}


def test_inbox_dir_can_be_repurposed_to_an_existing_folder(tmp_path: Path):
    """inbox_dir doesn't have to be a dedicated empty folder under
    library_root -- e.g. pointing it at ~/Downloads via settings.toml's
    inbox_dir override.
    """
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    settings = _make_settings(tmp_path, inbox_dir_override=downloads)
    assert settings.inbox_dir == downloads
    write_minimal_wav(downloads / "New_Find_128bpm.wav")
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_inbox_rescan(settings, taxonomy_rules, conn)

    assert report.errors == []
    assert report.orphan_count == 1
    assert list(downloads.iterdir()) == []  # only the sample was in there, now gone
    assert (settings.unsorted_dir / "New Find.wav").exists()


def test_inbox_rescan_incremental_skips_files_unmodified_since_last_run(tmp_path: Path):
    """A mixed-content dumping-ground inbox (e.g. repurposed ~/Downloads)
    shouldn't have every file reconsidered on every run -- only ones modified
    since the last completed inbox_rescan.
    """
    settings = _make_settings(tmp_path)
    settings.inbox_dir.mkdir(parents=True)
    write_minimal_wav(settings.inbox_dir / "First.wav")
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        first = run_inbox_rescan(settings, taxonomy_rules, conn)
        assert first.orphan_count == 1

        # Pin the recorded run start so the next cutoff is deterministic,
        # independent of real wall-clock timing between the two runs.
        conn.execute(
            "UPDATE scan_runs SET started_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", first.scan_run_id),
        )
        conn.commit()

    # A file whose mtime predates the pinned cutoff -- e.g. something that
    # was already sitting in Downloads before it became the inbox. Must be
    # left alone, not silently swept up.
    stale = write_minimal_wav(settings.inbox_dir / "Stale.wav")
    old_time = datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(stale, (old_time, old_time))

    # A file that genuinely arrived after the cutoff -- must still be picked up.
    fresh = write_minimal_wav(settings.inbox_dir / "Fresh.wav")
    new_time = datetime(2020, 6, 1, tzinfo=timezone.utc).timestamp()
    os.utime(fresh, (new_time, new_time))

    with repository.open_db(settings.db_path) as conn:
        second = run_inbox_rescan(settings, taxonomy_rules, conn)

    assert second.orphan_count == 1
    assert stale.exists()  # untouched
    assert not fresh.exists()  # moved into unsorted/
    assert (settings.unsorted_dir / "Fresh.wav").exists()


def test_vendor_rescan_only_symlinks_never_moves(tmp_path: Path):
    vendor_dir = tmp_path / "VendorLib"
    settings = _make_settings(tmp_path, vendor_roots=[vendor_dir])
    new_vendor_file = write_minimal_wav(vendor_dir / "new_pack" / "snare.wav")
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_vendor_rescan(settings, taxonomy_rules, conn)

    assert report.errors == []
    assert report.vendor_count == 1
    assert report.orphan_count == 0
    target = settings.vendor_dir / "VendorLib" / "new_pack" / "snare.wav"
    assert target.is_symlink()
    assert new_vendor_file.exists() and not new_vendor_file.is_symlink()


def test_vendor_rescan_is_idempotent_and_picks_up_new_files(tmp_path: Path):
    vendor_dir = tmp_path / "VendorLib"
    settings = _make_settings(tmp_path, vendor_roots=[vendor_dir])
    write_minimal_wav(vendor_dir / "kick.wav")
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        first = run_vendor_rescan(settings, taxonomy_rules, conn)
        assert first.vendor_count == 1
        assert first.errors == []

        # a second file appears later, e.g. a new pack installed
        write_minimal_wav(vendor_dir / "clap.wav")
        second = run_vendor_rescan(settings, taxonomy_rules, conn)

    # re-running is safe: kick.wav's already-correct symlink is a silent
    # no-op (not an error), and the genuinely new file gets symlinked too
    assert second.errors == []
    assert second.vendor_count == 2
    assert (settings.vendor_dir / "VendorLib" / "kick.wav").is_symlink()
    assert (settings.vendor_dir / "VendorLib" / "clap.wav").is_symlink()
