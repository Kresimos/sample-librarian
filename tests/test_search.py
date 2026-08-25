from pathlib import Path

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.db import repository
from sample_librarian.pipeline.initial_sweep import run_apply_sweep

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def _populate(tmp_path: Path) -> tuple:
    scan_dir = tmp_path / "scan"
    write_minimal_wav(scan_dir / "Deep_Kick_95bpm_Amin.wav")
    write_minimal_wav(scan_dir / "Bright_HiHat_140bpm.wav")
    write_minimal_wav(scan_dir / "Ambient_Pad_Cmaj.wav")

    settings = Settings(
        library_root=tmp_path / "library",
        scan_roots=(scan_dir,),
        vendor_roots=(),
        audio_extensions=(".wav",),
    )
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    conn = repository.connect(settings.db_path)
    run_apply_sweep(settings, taxonomy_rules, conn)
    return conn, settings


def test_search_by_free_text_matches_filename(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    results = repository.search_samples(conn, text="kick")
    assert {r["cleaned_filename"] for r in results} == {"Deep Kick.wav"}


def test_search_by_free_text_matches_tag(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    # "drum" is a tag on kick/hihat, not part of either filename
    results = repository.search_samples(conn, text="drum")
    assert {r["cleaned_filename"] for r in results} == {"Deep Kick.wav", "Bright Hihat.wav"}


def test_search_by_sample_type(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    results = repository.search_samples(conn, sample_type="pad")
    assert {r["cleaned_filename"] for r in results} == {"Ambient Pad.wav"}


def test_search_by_bpm_range(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    results = repository.search_samples(conn, bpm_min=100, bpm_max=200)
    assert {r["cleaned_filename"] for r in results} == {"Bright Hihat.wav"}


def test_search_by_key(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    results = repository.search_samples(conn, musical_key="Amin")
    assert {r["cleaned_filename"] for r in results} == {"Deep Kick.wav"}


def test_search_combined_filters(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    results = repository.search_samples(conn, text="drum", bpm_max=100)
    assert {r["cleaned_filename"] for r in results} == {"Deep Kick.wav"}


def test_search_no_filters_returns_everything_active(tmp_path: Path):
    conn, _ = _populate(tmp_path)
    results = repository.search_samples(conn)
    assert len(results) == 3
