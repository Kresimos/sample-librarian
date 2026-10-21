from pathlib import Path

from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import SampleRecord
from sample_librarian.pipeline.rename_remediation import apply_renames, plan_renames
from sample_librarian.undo import undo_scan_run

from .helpers import write_minimal_wav


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=(),
        audio_extensions=(".wav",),
    )


def _insert_orphan_sample(
    conn, *, current_path: Path, tags: tuple[str, ...] = (), scan_run_id: int
) -> int:
    record = SampleRecord(
        current_path=str(current_path),
        bucket="orphan",
        source_path=str(current_path),
        is_symlink_at_current=False,
        stub_left_at_source=True,
        vendor_name=None,
        original_filename=current_path.name,
        cleaned_filename=current_path.name,
        file_ext=current_path.suffix,
        file_size_bytes=current_path.stat().st_size,
        classification_method="filename_heuristic",
        bpm=None,
        bpm_source=None,
        musical_key=None,
        key_source=None,
        acid_chunk_present=False,
        duration_seconds=None,
        sample_rate=None,
        channels=None,
        tags=tags,
    )
    return repository.upsert_sample(conn, record, scan_run_id)


def test_plan_renames_only_targets_mangled_names_and_preserves_tags(tmp_path: Path):
    settings = _make_settings(tmp_path)

    mangled = write_minimal_wav(
        settings.unsorted_dir
        / r"Cymatics House Starter Pack\synth Loop Collection\supersaw Loops\cymatics Super Saw Loop 15.wav"
    )
    clean = write_minimal_wav(settings.unsorted_dir / "Kick Heavy.wav")
    # backslash from an escaped quote, not a mangled path -- must be left alone
    escaped_quote = write_minimal_wav(settings.unsorted_dir / r'Anthem \"God Save The Queen\".wav')

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        mangled_id = _insert_orphan_sample(
            conn, current_path=mangled, tags=("synth", "melodic", "loop"), scan_run_id=scan_run_id
        )
        _insert_orphan_sample(conn, current_path=clean, tags=("kick", "drum"), scan_run_id=scan_run_id)
        _insert_orphan_sample(conn, current_path=escaped_quote, tags=("song",), scan_run_id=scan_run_id)

        plans = plan_renames(conn)

        assert len(plans) == 1
        assert plans[0].sample_id == mangled_id
        assert plans[0].old_path == mangled
        assert plans[0].new_path == settings.unsorted_dir / "Cymatics Super Saw Loop 15.wav"


def test_apply_renames_renames_file_updates_db_and_keeps_tags(tmp_path: Path):
    settings = _make_settings(tmp_path)
    mangled = write_minimal_wav(
        settings.unsorted_dir / r"Pack\Synth Loop Collection\Chord Loops\Cymatics Chord Loop 1.wav"
    )

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = _insert_orphan_sample(
            conn, current_path=mangled, tags=("chord", "melodic"), scan_run_id=scan_run_id
        )

        plans = plan_renames(conn)
        report = apply_renames(conn, settings, plans)

        assert report.errors == []
        assert report.renamed_count == 1

        new_path = settings.unsorted_dir / "Cymatics Chord Loop 1.wav"
        assert new_path.exists()
        assert not mangled.exists()

        row = conn.execute("SELECT current_path, cleaned_filename FROM samples WHERE id = ?", (sample_id,)).fetchone()
        assert row["current_path"] == str(new_path)
        assert row["cleaned_filename"] == "Cymatics Chord Loop 1.wav"
        assert set(repository.tags_for_sample(conn, sample_id)) == {"chord", "melodic"}


def test_apply_renames_avoids_collisions_with_existing_clean_name(tmp_path: Path):
    settings = _make_settings(tmp_path)
    mangled = write_minimal_wav(
        settings.unsorted_dir / r"Pack\Kicks\Kick 1.wav"
    )
    already_clean = write_minimal_wav(settings.unsorted_dir / "Kick 1.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_orphan_sample(conn, current_path=mangled, scan_run_id=scan_run_id)
        _insert_orphan_sample(conn, current_path=already_clean, scan_run_id=scan_run_id)

        plans = plan_renames(conn)
        report = apply_renames(conn, settings, plans)

        assert report.errors == []
        assert (settings.unsorted_dir / "Kick 1 2.wav").exists()
        assert already_clean.exists()  # untouched


def test_undo_reverses_rename_remediation(tmp_path: Path):
    settings = _make_settings(tmp_path)
    mangled = write_minimal_wav(
        settings.unsorted_dir / r"Pack\Synth Loops\Cymatics Arp Loop 1.wav"
    )

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = _insert_orphan_sample(conn, current_path=mangled, tags=("arp",), scan_run_id=scan_run_id)

        plans = plan_renames(conn)
        report = apply_renames(conn, settings, plans)
        new_path = settings.unsorted_dir / "Cymatics Arp Loop 1.wav"
        assert new_path.exists()

        undo_report = undo_scan_run(conn, report.scan_run_id)

        assert undo_report.skipped == []
        assert not new_path.exists()
        assert mangled.exists()

        row = conn.execute("SELECT current_path, cleaned_filename FROM samples WHERE id = ?", (sample_id,)).fetchone()
        assert row["current_path"] == str(mangled)
        assert row["cleaned_filename"] == mangled.name
        assert set(repository.tags_for_sample(conn, sample_id)) == {"arp"}


def test_plan_renames_is_pure_and_reports_nothing_left_after_apply(tmp_path: Path):
    settings = _make_settings(tmp_path)
    mangled = write_minimal_wav(settings.unsorted_dir / r"Pack\Loops\Cymatics Loop 1.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_orphan_sample(conn, current_path=mangled, scan_run_id=scan_run_id)

        first_plans = plan_renames(conn)
        assert len(first_plans) == 1
        assert mangled.exists()  # planning alone must not touch the filesystem

        apply_renames(conn, settings, first_plans)

        assert plan_renames(conn) == []
