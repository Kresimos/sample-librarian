"""Filename normalization: junk-character cleanup and a consistent readable
style, keeping the descriptive/creative part of the original name. BPM/key
tokens are stripped rather than reformatted -- that information lives in the
database now, not the filename.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from sample_librarian.audio.filename_regex import strip_recognized_tokens

# A backslash immediately followed by a letter/digit is almost certainly a
# mangled Windows path separator (see clean_filename). A backslash followed
# by punctuation -- most commonly `\"` from an escaped/URL-decoded quote in a
# downloaded title -- is not a path separator and must be left alone.
_MANGLED_PATH_SEPARATOR = re.compile(r"\\(?=[A-Za-z0-9])")
_SEPARATOR_CHARS = re.compile(r"[_\-]+")
_JUNK_CHARS = re.compile(r"[\[\](){}%]")
_WHITESPACE_RUN = re.compile(r"\s+")
_STRIP_EDGE_PUNCT = re.compile(r"^[\s\-_.]+|[\s\-_.]+$")

# Words to keep lowercase when title-casing, unless they're the first word.
_MINOR_WORDS = {"a", "an", "the", "of", "in", "on", "and", "or", "vs"}


def has_mangled_path_separator(stem: str) -> bool:
    """True if stem contains a backslash acting as a mangled Windows path
    separator (see clean_filename) -- used to find already-organized files
    that were cleaned before this handling existed.
    """
    return bool(_MANGLED_PATH_SEPARATOR.search(stem))


def clean_filename(stem: str) -> str:
    """Clean a filename stem (no extension) into a consistent, readable form."""
    # Some sample packs (Cymatics in particular) ship zips built with
    # Windows-style backslash paths; extracted on macOS these backslashes
    # aren't treated as separators, so the whole intended relative path
    # ("Pack\Synth Loops\Supersaw Loops\Foo") lands as one literal flat
    # filename. Take just the real final segment rather than cleaning the
    # mangled full path. (The folder-name context this discards -- "Synth
    # Loops", "Drum One Shots", etc. -- isn't lost: classify() reads this
    # same raw filename independently and already picks those same keywords
    # up as tags, since word-boundary matching treats backslash as a
    # separator too.)
    if _MANGLED_PATH_SEPARATOR.search(stem):
        segments = [s for s in _MANGLED_PATH_SEPARATOR.split(stem) if s]
        if segments:
            stem = segments[-1]

    # Files downloaded from a URL sometimes keep it percent-encoded verbatim
    # (e.g. "Track%20Name" from a "...com/Track%20Name.mp3" link).
    text = unquote(stem)
    text = strip_recognized_tokens(text)
    text = _JUNK_CHARS.sub(" ", text)
    text = _SEPARATOR_CHARS.sub(" ", text)
    text = _WHITESPACE_RUN.sub(" ", text).strip()
    text = _STRIP_EDGE_PUNCT.sub("", text)

    if not text:
        return "untitled"

    words = text.split(" ")
    cleaned_words = [_title_case_word(w, is_first=(i == 0)) for i, w in enumerate(words)]
    return " ".join(cleaned_words)


def _title_case_word(word: str, *, is_first: bool) -> str:
    if not word:
        return word
    # Leave acronym-looking tokens (all caps, 2+ letters, e.g. "FX", "LFO") alone.
    if word.isupper() and len(word) > 1:
        return word
    if not is_first and word.lower() in _MINOR_WORDS:
        return word.lower()
    return word[0].upper() + word[1:].lower()


def make_unique(cleaned_stem: str, existing_stems_lower: set[str]) -> str:
    """Return cleaned_stem, or cleaned_stem with a numeric suffix if it collides
    with something already in existing_stems_lower.

    existing_stems_lower must hold LOWERCASED stems, and comparison here is
    case-insensitive to match. Found the hard way (2026-08-26, a real
    vintage-drum-machine sample collection with the exact same hit names
    spelled in different cases across kit folders, e.g. "Tom1.wav" and
    "TOM1.WAV" -- clean_filename's acronym-preserving title-case keeps them
    differently cased): macOS's default filesystem (case-insensitive,
    case-preserving APFS/HFS+) treats those as the *same* path, so a naive
    case-sensitive set comparison here would let both through as "unique,"
    and the second file's real move would then fail with "destination
    already exists" -- caught safely (mover.py checks before touching
    anything), but still a collision this function is supposed to prevent.
    The returned stem itself keeps its original case -- only the membership
    check is case-insensitive.
    """
    if cleaned_stem.lower() not in existing_stems_lower:
        return cleaned_stem
    n = 2
    while f"{cleaned_stem} {n}".lower() in existing_stems_lower:
        n += 1
    return f"{cleaned_stem} {n}"
