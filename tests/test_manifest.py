from pathlib import Path

from sample_librarian.organize.manifest import ManifestEntry, ManifestWriter, manifest_path_for_run, read_manifest


def test_manifest_path_for_run_is_unique_and_descriptive(tmp_path: Path):
    p1 = manifest_path_for_run(tmp_path, 1, "initial_sweep")
    p2 = manifest_path_for_run(tmp_path, 2, "inbox_rescan")
    assert "initial_sweep" in p1.name and "1" in p1.name
    assert "inbox_rescan" in p2.name and "2" in p2.name
    assert p1 != p2


def test_manifest_writer_round_trip(tmp_path: Path):
    path = tmp_path / "logs" / "manifests" / "test.jsonl"
    entry1 = ManifestEntry(
        action="move", source="/a/x.wav", dest="/b/x.wav",
        sample_source_path="/a/x.wav", timestamp="2026-08-25T00:00:00+00:00", success=True,
    )
    entry2 = ManifestEntry(
        action="write_tempo_metadata", source="/b/x.wav", dest="/b/x.wav",
        sample_source_path="/a/x.wav", timestamp="2026-08-25T00:00:01+00:00", success=False,
        error="boom", previous_state={"chunk_existed_before": False, "previous_tempo": None},
    )

    with ManifestWriter(path) as writer:
        writer.record(entry1)
        writer.record(entry2)

    entries = list(read_manifest(path))
    assert entries == [entry1, entry2]


def test_manifest_writer_appends_across_instances(tmp_path: Path):
    path = tmp_path / "manifest.jsonl"
    entry = ManifestEntry(
        action="symlink", source="/a", dest="/b", sample_source_path="/a",
        timestamp="t", success=True,
    )
    with ManifestWriter(path) as w:
        w.record(entry)
    with ManifestWriter(path) as w:
        w.record(entry)

    assert len(list(read_manifest(path))) == 2
