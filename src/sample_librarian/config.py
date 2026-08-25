"""Load and validate settings.toml, including the iCloud-path safety guard."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ICLOUD_MARKER = "Mobile Documents"

DEFAULT_AUDIO_EXTENSIONS = (".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac")


class ConfigError(Exception):
    pass


class UnsafeLibraryRootError(ConfigError):
    """Raised when library_root resolves inside an iCloud-synced location.

    iCloud Drive's on-demand-download/eviction layer has a documented history of
    mishandling symlinks and aliases. This tool's entire safety model (leaving
    vendor files in place, only symlinking) depends on symlinks resolving
    reliably, so refusing to run against an iCloud-synced library_root is a hard
    stop, not a warning.
    """


@dataclass(frozen=True)
class Settings:
    library_root: Path
    scan_roots: tuple[Path, ...]
    vendor_roots: tuple[Path, ...]
    audio_extensions: tuple[str, ...]

    @property
    def vendor_dir(self) -> Path:
        return self.library_root / "vendor"

    @property
    def inbox_dir(self) -> Path:
        return self.library_root / "inbox"

    @property
    def unsorted_dir(self) -> Path:
        return self.library_root / "unsorted"

    @property
    def db_path(self) -> Path:
        return self.library_root / "db" / "library.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.library_root / "logs"


def _expand(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def assert_safe_library_root(library_root: Path) -> None:
    """Refuse to proceed if library_root resolves under iCloud Drive."""
    if ICLOUD_MARKER in library_root.parts:
        raise UnsafeLibraryRootError(
            f"library_root '{library_root}' resolves inside an iCloud-synced "
            f"location (contains '{ICLOUD_MARKER}'). The library must live on "
            "local disk only, symlinks are not reliable under iCloud's "
            "eviction/sync layer. Choose a different library_root in "
            "settings.toml."
        )


def load_settings(config_path: Path) -> Settings:
    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    library_root = _expand(raw["library_root"])
    assert_safe_library_root(library_root)

    scan_roots = tuple(_expand(p) for p in raw.get("scan_roots", []))
    vendor_roots = tuple(_expand(p) for p in raw.get("vendor_roots", []))
    audio_extensions = tuple(
        ext.lower() for ext in raw.get("audio_extensions", DEFAULT_AUDIO_EXTENSIONS)
    )

    return Settings(
        library_root=library_root,
        scan_roots=scan_roots,
        vendor_roots=vendor_roots,
        audio_extensions=audio_extensions,
    )
