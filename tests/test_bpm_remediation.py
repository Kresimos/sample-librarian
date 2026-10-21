from pathlib import Path

from sample_librarian.audio import riff_chunks
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import SampleRecord
from sample_librarian.pipeline.bpm_remediation import apply_bpm_fills, plan_bpm_fills
from sample_librarian.undo import undo_scan_run

from .helpers import build_minimal_wav
from .test_aiff_caf_chunks import build_caf


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=(),
        audio_extensions=(".wav", ".caf"),
    )


def _insert(conn, scan_run_id, path: Path, **overrides) -> int:
    defaults = dict(
        current_path=str(path), bucket="orphan", source_path=str(path),
        is_symlink_at_current=False, stub_left_at_source=False, vendor_name=None,
        original_filename=path.name, cleaned_filename=path.name, file_ext=path.suffix,
        file_size_bytes=path.stat().st_size, classification_method="filename_heuristic",
        bpm=None, bpm_source=None, musical_key=None, key_source=None,
        acid_chunk_present=False, duration_seconds=None, sample_rate=None, channels=None, tags=(),
    )
    defaults.update(overrides)
    return repository.upsert_sample(conn, SampleRecord(**defaults), scan_run_id)


def test_fills_bpm_from_caf_beatgrid_and_is_undoable(tmp_path: Path):
    settings = _make_settings(tmp_path)
    settings.unsorted_dir.mkdir(parents=True, exist_ok=True)
    caf = settings.unsorted_dir / "Bumping Disco Guitar.caf"
    caf.write_bytes(build_caf(valid_frames=176400,
                              descriptor={"beat count": 8, "key signature": "E", "key type": "minor"}))

    with repository.open_db(settings.db_path) as conn:
        run = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sid = _insert(conn, run, caf)

        actions = plan_bpm_fills(conn)
        assert len(actions) == 1 and actions[0].new_bpm == 120.0 and actions[0].new_key == "Emin"

        report = apply_bpm_fills(conn, settings, actions)
        assert report.bpm_filled == 1 and report.key_filled == 1

        row = conn.execute("SELECT bpm, bpm_source, musical_key FROM samples WHERE id = ?", (sid,)).fetchone()
        assert row["bpm"] == 120.0
        assert row["bpm_source"] == "embedded_beatgrid"
        assert row["musical_key"] == "Emin"

        undo_scan_run(conn, report.scan_run_id)
        row = conn.execute("SELECT bpm, bpm_source, musical_key FROM samples WHERE id = ?", (sid,)).fetchone()
        assert row["bpm"] is None and row["bpm_source"] is None and row["musical_key"] is None


def test_never_overwrites_an_existing_bpm(tmp_path: Path):
    settings = _make_settings(tmp_path)
    settings.unsorted_dir.mkdir(parents=True, exist_ok=True)
    caf = settings.unsorted_dir / "loop.caf"
    caf.write_bytes(build_caf(valid_frames=176400, descriptor={"beat count": 8}))

    with repository.open_db(settings.db_path) as conn:
        run = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert(conn, run, caf, bpm=97.0, bpm_source="manual")
        assert plan_bpm_fills(conn) == []


def test_acid_beatgrid_wav_filled(tmp_path: Path):
    settings = _make_settings(tmp_path)
    settings.unsorted_dir.mkdir(parents=True, exist_ok=True)
    wav = settings.unsorted_dir / "Sample 02 (Paul Fathy - Funky Baby Love).wav"
    wav.write_bytes(build_minimal_wav(num_frames=int(44100 * 14.542), sample_rate=44100, channels=1))
    riff_chunks.write_acid(wav, riff_chunks.AcidData(
        is_one_shot=True, root_note_set=False, root_note_midi=0,
        num_beats=29, meter_numerator=4, meter_denominator=4, tempo=0.0,
    ))

    with repository.open_db(settings.db_path) as conn:
        run = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sid = _insert(conn, run, wav, acid_chunk_present=True)
        actions = plan_bpm_fills(conn)
        assert len(actions) == 1 and actions[0].new_bpm == 120.0
        apply_bpm_fills(conn, settings, actions)
        row = conn.execute("SELECT bpm, bpm_source FROM samples WHERE id = ?", (sid,)).fetchone()
        assert row["bpm"] == 120.0 and row["bpm_source"] == "embedded_beatgrid"
