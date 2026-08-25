"""The one shared per-file plan: classify bucket, extract metadata, clean the
name, decide where it would end up. Used identically by the initial sweep and
by future inbox/vendor rescans (see the plan doc), so there's exactly one
place that decides what happens to a file.

This module only ever *plans* -- it never touches the filesystem. Executing a
plan (real move/symlink/metadata write-back) is a separate step (Milestone 4
in the project plan), deliberately kept out of this pure-planning path so
dry-run and apply can never accidentally diverge in what they decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sample_librarian.audio import metadata_extractor
from sample_librarian.classify.classifier import TypeRule, classify
from sample_librarian.config import Settings
from sample_librarian.naming.cleaner import clean_filename, make_unique
from sample_librarian.scanner.bucket_classifier import classify_bucket


@dataclass(frozen=True)
class PlannedAction:
    source_path: Path
    bucket: str  # 'vendor' | 'orphan'
    vendor_name: str | None
    target_path: Path
    cleaned_filename: str
    sample_type: str | None
    tags: tuple[str, ...]
    bpm: float | None
    bpm_source: str | None
    musical_key: str | None
    key_source: str | None
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    acid_chunk_present: bool
    file_size_bytes: int
    would_write_tempo_metadata: bool


def plan_file(
    path: Path,
    settings: Settings,
    taxonomy_rules: list[TypeRule],
    *,
    existing_unsorted_stems: set[str],
) -> PlannedAction:
    decision = classify_bucket(path, settings.vendor_roots)
    metadata = metadata_extractor.extract(path)
    classification = classify(path.name, [p.name for p in path.parents], taxonomy_rules)

    if decision.bucket == "vendor":
        relative = path.relative_to(decision.vendor_root)
        target_path = settings.vendor_dir / decision.vendor_name / relative
        cleaned_filename = path.name
    else:
        cleaned_stem = clean_filename(path.stem)
        unique_stem = make_unique(cleaned_stem, existing_unsorted_stems)
        existing_unsorted_stems.add(unique_stem)
        cleaned_filename = f"{unique_stem}{path.suffix.lower()}"
        target_path = settings.unsorted_dir / cleaned_filename

    would_write_tempo = decision.bucket == "orphan" and metadata.bpm is not None

    return PlannedAction(
        source_path=path,
        bucket=decision.bucket,
        vendor_name=decision.vendor_name,
        target_path=target_path,
        cleaned_filename=cleaned_filename,
        sample_type=classification.sample_type,
        tags=classification.tags,
        bpm=metadata.bpm,
        bpm_source=metadata.bpm_source,
        musical_key=metadata.musical_key,
        key_source=metadata.key_source,
        duration_seconds=metadata.duration_seconds,
        sample_rate=metadata.sample_rate,
        channels=metadata.channels,
        acid_chunk_present=metadata.acid_chunk_present,
        file_size_bytes=path.stat().st_size,
        would_write_tempo_metadata=would_write_tempo,
    )
