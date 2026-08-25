"""Filename/folder-path keyword classification against config/taxonomy.yaml,
plus duration-based song detection and loop-vs-one-shot labeling.

v1 only -- audio-content/waveform analysis is deliberately deferred (see
samples.classification_method in schema.sql, which leaves room for it later
without a migration).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# A full song download runs a couple of minutes at minimum; nothing that's
# actually a sample/loop/one-shot realistically does. Files longer than this
# get sample_type="song" instead of going through keyword classification at
# all (a song called "Kick Drum Solo" shouldn't get tagged as a kick sample).
DEFAULT_SONG_DURATION_THRESHOLD_SECONDS = 90.0

# Anything this short or shorter is almost certainly a single hit, not a loop.
DEFAULT_ONE_SHOT_MAX_DURATION_SECONDS = 3.0

# Drum-type one-shots specifically can legitimately run longer than that --
# a kick layered with a sub-bass tail, or a hihat/percussion hit with a long
# decay, commonly stretches past 3s and is still just one hit, not a loop.
# Found empirically: a real "Kick_3_Sub_RedLine.wav" in the wild is 5.9s.
ONE_SHOT_LEANING_MAX_DURATION_SECONDS = 8.0

# Sample types that lean strongly one way when duration is unknown and no
# filename keyword settled it.
_ONE_SHOT_LEANING_TYPES = frozenset({"kick", "snare", "clap", "hihat", "tom", "percussion"})
_LOOP_LEANING_TYPES = frozenset({"breakbeat"})

_LOOP_KEYWORD = re.compile(r"\bloops?\b")
_ONE_SHOT_KEYWORD = re.compile(r"\b(?:one ?shots?|1shots?)\b")

# A .app bundle is just a directory on disk -- the scanner walks into it like
# any other folder, so its internal UI/notification sounds show up as
# "samples" too. Rather than exclude them, tag them: a system alert or
# notification chime can be a genuinely fun, weird sound to sample with.
_APP_BUNDLE_SUFFIX = ".app"
_APP_FOLEY_TAG = "app-foley"


@dataclass(frozen=True)
class TypeRule:
    sample_type: str
    tags: tuple[str, ...]
    patterns: tuple[re.Pattern, ...]


@dataclass(frozen=True)
class ClassificationResult:
    sample_type: str | None
    tags: tuple[str, ...]
    loop_type: str | None = None  # 'loop' | 'one-shot' | None (indeterminate, or n/a for a song)


def load_taxonomy(taxonomy_path: Path) -> list[TypeRule]:
    with taxonomy_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    rules: list[TypeRule] = []
    for sample_type, definition in raw.get("types", {}).items():
        keywords = definition.get("keywords", [])
        tags = tuple(definition.get("tags", []))
        patterns = tuple(_compile_keyword(k) for k in keywords)
        rules.append(TypeRule(sample_type=sample_type, tags=tags, patterns=patterns))
    return rules


_SEPARATOR_CHARS = re.compile(r"[_\-]+")


def _normalize(text: str) -> str:
    """Lowercase and turn underscore/dash separators into spaces, so word-boundary
    matching works on filenames like 'Heavy_Kick_01.wav' the way it would on
    'Heavy Kick 01.wav'. Without this, \\b never fires inside an underscore-joined
    run since '_' counts as a word character.
    """
    return _SEPARATOR_CHARS.sub(" ", text.lower())


def _compile_keyword(keyword: str) -> re.Pattern:
    escaped = re.escape(_normalize(keyword))
    # Tolerate a simple trailing plural (e.g. "breakbeats" matching "breakbeat")
    # without opening up matches for arbitrary suffixes.
    return re.compile(rf"\b{escaped}s?\b")


def classify(
    filename: str,
    parent_folder_names: list[str],
    rules: list[TypeRule],
    *,
    duration_seconds: float | None = None,
    bpm: float | None = None,
    song_duration_threshold_seconds: float = DEFAULT_SONG_DURATION_THRESHOLD_SECONDS,
) -> ClassificationResult:
    haystack = _normalize(" ".join([filename, *parent_folder_names]))
    app_foley = (_APP_FOLEY_TAG,) if _is_inside_app_bundle(parent_folder_names) else ()

    if duration_seconds is not None and duration_seconds > song_duration_threshold_seconds:
        # Long enough that it's a full track, not a sample -- keyword
        # classification and loop/one-shot labeling don't apply to it.
        return ClassificationResult(sample_type="song", tags=app_foley, loop_type=None)

    sample_type: str | None = None
    tags: tuple[str, ...] = ()
    for rule in rules:
        if any(p.search(haystack) for p in rule.patterns):
            sample_type, tags = rule.sample_type, rule.tags
            break

    loop_type = _classify_loop_type(
        haystack, duration_seconds=duration_seconds, sample_type=sample_type
    )

    return ClassificationResult(sample_type=sample_type, tags=tags + app_foley, loop_type=loop_type)


def _is_inside_app_bundle(parent_folder_names: list[str]) -> bool:
    return any(name.lower().endswith(_APP_BUNDLE_SUFFIX) for name in parent_folder_names)


def _classify_loop_type(
    haystack: str, *, duration_seconds: float | None, sample_type: str | None
) -> str | None:
    # An explicit filename keyword always wins over inference.
    if _ONE_SHOT_KEYWORD.search(haystack):
        return "one-shot"
    if _LOOP_KEYWORD.search(haystack):
        return "loop"

    if duration_seconds is not None:
        threshold = (
            ONE_SHOT_LEANING_MAX_DURATION_SECONDS
            if sample_type in _ONE_SHOT_LEANING_TYPES
            else DEFAULT_ONE_SHOT_MAX_DURATION_SECONDS
        )
        if duration_seconds <= threshold:
            return "one-shot"
        # Longer than a one-shot and (by the time we get here) already known
        # to be shorter than the song threshold -- almost certainly a loop.
        return "loop"

    # No duration available at all: fall back to what the sample type usually is.
    if sample_type in _LOOP_LEANING_TYPES:
        return "loop"
    if sample_type in _ONE_SHOT_LEANING_TYPES:
        return "one-shot"
    return None
