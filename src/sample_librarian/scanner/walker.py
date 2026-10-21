"""Filesystem walk: find audio files under the configured scan_roots."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator


def iter_audio_files(
    scan_roots: Iterable[Path],
    audio_extensions: Iterable[str],
    *,
    exclude_roots: Iterable[Path] = (),
    min_mtime: float | None = None,
) -> Iterator[Path]:
    """Yield real (non-symlink) audio files under scan_roots.

    Symlinks are skipped deliberately: they're either our own stub left behind
    at an old orphan location, a vendor symlink already in the library, or
    something else's symlink -- none of those should be re-ingested as if
    they were a newly discovered real file.

    exclude_roots is for subtrees that must never be touched at all -- e.g.
    library_root itself (a general sweep must not re-ingest the library's own
    content), or a non-sample subfolder nested inside a scan_root (e.g.
    Apple Music's own library folder living right next to real sample
    content under ~/Music -- settings.excluded_paths). This is different from
    vendor_roots: a vendor_roots match still gets touched, just symlinked
    instead of moved; an exclude_roots match is never walked at all.

    An exclude_roots entry that's an *ancestor* of one of scan_roots doesn't
    apply to that scan_root's own walk -- an explicitly-listed, more specific
    scan_root is a deliberate override of a broader exclusion. E.g. excluding
    ~/Music/Logic wholesale (hundreds of .logicx project bundles' internal
    take/comp audio isn't sample content) while still wanting its Imports/ and
    Bounces/ subfolders scanned, by listing those two as their own scan_roots
    entries alongside the exclusion.

    min_mtime, if given, skips any file last modified at or before that Unix
    timestamp -- lets a caller re-walk a root incrementally (e.g. inbox_rescan
    against a large, mixed-content folder like ~/Downloads) instead of
    reconsidering everything on every run.
    """
    exts = {e.lower() for e in audio_extensions}
    excludes = tuple(exclude_roots)

    for root in scan_roots:
        if not root.exists():
            continue
        applicable_excludes = tuple(ex for ex in excludes if not root.is_relative_to(ex))
        for path in root.rglob("*"):
            if any(path.is_relative_to(ex) for ex in applicable_excludes):
                continue
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if path.suffix.lower() not in exts:
                continue
            if min_mtime is not None and path.stat().st_mtime <= min_mtime:
                continue
            yield path
