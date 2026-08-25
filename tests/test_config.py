from pathlib import Path

import pytest

from sample_librarian.config import UnsafeLibraryRootError, assert_safe_library_root, load_settings


def test_assert_safe_library_root_rejects_icloud():
    icloud_path = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "SampleLibrary"
    with pytest.raises(UnsafeLibraryRootError):
        assert_safe_library_root(icloud_path)


def test_assert_safe_library_root_accepts_local_path():
    assert_safe_library_root(Path.home() / "SampleLibrary")  # must not raise


def test_load_settings_from_toml(tmp_path: Path):
    library_root = tmp_path / "Library"
    scan_root = tmp_path / "Downloads"
    config_file = tmp_path / "settings.toml"
    config_file.write_text(
        f"""
library_root = "{library_root}"
scan_roots = ["{scan_root}"]
vendor_roots = []
audio_extensions = [".wav", ".mp3"]
"""
    )

    settings = load_settings(config_file)

    assert settings.library_root == library_root
    assert settings.scan_roots == (scan_root,)
    assert settings.audio_extensions == (".wav", ".mp3")
    assert settings.unsorted_dir == library_root / "unsorted"


def test_load_settings_rejects_icloud_library_root(tmp_path: Path):
    icloud_style = tmp_path / "Library" / "Mobile Documents" / "SampleLibrary"
    config_file = tmp_path / "settings.toml"
    config_file.write_text(f'library_root = "{icloud_style}"\n')

    with pytest.raises(UnsafeLibraryRootError):
        load_settings(config_file)
