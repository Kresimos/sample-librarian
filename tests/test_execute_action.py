from pathlib import Path
from unittest.mock import patch

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import Settings
from sample_librarian.organize.manifest import ManifestWriter, read_manifest
from sample_librarian.pipeline.per_file_pipeline import execute_action, plan_file

from .helpers import write_minimal_wav

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


def test_move_success_with_tempo_write_failure_is_not_reported_as_failed_move(tmp_path: Path):
    """Regression test: a successful move followed by a failing tempo
    write-back must NOT be reported as a failed move -- the file really is
    safely in the library at this point, it just didn't get the bonus tempo
    tag written. Getting this wrong would leave a correctly-organized file
    silently missing from the database.
    """
    scan_dir = tmp_path / "scan"
    source = write_minimal_wav(scan_dir / "Groove_120bpm.wav")
    settings = Settings(
        library_root=tmp_path / "library",
        scan_roots=(scan_dir,),
        vendor_roots=(),
        audio_extensions=(".wav",),
    )
    taxonomy_rules = load_taxonomy(TAXONOMY_PATH)
    action = plan_file(source, settings, taxonomy_rules, existing_unsorted_stems=set())
    assert action.would_write_tempo_metadata is True

    manifest_path = tmp_path / "manifest.jsonl"
    with patch(
        "sample_librarian.pipeline.per_file_pipeline.write_tempo_metadata",
        side_effect=RuntimeError("simulated tempo write failure"),
    ):
        with ManifestWriter(manifest_path) as manifest:
            outcome = execute_action(action, manifest)

    # the move genuinely succeeded -- the file must be treated as such
    assert outcome.success is True
    assert outcome.wrote_tempo_metadata is False
    assert outcome.error is not None and "simulated tempo write failure" in outcome.error
    assert action.target_path.exists()
    assert source.is_symlink()

    entries = list(read_manifest(manifest_path))
    move_entries = [e for e in entries if e.action == "move"]
    tempo_entries = [e for e in entries if e.action == "write_tempo_metadata"]
    assert len(move_entries) == 1 and move_entries[0].success is True
    assert len(tempo_entries) == 1 and tempo_entries[0].success is False
