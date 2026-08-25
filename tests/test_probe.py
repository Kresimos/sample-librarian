from pathlib import Path

import pytest

from sample_librarian.audio import probe as pr

FIXTURES = Path(__file__).parent / "fixtures"


def test_probe_mp3():
    result = pr.probe(FIXTURES / "tiny.mp3")
    assert result.sample_rate == 44100
    assert result.channels == 1
    assert result.duration_seconds == pytest.approx(0.3, abs=0.05)


def test_probe_flac():
    result = pr.probe(FIXTURES / "tiny.flac")
    assert result.sample_rate == 44100
    assert result.channels == 1
    assert result.duration_seconds == pytest.approx(0.3, abs=0.05)


def test_probe_m4a():
    result = pr.probe(FIXTURES / "tiny.m4a")
    assert result.sample_rate == 44100
    assert result.channels == 1
    assert result.duration_seconds == pytest.approx(0.3, abs=0.05)
