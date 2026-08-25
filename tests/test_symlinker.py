from pathlib import Path

import pytest

from sample_librarian.organize.symlinker import SymlinkError, symlink_vendor_file

from .helpers import write_minimal_wav


def test_symlink_vendor_file_creates_link_and_leaves_source_untouched(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "vendor" / "Splice" / "kick.wav")
    dest = tmp_path / "library" / "vendor" / "Splice" / "kick.wav"
    original_bytes = source.read_bytes()

    symlink_vendor_file(source, dest)

    assert dest.is_symlink()
    assert dest.resolve() == source.resolve()
    assert dest.read_bytes() == original_bytes
    assert source.exists() and not source.is_symlink()  # vendor file itself never touched


def test_symlink_vendor_file_rejects_existing_real_file_destination(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "vendor" / "kick.wav")
    dest = write_minimal_wav(tmp_path / "library" / "kick.wav")

    with pytest.raises(SymlinkError):
        symlink_vendor_file(source, dest)


def test_symlink_vendor_file_is_idempotent_for_already_correct_link(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "vendor" / "kick.wav")
    dest = tmp_path / "library" / "kick.wav"

    symlink_vendor_file(source, dest)
    symlink_vendor_file(source, dest)  # must not raise

    assert dest.resolve() == source.resolve()


def test_symlink_vendor_file_rejects_destination_pointing_elsewhere(tmp_path: Path):
    source = write_minimal_wav(tmp_path / "vendor" / "kick.wav")
    other = write_minimal_wav(tmp_path / "other.wav")
    dest = tmp_path / "library" / "kick.wav"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(other)

    with pytest.raises(SymlinkError):
        symlink_vendor_file(source, dest)
