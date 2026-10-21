from pathlib import Path

from sample_librarian.audio import riff_chunks, smart_tempo
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.db.repository import SampleRecord
from sample_librarian.pipeline.tempo_remediation import apply_tempo_fixes, plan_tempo_fixes
from sample_librarian.undo import undo_scan_run

from .helpers import write_minimal_wav


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        library_root=tmp_path / "library",
        scan_roots=(tmp_path / "scan",),
        vendor_roots=(),
        audio_extensions=(".wav",),
    )


def _insert_sample(conn, *, current_path: Path, scan_run_id: int, bucket: str = "orphan", **overrides) -> int:
    defaults = dict(
        current_path=str(current_path),
        bucket=bucket,
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
        duration_seconds=4.0,
        sample_rate=44100,
        channels=1,
        tags=(),
    )
    defaults.update(overrides)
    return repository.upsert_sample(conn, SampleRecord(**defaults), scan_run_id)


def test_plan_clears_catalog_number_under_50bpm(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Snare Frank Ricotti Undertone.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id,
            bpm=43.0, bpm_source="filename_regex",
            original_filename="Snare 43 (Frank Ricotti - Undertone).wav",
        )

        plan = plan_tempo_fixes(conn)
        assert len(plan.clear_actions) == 1
        assert plan.clear_actions[0].reason == "under_50bpm"
        assert plan.bake_actions == []


def test_plan_clears_one_shot_pattern_regardless_of_bpm_value(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Cymatics Kick 97.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id,
            bpm=97.0, bpm_source="filename_regex",
            original_filename="Cymatics - House - Starter Pack\\Drums\\Drum One Shots\\Kicks\\Cymatics - Kick 97 - B.wav",
        )

        plan = plan_tempo_fixes(conn)
        assert len(plan.clear_actions) == 1
        assert plan.clear_actions[0].reason == "one_shot_pattern"


def test_plan_leaves_genuine_tempo_tagged_filename_alone(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Groove.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id,
            bpm=140.0, bpm_source="filename_regex", original_filename="BBr_BeatStyleA_140-06.wav",
        )

        plan = plan_tempo_fixes(conn)
        assert plan.clear_actions == []
        assert len(plan.bake_actions) == 1  # doesn't have Smart Tempo yet -- needs baking


def test_plan_skips_bake_when_smart_tempo_already_matches(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Groove.wav")
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=128.0)

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id,
            bpm=128.0, bpm_source="embedded_acid", original_filename="Groove.wav",
        )

        plan = plan_tempo_fixes(conn)
        assert plan.clear_actions == []
        assert plan.bake_actions == []  # already correct, idempotent


def test_plan_never_touches_vendor_bucket(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.vendor_dir / "SomeVendor" / "Snare 43.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id, bucket="vendor",
            bpm=43.0, bpm_source="filename_regex", original_filename="Snare 43.wav",
        )

        plan = plan_tempo_fixes(conn)
        assert plan.clear_actions == []
        assert plan.bake_actions == []


def test_apply_clears_bpm_in_db_and_resets_file_tempo(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Snare.wav")
    riff_chunks.merge_tempo(path, 43.0)
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=43.0)

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id,
            bpm=43.0, bpm_source="filename_regex", original_filename="Snare 43 (Artist).wav",
        )

        plan = plan_tempo_fixes(conn)
        report = apply_tempo_fixes(conn, settings, plan)

        assert report.errors == []
        assert report.cleared_count == 1

        row = conn.execute("SELECT bpm, bpm_source FROM samples WHERE id = ?", (sample_id,)).fetchone()
        assert row["bpm"] is None
        assert row["bpm_source"] is None

        acid = riff_chunks.read_acid(riff_chunks.read_chunks(path))
        assert acid.tempo == 0.0
        assert smart_tempo.read_smart_tempo(path) is None


def test_apply_bakes_smart_tempo_for_genuine_tempo(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Groove.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id, duration_seconds=4.0,
            bpm=140.0, bpm_source="filename_regex", original_filename="BBr_BeatStyleA_140-06.wav",
        )

        plan = plan_tempo_fixes(conn)
        report = apply_tempo_fixes(conn, settings, plan)

        assert report.errors == []
        assert report.baked_count == 1
        result = smart_tempo.read_smart_tempo(path)
        assert result["Tempo"] == [{"t": 0, "conf": -1, "tempo": 140.0}]


def test_undo_restores_db_bpm_and_file_state_for_a_cleared_entry(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Snare.wav")
    riff_chunks.merge_tempo(path, 43.0)
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=43.0)

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        sample_id = _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id,
            bpm=43.0, bpm_source="filename_regex", original_filename="Snare 43 (Artist).wav",
        )

        plan = plan_tempo_fixes(conn)
        report = apply_tempo_fixes(conn, settings, plan)

        undo_report = undo_scan_run(conn, report.scan_run_id)
        assert undo_report.skipped == []

        row = conn.execute("SELECT bpm, bpm_source FROM samples WHERE id = ?", (sample_id,)).fetchone()
        assert row["bpm"] == 43.0
        assert row["bpm_source"] == "filename_regex"

        acid = riff_chunks.read_acid(riff_chunks.read_chunks(path))
        assert acid.tempo == 43.0
        assert smart_tempo.read_smart_tempo(path)["Tempo"] == [{"t": 0, "conf": -1, "tempo": 43.0}]


def test_undo_reverses_a_baked_smart_tempo_entry(tmp_path: Path):
    settings = _make_settings(tmp_path)
    path = write_minimal_wav(settings.unsorted_dir / "Groove.wav")

    with repository.open_db(settings.db_path) as conn:
        scan_run_id = repository.start_scan_run(conn, "initial_sweep", dry_run=False)
        _insert_sample(
            conn, current_path=path, scan_run_id=scan_run_id, duration_seconds=4.0,
            bpm=140.0, bpm_source="filename_regex", original_filename="BBr_BeatStyleA_140-06.wav",
        )

        plan = plan_tempo_fixes(conn)
        report = apply_tempo_fixes(conn, settings, plan)
        assert smart_tempo.read_smart_tempo(path) is not None

        undo_scan_run(conn, report.scan_run_id)
        assert smart_tempo.read_smart_tempo(path) is None
