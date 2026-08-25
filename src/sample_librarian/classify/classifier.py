"""Filename/folder-path keyword classification against config/taxonomy.yaml,
plus duration-based song detection and loop-vs-one-shot tagging.

Everything a file gets labeled with -- what instrument/drum it is, whether
it's a loop or one-shot, whether it's a full song, where it came from -- is
just a tag in one flat set. There's no separate "type" field: a file can
match several taxonomy rules at once (a "Guitar Riff" is both `guitar` and
`melody`), which wasn't possible under the old first-match-wins design.

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
# get tagged "song" instead of going through keyword classification at all
# (a song called "Kick Drum Solo" shouldn't get tagged "kick").
DEFAULT_SONG_DURATION_THRESHOLD_SECONDS = 90.0

# Anything this short or shorter is almost certainly a single hit, not a loop.
DEFAULT_ONE_SHOT_MAX_DURATION_SECONDS = 3.0

# Drum-type one-shots specifically can legitimately run longer than that --
# a kick layered with a sub-bass tail, or a hihat/percussion hit with a long
# decay, commonly stretches past 3s and is still just one hit, not a loop.
# Found empirically: a real "Kick_3_Sub_RedLine.wav" in the wild is 5.9s.
ONE_SHOT_LEANING_MAX_DURATION_SECONDS = 8.0

# Tag names (from taxonomy.yaml's rule names/tags) that lean strongly one way
# when duration is unknown and no filename keyword settled it.
_ONE_SHOT_LEANING_TAGS = frozenset({
    "kick", "snare", "rimshot", "clap", "hihat", "cymbal", "tom", "percussion",
    "shaker", "tambourine", "conga", "bongo", "cowbell", "clave", "triangle",
    "woodblock", "timbale", "djembe", "impact",
})
_LOOP_LEANING_TAGS = frozenset({"breakbeat", "drumkit"})

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
    name: str  # the rule's own key in taxonomy.yaml, e.g. "kick" -- itself just a tag now
    tags: tuple[str, ...]
    patterns: tuple[re.Pattern, ...]


@dataclass(frozen=True)
class ClassificationResult:
    tags: tuple[str, ...]


def load_taxonomy(taxonomy_path: Path) -> list[TypeRule]:
    with taxonomy_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    rules: list[TypeRule] = []
    for name, definition in raw.get("types", {}).items():
        keywords = definition.get("keywords", [])
        tags = tuple(definition.get("tags", []))
        patterns = tuple(_compile_keyword(k) for k in keywords)
        rules.append(TypeRule(name=name, tags=tags, patterns=patterns))
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
        # classification and loop/one-shot tagging don't apply to it.
        return ClassificationResult(tags=_dedupe(("song", *app_foley)))

    matched_tags: list[str] = []
    for rule in rules:
        if any(p.search(haystack) for p in rule.patterns):
            matched_tags.append(rule.name)
            matched_tags.extend(rule.tags)

    loop_type = _classify_loop_type(haystack, duration_seconds=duration_seconds, matched_tags=matched_tags)
    if loop_type is not None:
        matched_tags.append(loop_type)

    return ClassificationResult(tags=_dedupe((*matched_tags, *app_foley)))


def _dedupe(tags: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for tag in tags:
        seen.setdefault(tag, None)
    return tuple(seen.keys())


def _is_inside_app_bundle(parent_folder_names: list[str]) -> bool:
    return any(name.lower().endswith(_APP_BUNDLE_SUFFIX) for name in parent_folder_names)


def _classify_loop_type(
    haystack: str, *, duration_seconds: float | None, matched_tags: list[str]
) -> str | None:
    # An explicit filename keyword always wins over inference.
    if _ONE_SHOT_KEYWORD.search(haystack):
        return "one-shot"
    if _LOOP_KEYWORD.search(haystack):
        return "loop"

    if duration_seconds is not None:
        threshold = (
            ONE_SHOT_LEANING_MAX_DURATION_SECONDS
            if any(t in _ONE_SHOT_LEANING_TAGS for t in matched_tags)
            else DEFAULT_ONE_SHOT_MAX_DURATION_SECONDS
        )
        if duration_seconds <= threshold:
            return "one-shot"
        # Longer than a one-shot and (by the time we get here) already known
        # to be shorter than the song threshold -- almost certainly a loop.
        return "loop"

    # No duration available at all: fall back to what the matched tags usually mean.
    if any(t in _LOOP_LEANING_TAGS for t in matched_tags):
        return "loop"
    if any(t in _ONE_SHOT_LEANING_TAGS for t in matched_tags):
        return "one-shot"
    return None
