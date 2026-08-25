"""Filesystem walk: find audio files under the configured scan_roots."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator


def iter_audio_files(
    scan_roots: Iterable[Path],
    audio_extensions: Iterable[str],
    *,
    exclude_root: Path | None = None,
) -> Iterator[Path]:
    """Yield real (non-symlink) audio files under scan_roots.

    Symlinks are skipped deliberately: they're either our own stub left behind
    at an old orphan location, a vendor symlink already in the library, or
    something else's symlink -- none of those should be re-ingested as if
    they were a newly discovered real file.
    """
    exts = {e.lower() for e in audio_extensions}

    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if exclude_root is not None and path.is_relative_to(exclude_root):
                continue
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if path.suffix.lower() in exts:
                yield path
