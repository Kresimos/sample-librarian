from pathlib import Path

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.initial_sweep import run_dry_run_sweep

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def _make_settings(tmp_path: Path, *, vendor_roots=()) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=tuple(vendor_roots),
        audio_extensions=(".wav",),
    )


def test_dry_run_sweep_classifies_vendor_and_orphan_buckets(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    vendor_dir = scan_dir / "VendorLib"
    vendor_dir.mkdir(parents=True)

    orphan_file = write_minimal_wav(scan_dir / "Cool_Break_120bpm.wav")
    vendor_file = write_minimal_wav(vendor_dir / "kick.wav")

    settings = _make_settings(tmp_path, vendor_roots=[vendor_dir])
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_dry_run_sweep(settings, taxonomy_rules, conn)

        assert report.files_scanned == 2
        assert report.vendor_count == 1
        assert report.orphan_count == 1
        assert report.errors == []

        by_source = {a.source_path: a for a in report.actions}

        vendor_action = by_source[vendor_file]
        assert vendor_action.bucket == "vendor"
        assert vendor_action.vendor_name == "VendorLib"
        assert vendor_action.target_path == settings.vendor_dir / "VendorLib" / "kick.wav"
        # vendor files are mirrored verbatim, never renamed
        assert vendor_action.cleaned_filename == "kick.wav"

        orphan_action = by_source[orphan_file]
        assert orphan_action.bucket == "orphan"
        assert orphan_action.target_path.parent == settings.unsorted_dir
        assert "120" not in orphan_action.cleaned_filename
        assert "bpm" not in orphan_action.cleaned_filename.lower()
        assert orphan_action.bpm == 120.0
        assert orphan_action.bpm_source == "filename_regex"
        assert "breakbeat" in orphan_action.tags
        assert orphan_action.would_write_tempo_metadata is True

        # dry run must never populate the samples table -- nothing has actually moved
        assert repository.count_samples(conn) == 0

        run_row = conn.execute("SELECT * FROM scan_runs WHERE id = ?", (report.scan_run_id,)).fetchone()
        assert run_row["dry_run"] == 1
        assert run_row["files_scanned"] == 2
        assert run_row["run_type"] == "initial_sweep"


def test_dry_run_sweep_handles_collisions_in_orphan_bucket(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)

    write_minimal_wav(scan_dir / "Kick_Heavy.wav")
    (scan_dir / "sub").mkdir()
    write_minimal_wav(scan_dir / "sub" / "kick___heavy.wav")

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_dry_run_sweep(settings, taxonomy_rules, conn)

    target_names = sorted(a.cleaned_filename for a in report.actions)
    assert target_names == ["Kick Heavy 2.wav", "Kick Heavy.wav"]


def test_dry_run_sweep_ignores_symlinks_and_excludes_library_root(tmp_path: Path):
    # library_root deliberately nested inside the scan_root, to exercise
    # exclude_root actually filtering it out during a single-root walk.
    scan_dir = tmp_path / "scan"
    library_dir = scan_dir / "library"
    scan_dir.mkdir(parents=True)

    real_file = write_minimal_wav(scan_dir / "Real.wav")
    symlink_file = scan_dir / "Link.wav"
    symlink_file.symlink_to(real_file)

    inside_library = library_dir / "unsorted" / "Already_Organized.wav"
    inside_library.parent.mkdir(parents=True)
    write_minimal_wav(inside_library)

    settings = Settings(
        library_root=library_dir,
        scan_roots=(scan_dir,),
        vendor_roots=(),
        audio_extensions=(".wav",),
    )
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_dry_run_sweep(settings, taxonomy_rules, conn)

    scanned_sources = {a.source_path for a in report.actions}
    assert real_file in scanned_sources
    assert symlink_file not in scanned_sources
    assert inside_library not in scanned_sources
