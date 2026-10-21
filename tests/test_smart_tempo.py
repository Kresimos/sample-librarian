from pathlib import Path

from sample_librarian.audio import riff_chunks, smart_tempo

from .helpers import write_minimal_wav


def test_build_payload_json_beat_grid_matches_tempo_and_duration():
    payload = smart_tempo.build_payload_json(duration_seconds=7.5, tempo=128.0)
    import json

    parsed = json.loads(payload)
    # 128 BPM = 0.46875s/beat; 7.5s fits exactly 16 beats before the end
    beats = parsed["beats"]
    assert len(beats) == 16
    assert beats[0] == {"t": 0, "conf": -1, "onset": 1}
    assert beats[1]["t"] == 0.46875
    assert parsed["Tempo"] == [{"t": 0, "conf": -1, "tempo": 128.0}]
    assert parsed["time_signatures"] == [{"t": 0, "conf": -1, "signature": "4/4"}]
    assert parsed["duration"] == 7.5


def test_payload_nests_initial_and_rec_ctx_matching_real_logic_shape():
    import json

    parsed = json.loads(smart_tempo.build_payload_json(duration_seconds=2.0, tempo=120.0))
    assert "initial" in parsed and "rec_ctx" in parsed
    assert "rec_ctx" in parsed["initial"]
    assert parsed["initial"]["Tempo"] == parsed["Tempo"]
    assert parsed["initial"]["rec_ctx"]["Tempo"] == parsed["Tempo"]


def test_no_beats_when_duration_shorter_than_one_beat():
    import json

    parsed = json.loads(smart_tempo.build_payload_json(duration_seconds=0.1, tempo=60.0))
    assert parsed["beats"] == []


def test_write_then_read_smart_tempo_round_trips_through_a_real_wav_file(tmp_path: Path):
    path = write_minimal_wav(tmp_path / "loop.wav")
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=140.0)

    result = smart_tempo.read_smart_tempo(path)
    assert result is not None
    assert result["Tempo"] == [{"t": 0, "conf": -1, "tempo": 140.0}]
    assert result["duration"] == 4.0

    # other chunks (fmt/data) must survive untouched
    chunks = riff_chunks.read_chunks(path)
    assert riff_chunks.get_chunk(chunks, "fmt ") is not None
    assert riff_chunks.get_chunk(chunks, "data") is not None


def test_write_smart_tempo_replaces_existing_chunk_rather_than_duplicating(tmp_path: Path):
    path = write_minimal_wav(tmp_path / "loop.wav")
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=100.0)
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=140.0)

    chunks = riff_chunks.read_chunks(path)
    resu_chunks = [c for c in chunks if c.chunk_id == "ResU"]
    assert len(resu_chunks) == 1
    assert smart_tempo.read_smart_tempo(path)["Tempo"] == [{"t": 0, "conf": -1, "tempo": 140.0}]


def test_remove_smart_tempo_strips_chunk_and_is_a_no_op_when_absent(tmp_path: Path):
    path = write_minimal_wav(tmp_path / "loop.wav")
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=140.0)
    smart_tempo.remove_smart_tempo(path)
    assert smart_tempo.read_smart_tempo(path) is None

    smart_tempo.remove_smart_tempo(path)  # no-op, must not raise
    assert smart_tempo.read_smart_tempo(path) is None


def test_read_raw_chunk_data_can_restore_an_existing_chunk_verbatim(tmp_path: Path):
    """Undo bookkeeping needs the exact previous bytes, not a re-derived
    value, in case a vendor file already shipped with its own real Smart
    Tempo analysis we must not silently replace with our synthetic one.
    """
    path = write_minimal_wav(tmp_path / "loop.wav")
    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=90.0)
    original_raw = smart_tempo.read_raw_chunk_data(path)

    smart_tempo.write_smart_tempo(path, duration_seconds=4.0, tempo=999.0)
    assert smart_tempo.read_raw_chunk_data(path) != original_raw

    riff_chunks.write_chunk(path, "ResU", original_raw)
    assert smart_tempo.read_smart_tempo(path)["Tempo"] == [{"t": 0, "conf": -1, "tempo": 90.0}]
