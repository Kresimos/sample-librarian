"""Filename normalization: junk-character cleanup and a consistent readable
style, keeping the descriptive/creative part of the original name. BPM/key
tokens are stripped rather than reformatted -- that information lives in the
database now, not the filename.
"""

from __future__ import annotations

import re

from sample_librarian.audio.filename_regex import strip_recognized_tokens

_SEPARATOR_CHARS = re.compile(r"[_\-]+")
_JUNK_CHARS = re.compile(r"[\[\](){}]")
_WHITESPACE_RUN = re.compile(r"\s+")
_STRIP_EDGE_PUNCT = re.compile(r"^[\s\-_.]+|[\s\-_.]+$")

# Words to keep lowercase when title-casing, unless they're the first word.
_MINOR_WORDS = {"a", "an", "the", "of", "in", "on", "and", "or", "vs"}


def clean_filename(stem: str) -> str:
    """Clean a filename stem (no extension) into a consistent, readable form."""
    text = strip_recognized_tokens(stem)
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


def make_unique(cleaned_stem: str, existing_stems: set[str]) -> str:
    """Return cleaned_stem, or cleaned_stem with a numeric suffix if it collides
    with something already in existing_stems.
    """
    if cleaned_stem not in existing_stems:
        return cleaned_stem
    n = 2
    while f"{cleaned_stem} {n}" in existing_stems:
        n += 1
    return f"{cleaned_stem} {n}"
