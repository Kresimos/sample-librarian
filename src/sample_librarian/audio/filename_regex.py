"""Fallback BPM/key extraction from filenames, used when a file has no usable
embedded metadata. Embedded metadata (ACID chunk, ID3 tags) is always preferred
over this when present -- filenames are the less reliable source.
"""

from __future__ import annotations

import re

# Sample filenames commonly use '_'/'-' as word separators (e.g. "120bpm_Cmin"),
# but those are \w characters, so plain \b never fires between them and an
# adjacent token. These lookarounds treat only letters/digits as "connected",
# so underscore/dash/space/punctuation/start/end all count as valid boundaries.
_BOUND_BEFORE = r"(?<![A-Za-z0-9])"
_BOUND_AFTER = r"(?![A-Za-z0-9])"

_BPM_TAGGED = re.compile(
    rf"(?<!\d)(\d{{2,3}})\s*[-_]?\s*bpm{_BOUND_AFTER}", re.IGNORECASE
)
_BPM_BARE = re.compile(r"(?:^|[_\-\s])(\d{2,3})(?:$|[_\-\s])")

_MIN_BPM = 40
_MAX_BPM = 220

_NOTE = r"[A-G](?:#|b|s(?:harp)?|flat)?"
_KEY_WORDED = re.compile(
    rf"{_BOUND_BEFORE}({_NOTE})[\s_-]?(min(?:or)?|maj(?:or)?){_BOUND_AFTER}", re.IGNORECASE
)
_KEY_SHORT = re.compile(rf"{_BOUND_BEFORE}({_NOTE})(m)(?=[_\-\s]|$)")

_ACCIDENTAL_NORMALIZE = {
    "#": "#",
    "sharp": "#",
    "s": "#",
    "b": "b",
    "flat": "b",
}
_QUALITY_NORMALIZE = {
    "min": "min",
    "minor": "min",
    "maj": "maj",
    "major": "maj",
    "m": "min",
}


def extract_bpm(filename: str) -> float | None:
    """Return a BPM parsed from the filename, or None if nothing plausible found."""
    match = _BPM_TAGGED.search(filename)
    if match:
        return float(match.group(1))

    for match in _BPM_BARE.finditer(filename):
        value = int(match.group(1))
        if _MIN_BPM <= value <= _MAX_BPM:
            return float(value)

    return None


def extract_key(filename: str) -> str | None:
    """Return a normalized key like 'C#min' parsed from the filename, or None."""
    match = _KEY_WORDED.search(filename)
    if match:
        root_raw, quality_raw = match.group(1), match.group(2)
        return _normalize_key(root_raw, quality_raw)

    match = _KEY_SHORT.search(filename)
    if match:
        root_raw, quality_raw = match.group(1), match.group(2)
        return _normalize_key(root_raw, quality_raw)

    return None


def strip_recognized_tokens(filename: str) -> str:
    """Remove BPM/key substrings this module can recognize, e.g. for building a
    clean display name once that info has been captured as metadata instead.
    """
    result = _BPM_TAGGED.sub(" ", filename)
    result = _KEY_WORDED.sub(" ", result)
    result = _KEY_SHORT.sub(" ", result)
    # Only strip a bare number if it's plausibly the BPM we'd have extracted,
    # otherwise this would eat catalog numbers, take counts, etc.
    if extract_bpm(filename) is not None and _BPM_TAGGED.search(filename) is None:
        result = _BPM_BARE.sub(" ", result)
    return result


def _normalize_key(root_raw: str, quality_raw: str) -> str:
    letter = root_raw[0].upper()
    accidental_raw = root_raw[1:].lower()
    accidental = _ACCIDENTAL_NORMALIZE.get(accidental_raw, "")
    quality = _QUALITY_NORMALIZE[quality_raw.lower()]
    return f"{letter}{accidental}{quality}"
