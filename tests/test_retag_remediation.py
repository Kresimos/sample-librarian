from pathlib import Path

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import SampleRecord
from sample_librarian.pipeline.retag_remediation import apply_retags, plan_retags
from sample_librarian.undo import undo_scan_run

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=(),
        audio_extensions=(".wav",),
    )


def _insert_sample(
    conn,
    *,
    current_path: Path,
    source_path: Path | None = None,
    bucket: str = "orphan",
    vendor_name: str | None = None,
    tags: tuple[str, ...] = (),
    scan_run_id: int,
) -> int:
    record = SampleRecord(
        current_path=str(current_path),
        bucket=bucket,
        source_path=str(source_path or current_path),
        is_symlink_at_current=(bucket == "vendor"),
        stub_left_at_source=False,
        vendor_name=vendor_name,
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


def test_plan_retags_picks_up_a_new_taxonomy_keyword(tmp_path: Path):
    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    path = write_minimal_wav(settings.unsorted_dir / "Cymatics Drum And Bass Loop.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        # Simulate a sample classified before "dnb"/"cymatics" existed in the taxonomy.
        sample_id = _insert_sample(conn, current_path=path, tags=("loop",), scan_run_id=scan_run_id)

        plans = plan_retags(conn, taxonomy_rules)

        assert len(plans) == 1
        assert plans[0].sample_id == sample_id
        assert "dnb" in plans[0].new_tags
        assert "cymatics" in plans[0].new_tags
        assert plans[0].old_tags == ("loop",)


def test_plan_retags_mirrors_vendor_name_into_tags(tmp_path: Path):
    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    path = write_minimal_wav(settings.vendor_dir / "Splice" / "kick.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        # Simulate a sample upserted before vendor_name-to-tag mirroring existed.
        _insert_sample(
            conn, current_path=path, bucket="vendor", vendor_name="Splice",
            tags=("kick", "drum"), scan_run_id=scan_run_id,
        )

        plans = plan_retags(conn, taxonomy_rules)

        assert len(plans) == 1
        assert "splice" in plans[0].new_tags


def test_plan_retags_skips_samples_whose_tags_are_already_current(tmp_path: Path):
    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    path = write_minimal_wav(settings.unsorted_dir / "Kick Heavy.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(conn, current_path=path, tags=("kick", "drum", "one-shot"), scan_run_id=scan_run_id)

        assert plan_retags(conn, taxonomy_rules) == []


def test_apply_retags_replaces_tags_in_db(tmp_path: Path):
    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    path = write_minimal_wav(settings.unsorted_dir / "Cymatics Drum And Bass Loop.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = _insert_sample(conn, current_path=path, tags=("loop",), scan_run_id=scan_run_id)

        plans = plan_retags(conn, taxonomy_rules)
        report = apply_retags(conn, settings, plans)

        assert report.errors == []
        assert report.retagged_count == 1
        new_tags = set(repository.tags_for_sample(conn, sample_id))
        assert "dnb" in new_tags
        assert "cymatics" in new_tags
        assert "loop" in new_tags  # untouched signal preserved by re-classification


def test_undo_reverses_retag_remediation(tmp_path: Path):
    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    path = write_minimal_wav(settings.unsorted_dir / "Cymatics Drum And Bass Loop.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = _insert_sample(conn, current_path=path, tags=("loop",), scan_run_id=scan_run_id)

        plans = plan_retags(conn, taxonomy_rules)
        report = apply_retags(conn, settings, plans)
        assert "dnb" in set(repository.tags_for_sample(conn, sample_id))

        undo_report = undo_scan_run(conn, report.scan_run_id)

        assert undo_report.skipped == []
        assert set(repository.tags_for_sample(conn, sample_id)) == {"loop"}


def test_plan_retags_is_pure_and_reports_nothing_left_after_apply(tmp_path: Path):
    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    path = write_minimal_wav(settings.unsorted_dir / "Cymatics Drum And Bass Loop.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(conn, current_path=path, tags=("loop",), scan_run_id=scan_run_id)

        first_plans = plan_retags(conn, taxonomy_rules)
        assert len(first_plans) == 1

        apply_retags(conn, settings, first_plans)

        assert plan_retags(conn, taxonomy_rules) == []
