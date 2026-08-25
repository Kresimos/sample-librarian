"""Vendor vs orphan bucket decision.

Deliberately not automatic: a file is 'vendor' only if it falls under a path
the user explicitly listed in vendor_roots. False positives here are cheap
(over-protecting a file that was actually fine to move); false negatives are
the exact failure this whole tool is designed to avoid (moving something a
plugin depends on). Heuristic auto-detection is not used to make this call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BucketDecision:
    bucket: str  # 'vendor' | 'orphan'
    vendor_name: str | None
    vendor_root: Path | None


def classify_bucket(path: Path, vendor_roots: Iterable[Path]) -> BucketDecision:
    for root in vendor_roots:
        if path.is_relative_to(root):
            return BucketDecision(bucket="vendor", vendor_name=root.name, vendor_root=root)
    return BucketDecision(bucket="orphan", vendor_name=None, vendor_root=None)
