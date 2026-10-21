from pathlib import Path

from sample_librarian.audio import riff_chunks, smart_tempo
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

        orphan_row = conn.execute(
            "SELECT stub_left_at_source, is_symlink_at_current FROM samples WHERE bucket = 'orphan'"
        ).fetchone()
        assert orphan_row["stub_left_at_source"] == 1
        assert orphan_row["is_symlink_at_current"] == 0
        vendor_row = conn.execute(
            "SELECT stub_left_at_source, is_symlink_at_current FROM samples WHERE bucket = 'vendor'"
        ).fetchone()
        assert vendor_row["stub_left_at_source"] == 0
        assert vendor_row["is_symlink_at_current"] == 1
        by_bucket = repository.count_by_bucket(conn)
        assert by_bucket == {"vendor": 1, "orphan": 1}


def test_apply_sweep_dedupes_case_insensitive_collisions(tmp_path: Path):
    # Regression (2026-08-26): a real vintage-drum-machine sample collection
    # had the same hit name spelled in different cases in different kit
    # folders (e.g. "TOM1.WAV" all-caps in one, "Tom1.wav" in another).
    # clean_filename's acronym-preserving title-case keeps "TOM1" upper and
    # title-cases "Tom1" -- two different Python strings that are still the
    # exact same path on macOS's case-insensitive default filesystem, so a
    # naive case-sensitive dedup let both through as "unique" and the second
    # file's real move failed with "destination already exists".
    scan_dir = tmp_path / "scan"
    write_minimal_wav(scan_dir / "kitA" / "TOM1.WAV")
    write_minimal_wav(scan_dir / "kitB" / "Tom1.wav")

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)

    assert report.errors == []
    assert report.orphan_count == 2
    unsorted_names = sorted(p.name for p in settings.unsorted_dir.iterdir())
    assert len(unsorted_names) == 2  # no case-insensitive collision on disk


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

        # "124" stays in the display name now -- a bare number is no longer
        # confidently treated as tempo (see filename_regex.py), so it isn't
        # confidently stripped from the cleaned name either.
        target = settings.unsorted_dir / "Deep House 124.wav"
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


def test_apply_writes_smart_tempo_chunk_and_undo_removes_it(tmp_path: Path):
    """Logic Pro's own "File Tempo" field on a plain drag is driven by the
    Smart Tempo ('ResU') chunk, not the ACID chunk -- confirmed empirically
    2026-08-25 -- so both must be written on apply and both cleanly reversed
    on undo.
    """
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)
    write_minimal_wav(scan_dir / "Deep_House_124bpm.wav")

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)
        assert report.errors == []

        target = settings.unsorted_dir / "Deep House.wav"
        result = smart_tempo.read_smart_tempo(target)
        assert result is not None
        assert result["Tempo"] == [{"t": 0, "conf": -1, "tempo": 124.0}]

        undo_scan_run(conn, report.scan_run_id)

    restored = scan_dir / "Deep_House_124bpm.wav"
    assert smart_tempo.read_smart_tempo(restored) is None


def test_undo_restores_a_vendor_files_pre_existing_smart_tempo_chunk_exactly(tmp_path: Path):
    """A file that already had its own real Smart Tempo analysis (e.g. from
    a sample pack that's been through Logic at some point) must get that
    exact chunk back on undo, not just have ours deleted -- merge_tempo-style
    "preserve what was already there" behavior, same as the ACID chunk.
    """
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)
    source = write_minimal_wav(scan_dir / "Groove_120bpm.wav")
    smart_tempo.write_smart_tempo(source, duration_seconds=99.0, tempo=77.0)
    pre_existing_raw = smart_tempo.read_raw_chunk_data(source)

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)
        assert report.errors == []

        target = settings.unsorted_dir / "Groove.wav"
        # our own write-back replaced it with a 120bpm result derived from the filename
        assert smart_tempo.read_smart_tempo(target)["Tempo"] == [{"t": 0, "conf": -1, "tempo": 120.0}]

        undo_scan_run(conn, report.scan_run_id)

    restored = scan_dir / "Groove_120bpm.wav"
    assert smart_tempo.read_raw_chunk_data(restored) == pre_existing_raw


def test_undo_only_removes_db_rows_for_entries_actually_reversed(tmp_path: Path):
    """If reversing one file's move fails partway through an undo, that
    file is still really sitting in the library -- its samples row must
    NOT be deleted just because it shares a scan_run_id with files that
    *were* successfully reversed.
    """
    import shutil as shutil_module
    from unittest.mock import patch

    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)
    write_minimal_wav(scan_dir / "Alpha.wav")
    write_minimal_wav(scan_dir / "Beta.wav")

    settings = _make_settings(tmp_path)
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)

    real_move = shutil_module.move

    def flaky_move(src, dst, *args, **kwargs):
        if "Alpha" in str(dst):
            raise OSError("simulated: could not restore Alpha")
        return real_move(src, dst, *args, **kwargs)

    with repository.open_db(settings.db_path) as conn:
        report = run_apply_sweep(settings, taxonomy_rules, conn)
        assert report.errors == []

        with patch("sample_librarian.undo.shutil.move", side_effect=flaky_move):
            undo_report = undo_scan_run(conn, report.scan_run_id)

        assert len(undo_report.skipped) == 1
        assert "Alpha" in str(undo_report.skipped[0][0].dest)

        remaining = conn.execute("SELECT cleaned_filename FROM samples").fetchall()
        assert {r["cleaned_filename"] for r in remaining} == {"Alpha.wav"}
        assert (settings.unsorted_dir / "Alpha.wav").exists()  # still there, correctly tracked
        # best-effort: the stub got put back rather than leaving the original
        # location with neither a stub nor the restored file
        assert (scan_dir / "Alpha.wav").is_symlink()
        assert not (settings.unsorted_dir / "Beta.wav").exists()  # successfully restored
        assert (scan_dir / "Beta.wav").exists()
