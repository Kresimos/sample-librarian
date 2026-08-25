import shutil
from pathlib import Path

import pytest

from sample_librarian.audio import compressed_tags as ct

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mp3_path(tmp_path: Path) -> Path:
    dest = tmp_path / "tiny.mp3"
    shutil.copy(FIXTURES / "tiny.mp3", dest)
    return dest


@pytest.fixture
def flac_path(tmp_path: Path) -> Path:
    dest = tmp_path / "tiny.flac"
    shutil.copy(FIXTURES / "tiny.flac", dest)
    return dest


@pytest.fixture
def m4a_path(tmp_path: Path) -> Path:
    dest = tmp_path / "tiny.m4a"
    shutil.copy(FIXTURES / "tiny.m4a", dest)
    return dest


def test_mp3_no_tags_initially(mp3_path: Path):
    bpm, key = ct.read_tempo_key(mp3_path)
    assert bpm is None
    assert key is None


def test_mp3_write_and_read_tempo_round_trip(mp3_path: Path):
    ct.write_tempo(mp3_path, 128.0)
    bpm, _key = ct.read_tempo_key(mp3_path)
    assert bpm == pytest.approx(128.0)


def test_flac_write_and_read_tempo_round_trip(flac_path: Path):
    ct.write_tempo(flac_path, 174.0)
    bpm, _key = ct.read_tempo_key(flac_path)
    assert bpm == pytest.approx(174.0)


def test_m4a_write_and_read_tempo_round_trip(m4a_path: Path):
    ct.write_tempo(m4a_path, 90.0)
    bpm, _key = ct.read_tempo_key(m4a_path)
    assert bpm == pytest.approx(90.0)


def test_unsupported_format_raises(tmp_path: Path):
    fake = tmp_path / "not_audio.txt"
    fake.write_text("nope")
    with pytest.raises(ct.UnsupportedFormatError):
        ct.read_tempo_key(fake)
