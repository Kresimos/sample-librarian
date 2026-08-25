"""Mirror a vendor file into the library via a symlink. The vendor file
itself is never touched -- no move, no rename, no metadata write.
"""

from __future__ import annotations

from pathlib import Path


class SymlinkError(Exception):
    pass


def symlink_vendor_file(source: Path, dest: Path) -> None:
    """Idempotent: a rescan should be safe to run repeatedly, so a dest that
    already correctly symlinks to source is a silent no-op, not an error.
    Only a genuine conflict (a real file, or a symlink to something else)
    raises.
    """
    if not source.is_file():
        raise SymlinkError(f"source is not a real file: {source}")

    if dest.is_symlink():
        if dest.resolve() == source.resolve():
            return
        raise SymlinkError(f"destination already exists and points elsewhere: {dest}")
    if dest.exists():
        raise SymlinkError(f"destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(source)
