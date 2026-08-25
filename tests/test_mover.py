from pathlib import Path

import pytest

from sample_librarian.organize.mover import MoveError, move_orphan_file

from .helpers import write_minimal_wav


def test_move_orphan_file_moves_and_leaves_stub_symlink(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "source" / "Kick.wav")
    dest = tmp_path / "library" / "unsorted" / "Kick.wav"
    original_bytes = source.read_bytes()

    move_orphan_file(source, dest)

    assert dest.exists()
    assert dest.read_bytes() == original_bytes
    assert source.is_symlink()
    assert source.resolve() == dest.resolve()
    # reading through the stub must transparently reach the real file
    assert source.read_bytes() == original_bytes


def test_move_orphan_file_rejects_existing_destination(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "source" / "Kick.wav")
    dest = write_minimal_wav(tmp_path / "library" / "unsorted" / "Kick.wav")

    with pytest.raises(MoveError):
        move_orphan_file(source, dest)

    assert source.exists()  # source untouched on failure


def test_move_orphan_file_leave_stub_false_leaves_nothing_behind(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "inbox" / "New.wav")
    dest = tmp_path / "library" / "unsorted" / "New.wav"

    move_orphan_file(source, dest, leave_stub=False)

    assert dest.exists()
    assert not source.exists()
    assert not source.is_symlink()
    assert list(source.parent.iterdir()) == []


def test_move_orphan_file_rejects_symlink_source(tmp_path: Path):
    real = write_minimal_wav(tmp_path / "real.wav")
    link = tmp_path / "link.wav"
    link.symlink_to(real)
    dest = tmp_path / "library" / "link.wav"

    with pytest.raises(MoveError):
        move_orphan_file(link, dest)
