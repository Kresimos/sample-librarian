from pathlib import Path

from sample_librarian.audio import riff_chunks
from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.initial_sweep import run_apply_sweep
from sample_librarian.undo import undo_scan_run

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def _make_settings(tmp_path: Path, *, vendor_roots=()) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=tuple(vendor_roots),
        audio_extensions=(".wav",),
    )


def test_apply_sweep_moves_orphan_and_symlinks_vendor(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    vendor_dir = scan_dir / "VendorLib"
    vendor_dir.mkdir(parents=True)

    orphan_source = write_minimal_wav(scan_dir / "Cool_Break_120bpm.wav")
    orphan_original_chunks = riff_chunks.read_chunks(orphan_source)
    orphan_original_data = riff_chunks.get_chunk(orphan_original_chunks, "data").data
    vendor_source = write_minimal_wav(vendor_dir / "kick.wav")
    vendor_bytes = vendor_source.read_bytes()

    settings = _make_settings(tmp_path, vendor_roots=[vendor_dir])
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)

        assert report.errors == []
        assert report.vendor_count == 1
        assert report.orphan_count == 1

        # orphan: real file physically moved, stub symlink left behind
        orphan_target = settings.unsorted_dir / "Cool Break.wav"
        assert orphan_target.exists()
        assert orphan_source.is_symlink()

        # tempo written back into the moved file's own ACID chunk; audio data
        # itself (not the raw bytes, which legitimately change once the ACID
        # chunk is added) must be untouched
        chunks = riff_chunks.read_chunks(orphan_target)
        acid = riff_chunks.read_acid(chunks)
        assert acid is not None
        assert acid.tempo == 120.0
        assert riff_chunks.get_chunk(chunks, "data").data == orphan_original_data
        # the stub symlink transparently reaches the same (now tempo-tagged) file
        assert riff_chunks.get_chunk(riff_chunks.read_chunks(orphan_source), "data").data == orphan_original_data

        # vendor: symlinked into the library, original completely untouched
        vendor_target = settings.vendor_dir / "VendorLib" / "kick.wav"
        assert vendor_target.is_symlink()
        assert vendor_target.read_bytes() == vendor_bytes
        assert vendor_source.exists() and not vendor_source.is_symlink()
        vendor_chunks = riff_chunks.read_chunks(vendor_source)
        assert riff_chunks.read_acid(vendor_chunks) is None  # never written to

        assert repository.count_samples(conn) == 2
        by_bucket = repository.count_by_bucket(conn)
        assert by_bucket == {"vendor": 1, "orphan": 1}


def test_undo_restores_orphan_file_and_removes_tempo_writeback(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)
    orphan_source = write_minimal_wav(scan_dir / "Deep_House_124.wav")
    original_bytes = orphan_source.read_bytes()

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)
        assert report.errors == []

        target = settings.unsorted_dir / "Deep House.wav"
        assert target.exists()
        assert orphan_source.is_symlink()

        undo_report = undo_scan_run(conn, report.scan_run_id)

        assert undo_report.skipped == []
        assert not target.exists()
        assert orphan_source.exists() and not orphan_source.is_symlink()
        assert orphan_source.read_bytes() == original_bytes
        assert repository.count_samples(conn) == 0


def test_undo_restores_vendor_symlink_removal_and_leaves_original(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    vendor_dir = scan_dir / "VendorLib"
    vendor_dir.mkdir(parents=True)
    vendor_source = write_minimal_wav(vendor_dir / "snare.wav")
    original_bytes = vendor_source.read_bytes()

    settings = _make_settings(tmp_path, vendor_roots=[vendor_dir])
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)
        target = settings.vendor_dir / "VendorLib" / "snare.wav"
        assert target.is_symlink()

        undo_report = undo_scan_run(conn, report.scan_run_id)

        assert undo_report.skipped == []
        assert not target.exists()
        assert vendor_source.exists() and not vendor_source.is_symlink()
        assert vendor_source.read_bytes() == original_bytes


def test_undo_restores_previously_missing_acid_chunk_to_absent(tmp_path: Path):
    """A file that had no ACID chunk before getting tempo-written should have
    none after undo -- not a leftover chunk with a stale tempo.
    """
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)
    write_minimal_wav(scan_dir / "Track_90bpm.wav")

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)
        undo_scan_run(conn, report.scan_run_id)

    restored = scan_dir / "Track_90bpm.wav"
    chunks = riff_chunks.read_chunks(restored)
    assert riff_chunks.read_acid(chunks) is None
