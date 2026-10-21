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
    # Tonal-but-sustained one-shots: an 808/sub/bass hit rings out for many
    # seconds, a pad or plucked note is a single sustained event -- none of
    # these is a loop just for being longer than a drum transient. Their
    # absence from this set is exactly why ~7k sampler notes were mislabeled
    # "loop" on a flat 3s cutoff.
    "808", "bass", "sub", "pad", "pluck", "stab",
})
# Tags whose very meaning is "a loop" -- only consulted as a last resort when
# there's no duration and no explicit keyword. NOT "drumkit": that tag lands
# on every individual hit inside a "Drum Kit" folder, which is the opposite
# of a loop.
_LOOP_LEANING_TAGS = frozenset({"breakbeat"})

# Folder names that mark a sampler-instrument source tree: the files under
# them are single notes chromatically mapped to build an EXS/Sampler/Alchemy
# instrument -- one-shots by construction, however long any single note rings.
_MULTISAMPLE_FOLDER_NAMES = frozenset({
    "quick sampler", "alchemy samples", "sampler instruments",
    "exs factory samples", "autosampled", "ultrabeat samples",
})

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

# Splits camelCase/PascalCase runs into separate words *before* lowercasing
# (case info is gone after that), e.g. "DrumNBass" -> "Drum N Bass" so it
# matches the "drum n bass" keyword the same as a naturally spaced filename
# would, and "BassLine" -> "Bass Line" matches "bass line". Two alternatives:
# lower/digit -> upper (the common case, "drumNbass" -> split before N), and
# upper -> upper+lower (acronym-then-word, "NBass" -> "N Bass" -- needed
# because a single capital standing in for its own word, like the "N" in
# "DrumNBass", is itself all-caps and wouldn't split under the first rule
# alone).
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _normalize(text: str) -> str:
    """Lowercase and turn underscore/dash separators (and camelCase word
    boundaries) into spaces, so word-boundary matching works on filenames
    like 'Heavy_Kick_01.wav' or 'DrumNBass.wav' the way it would on
    'Heavy Kick 01.wav' or 'Drum N Bass.wav'. Without the separator handling,
    \\b never fires inside an underscore-joined run since '_' counts as a
    word character; without the camelCase handling, a concatenated
    multi-keyword name like 'DrumNBass' never breaks into its component words.
    """
    text = _CAMEL_BOUNDARY.sub(" ", text)
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

    loop_type = _classify_loop_type(
        haystack,
        duration_seconds=duration_seconds,
        bpm=bpm,
        matched_tags=matched_tags,
        is_instrument_multisample=_is_instrument_multisample(parent_folder_names),
    )
    if loop_type is not None:
        matched_tags.append(loop_type)

    return ClassificationResult(tags=_dedupe((*matched_tags, *app_foley)))


def _dedupe(tags: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for tag in tags:
        seen.setdefault(tag, None)
    return tuple(seen.keys())


_VENDOR_NAME_SUFFIXES = (".bundle", ".app")
_VENDOR_NAME_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify_vendor_name(vendor_name: str) -> str:
    """Turn a vendor_roots folder name (e.g. "Native Instruments", "Logic Pro
    Library.bundle") into a tag-shaped slug ("native-instruments",
    "logic-pro-library") -- shared by per_file_pipeline.py (new files) and
    retag_remediation.py (backfilling the already-swept library) so both
    produce identical tags for the same vendor_name.
    """
    stem = vendor_name
    for suffix in _VENDOR_NAME_SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return _VENDOR_NAME_SLUG_CHARS.sub("-", stem.lower()).strip("-")


def _is_inside_app_bundle(parent_folder_names: list[str]) -> bool:
    return any(name.lower().endswith(_APP_BUNDLE_SUFFIX) for name in parent_folder_names)


def _is_instrument_multisample(parent_folder_names: list[str]) -> bool:
    lowered = [n.lower() for n in parent_folder_names]
    if any(n in _MULTISAMPLE_FOLDER_NAMES for n in lowered):
        return True
    # A "Samples" folder sitting directly inside Logic's stock library bundle
    # is the EXS/Sampler instrument source tree, as distinct from its sibling
    # "Apple Loops". Likewise "Patches/Instrument" under Logic's shared folder.
    for near, far in zip(lowered, lowered[1:]):
        if near == "samples" and far == "logic pro library.bundle":
            return True
        if near == "instrument" and far == "patches":
            return True
    return False


def _classify_loop_type(
    haystack: str,
    *,
    duration_seconds: float | None,
    bpm: float | None,
    matched_tags: list[str],
    is_instrument_multisample: bool,
) -> str | None:
    # An explicit filename/folder keyword always wins over inference.
    if _ONE_SHOT_KEYWORD.search(haystack):
        return "one-shot"
    if _LOOP_KEYWORD.search(haystack):
        return "loop"

    # Sampler-instrument source material: single mapped notes, never loops.
    if is_instrument_multisample:
        return "one-shot"

    has_real_bpm = bpm is not None and bpm > 0
    leaning_one_shot = any(t in _ONE_SHOT_LEANING_TAGS for t in matched_tags)

    if duration_seconds is not None:
        if has_real_bpm:
            # A genuine tempo is a loop signal -- but a short thing with a
            # tempo tag (a kick from a pack named "... 128bpm") is still a hit.
            return (
                "one-shot"
                if duration_seconds <= DEFAULT_ONE_SHOT_MAX_DURATION_SECONDS
                else "loop"
            )

        threshold = (
            ONE_SHOT_LEANING_MAX_DURATION_SECONDS
            if leaning_one_shot
            else DEFAULT_ONE_SHOT_MAX_DURATION_SECONDS
        )
        if duration_seconds <= threshold:
            return "one-shot"
        if leaning_one_shot:
            # A long 808/sub/pad/kick with no tempo at all is a sustained
            # single hit, not a loop.
            return "one-shot"
        if any(t in _LOOP_LEANING_TAGS for t in matched_tags):
            # "breakbeat" (break / drum loop / groove) is a loop by its very
            # meaning -- keep it even without a detected tempo.
            return "loop"
        # Long, tonal, no tempo, no keyword: genuinely ambiguous between a
        # held note and a loop. Don't guess -- this is what used to wrongly
        # label thousands of sampler notes "loop".
        return None

    # No duration available at all.
    if has_real_bpm:
        return "loop"
    if any(t in _LOOP_LEANING_TAGS for t in matched_tags):
        return "loop"
    if leaning_one_shot:
        return "one-shot"
    return None
