from pathlib import Path

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.inbox_rescan import run_inbox_rescan
from sample_librarian.pipeline.initial_sweep import run_apply_sweep
from sample_librarian.pipeline.vendor_rescan import run_vendor_rescan

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def _make_settings(tmp_path: Path, *, vendor_roots=()) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=tuple(vendor_roots),
        audio_extensions=(".wav",),
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
