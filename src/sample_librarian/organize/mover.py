"""Real move of an orphan-bucket file into the library, with a stub symlink
left behind at the original location. Vendor files never go through here --
see symlinker.py, they're only ever mirrored, never moved.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class MoveError(Exception):
    pass


def move_orphan_file(source: Path, dest: Path, *, leave_stub: bool = True) -> None:
    """Move source to dest (creating parent dirs as needed).

    If leave_stub is True (the default -- used for a general disk sweep), a
    symlink is left at source's original location pointing to dest, so
    anything that hardcoded that path still resolves. leave_stub=False skips
    that (used for inbox_rescan: the inbox is a drop zone nothing else
    references, and leaving stubs there would mean the inbox could never
    actually go back to empty, defeating "empty inbox = nothing pending").

    Cross-volume moves are copy+verify+delete, never a bare rename that could
    half-fail.
    """
    if not source.is_file() or source.is_symlink():
        raise MoveError(f"source is not a real file: {source}")
    if dest.exists() or dest.is_symlink():
        raise MoveError(f"destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    source_size = source.stat().st_size
    same_volume = source.stat().st_dev == _existing_ancestor(dest.parent).stat().st_dev

    if same_volume:
        try:
            source.rename(dest)
        except OSError as exc:  # fall back to copy+verify+delete just in case
            _copy_verify_delete(source, dest, source_size)
            if not dest.exists():
                raise MoveError(f"rename fallback failed for {source} -> {dest}: {exc}") from exc
    else:
        _copy_verify_delete(source, dest, source_size)

    if leave_stub:
        source.symlink_to(dest)


def _copy_verify_delete(source: Path, dest: Path, expected_size: int) -> None:
    shutil.copy2(source, dest)
    actual_size = dest.stat().st_size
    if actual_size != expected_size:
        dest.unlink(missing_ok=True)
        raise MoveError(
            f"copy verification failed for {source} -> {dest}: "
            f"expected {expected_size} bytes, got {actual_size}"
        )
    source.unlink()


def _existing_ancestor(path: Path) -> Path:
    """dest.parent may not exist yet at the point we need its device id."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    raise MoveError(f"no existing ancestor found for {path}")
