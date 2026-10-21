"""Load and validate settings.toml, including the iCloud-path safety guard."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ICLOUD_MARKER = "Mobile Documents"

DEFAULT_AUDIO_EXTENSIONS = (".wav", ".aif", ".aiff", ".aifc", ".caf", ".mp3", ".m4a", ".flac")


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
    # Subtrees never walked at all, even though they sit inside a scan_root --
    # for a folder that holds real files with no sample content (e.g. Apple
    # Music's own library living right next to real samples under ~/Music).
    # Different from vendor_roots: a vendor_roots match still gets touched
    # (symlinked); an excluded_paths match is never visited.
    excluded_paths: tuple[Path, ...] = ()
    # Overrides the default library_root/inbox location -- e.g. pointing it
    # at ~/Downloads so rescan-inbox can treat an existing dumping-ground
    # folder as the inbox instead of a dedicated one inside library_root.
    inbox_dir_override: Path | None = None

    @property
    def vendor_dir(self) -> Path:
        return self.library_root / "vendor"

    @property
    def inbox_dir(self) -> Path:
        if self.inbox_dir_override is not None:
            return self.inbox_dir_override
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
    excluded_paths = tuple(_expand(p) for p in raw.get("excluded_paths", []))
    audio_extensions = tuple(
        ext.lower() for ext in raw.get("audio_extensions", DEFAULT_AUDIO_EXTENSIONS)
    )
    inbox_dir_override = _expand(raw["inbox_dir"]) if "inbox_dir" in raw else None

    return Settings(
        library_root=library_root,
        scan_roots=scan_roots,
        vendor_roots=vendor_roots,
        audio_extensions=audio_extensions,
        excluded_paths=excluded_paths,
        inbox_dir_override=inbox_dir_override,
    )
