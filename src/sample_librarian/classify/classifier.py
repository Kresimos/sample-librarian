"""Filename/folder-path keyword classification against config/taxonomy.yaml.

v1 only -- audio-content/waveform analysis is deliberately deferred (see
samples.classification_method in schema.sql, which leaves room for it later
without a migration).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TypeRule:
    sample_type: str
    tags: tuple[str, ...]
    patterns: tuple[re.Pattern, ...]


@dataclass(frozen=True)
class ClassificationResult:
    sample_type: str | None
    tags: tuple[str, ...]


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


def classify(filename: str, parent_folder_names: list[str], rules: list[TypeRule]) -> ClassificationResult:
    haystack = _normalize(" ".join([filename, *parent_folder_names]))

    for rule in rules:
        if any(p.search(haystack) for p in rule.patterns):
            return ClassificationResult(sample_type=rule.sample_type, tags=rule.tags)

    return ClassificationResult(sample_type=None, tags=())
