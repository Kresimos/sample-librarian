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
# Deliberately NO bare-number fallback (e.g. matching "58" in "Snare Loop
# 58.wav" as a tempo) -- tried this, reverted it (2026-08-25, per Johnny: a
# sample pack numbers loop variations constantly, "Loop 58" is at least as
# likely to mean "the 58th loop" as "58 BPM", and there's no reliable way to
# tell those apart from the filename alone. A missed real tempo is a much
# smaller problem than a wrong one silently corrupting tempo-based search/
# sync -- most vendor content already carries a real embedded tempo tag
# anyway, so this fallback only ever mattered for files that don't.

_NOTE = r"[A-G](?:#|b|s(?:harp)?|flat)?"
_KEY_WORDED = re.compile(
    rf"{_BOUND_BEFORE}({_NOTE})[\s_-]?(min(?:or)?|maj(?:or)?){_BOUND_AFTER}", re.IGNORECASE
)
_KEY_SHORT = re.compile(rf"{_BOUND_BEFORE}({_NOTE})(m)(?=[_\-\s]|$)")

# An explicit literal "key" immediately before the note (e.g. "KeyAmin",
# "Key-Amin", "Key_Amin") is an unambiguous signal, but _BOUND_BEFORE alone
# won't catch the no-separator form "KeyAmin" -- the 'y' right before 'A' is
# a letter, so plain \b-style matching never fires there. These variants
# require the literal "key" (with at most one optional separator after it)
# right before the note, and are tried before the unprefixed patterns since
# they're strictly more specific/confident.
_KEY_PREFIX = r"key[\s_-]?"
_KEY_PREFIXED_WORDED = re.compile(
    rf"{_BOUND_BEFORE}{_KEY_PREFIX}({_NOTE})[\s_-]?(min(?:or)?|maj(?:or)?){_BOUND_AFTER}",
    re.IGNORECASE,
)
_KEY_PREFIXED_SHORT = re.compile(
    rf"{_BOUND_BEFORE}{_KEY_PREFIX}({_NOTE})(m)(?=[_\-\s]|$)", re.IGNORECASE
)

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
    """Return a BPM parsed from the filename, or None if nothing plausible found.

    Only ever matches an explicit "128bpm"/"128-bpm"/"128 bpm" tag -- see the
    comment on _BPM_TAGGED above for why a bare number is never trusted.
    """
    match = _BPM_TAGGED.search(filename)
    if match:
        return float(match.group(1))
    return None


def extract_key(filename: str) -> str | None:
    """Return a normalized key like 'C#min' parsed from the filename, or None."""
    for pattern in (_KEY_PREFIXED_WORDED, _KEY_PREFIXED_SHORT, _KEY_WORDED, _KEY_SHORT):
        match = pattern.search(filename)
        if match:
            root_raw, quality_raw = match.group(1), match.group(2)
            return _normalize_key(root_raw, quality_raw)

    return None


def strip_recognized_tokens(filename: str) -> str:
    """Remove BPM/key substrings this module can recognize, e.g. for building a
    clean display name once that info has been captured as metadata instead.
    """
    result = _BPM_TAGGED.sub(" ", filename)
    result = _KEY_PREFIXED_WORDED.sub(" ", result)
    result = _KEY_PREFIXED_SHORT.sub(" ", result)
    result = _KEY_WORDED.sub(" ", result)
    result = _KEY_SHORT.sub(" ", result)
    return result


def _normalize_key(root_raw: str, quality_raw: str) -> str:
    letter = root_raw[0].upper()
    accidental_raw = root_raw[1:].lower()
    accidental = _ACCIDENTAL_NORMALIZE.get(accidental_raw, "")
    quality = _QUALITY_NORMALIZE[quality_raw.lower()]
    return f"{letter}{accidental}{quality}"
