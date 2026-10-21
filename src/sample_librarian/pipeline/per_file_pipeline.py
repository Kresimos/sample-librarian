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

import base64
from dataclasses import dataclass
from pathlib import Path

from sample_librarian.audio import compressed_tags, metadata_extractor, riff_chunks, smart_tempo
from sample_librarian.classify.classifier import TypeRule, classify, slugify_vendor_name
from sample_librarian.config import Settings
from sample_librarian.naming.cleaner import clean_filename, make_unique
from sample_librarian.db.repository import now_iso
from sample_librarian.organize.manifest import ManifestEntry, ManifestWriter
from sample_librarian.organize.mover import move_orphan_file
from sample_librarian.organize.symlinker import symlink_vendor_file
from sample_librarian.scanner.bucket_classifier import classify_bucket

_NO_WRITE_BACK_EXTENSIONS = {".aif", ".aiff", ".aifc", ".caf"}  # only WAV has a chunk writer


@dataclass(frozen=True)
class PlannedAction:
    source_path: Path
    bucket: str  # 'vendor' | 'orphan'
    vendor_name: str | None
    target_path: Path
    cleaned_filename: str
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
    existing_unsorted_stems: set[str],  # must hold LOWERCASED stems -- see make_unique
) -> PlannedAction:
    decision = classify_bucket(path, settings.vendor_roots)
    metadata = metadata_extractor.extract(path)
    classification = classify(
        path.name,
        [p.name for p in path.parents],
        taxonomy_rules,
        duration_seconds=metadata.duration_seconds,
        bpm=metadata.bpm,
    )

    if decision.bucket == "vendor":
        relative = path.relative_to(decision.vendor_root)
        target_path = settings.vendor_dir / decision.vendor_name / relative
        cleaned_filename = path.name
    else:
        cleaned_stem = clean_filename(path.stem)
        unique_stem = make_unique(cleaned_stem, existing_unsorted_stems)
        existing_unsorted_stems.add(unique_stem.lower())
        cleaned_filename = f"{unique_stem}{path.suffix.lower()}"
        target_path = settings.unsorted_dir / cleaned_filename

    would_write_tempo = (
        decision.bucket == "orphan"
        and metadata.bpm is not None
        and path.suffix.lower() not in _NO_WRITE_BACK_EXTENSIONS
        and "song" not in classification.tags  # tempo-conform tagging is for loops, not full tracks
    )

    # Mirror the vendor_name column into the tag system too -- vendor_name is
    # already an authoritative, structured signal (from settings.toml's
    # vendor_roots), not something classify()'s keyword matching could infer
    # on its own, so it's appended here rather than added as a taxonomy rule.
    tags = classification.tags
    if decision.vendor_name is not None:
        tags = (*tags, slugify_vendor_name(decision.vendor_name))

    return PlannedAction(
        source_path=path,
        bucket=decision.bucket,
        vendor_name=decision.vendor_name,
        target_path=target_path,
        cleaned_filename=cleaned_filename,
        tags=tags,
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


@dataclass(frozen=True)
class ExecutionOutcome:
    success: bool
    error: str | None
    wrote_tempo_metadata: bool


def execute_action(
    action: PlannedAction, manifest: ManifestWriter, *, leave_stub_on_move: bool = True
) -> ExecutionOutcome:
    """Perform the real move/symlink (and tempo write-back for orphan files)
    described by a previously-planned action, recording every step to the
    manifest as it happens. leave_stub_on_move=False is used by inbox_rescan,
    see move_orphan_file for why.
    """
    if action.bucket == "vendor":
        try:
            symlink_vendor_file(action.source_path, action.target_path)
        except Exception as exc:  # noqa: BLE001 -- always record failures
            manifest.record(
                ManifestEntry(
                    action="symlink",
                    source=str(action.source_path),
                    dest=str(action.target_path),
                    sample_source_path=str(action.source_path),
                    timestamp=now_iso(),
                    success=False,
                    error=str(exc),
                )
            )
            return ExecutionOutcome(success=False, error=str(exc), wrote_tempo_metadata=False)

        manifest.record(
            ManifestEntry(
                action="symlink",
                source=str(action.source_path),
                dest=str(action.target_path),
                sample_source_path=str(action.source_path),
                timestamp=now_iso(),
                success=True,
            )
        )
        return ExecutionOutcome(success=True, error=None, wrote_tempo_metadata=False)

    try:
        move_orphan_file(action.source_path, action.target_path, leave_stub=leave_stub_on_move)
    except Exception as exc:  # noqa: BLE001 -- always record failures
        manifest.record(
            ManifestEntry(
                action="move",
                source=str(action.source_path),
                dest=str(action.target_path),
                sample_source_path=str(action.source_path),
                timestamp=now_iso(),
                success=False,
                error=str(exc),
            )
        )
        return ExecutionOutcome(success=False, error=str(exc), wrote_tempo_metadata=False)

    manifest.record(
        ManifestEntry(
            action="move",
            source=str(action.source_path),
            dest=str(action.target_path),
            sample_source_path=str(action.source_path),
            timestamp=now_iso(),
            success=True,
        )
    )

    # The move already fully succeeded at this point -- the file is safely in
    # the library. A failure writing tempo metadata back is a lesser problem
    # (a bonus feature didn't apply) and must NOT be reported as a failed
    # move, or the file would end up correctly organized on disk but missing
    # from the database entirely.
    wrote_tempo = False
    tempo_error: str | None = None
    if action.would_write_tempo_metadata:
        try:
            previous_state = read_previous_tempo_state(action.target_path)
            write_tempo_metadata(action.target_path, action.bpm, action.duration_seconds)
            wrote_tempo = True
            manifest.record(
                ManifestEntry(
                    action="write_tempo_metadata",
                    source=str(action.target_path),
                    dest=str(action.target_path),
                    sample_source_path=str(action.source_path),
                    timestamp=now_iso(),
                    success=True,
                    previous_state=previous_state,
                )
            )
        except Exception as exc:  # noqa: BLE001 -- always record failures
            tempo_error = str(exc)
            manifest.record(
                ManifestEntry(
                    action="write_tempo_metadata",
                    source=str(action.target_path),
                    dest=str(action.target_path),
                    sample_source_path=str(action.source_path),
                    timestamp=now_iso(),
                    success=False,
                    error=tempo_error,
                )
            )

    return ExecutionOutcome(success=True, error=tempo_error, wrote_tempo_metadata=wrote_tempo)


def read_previous_tempo_state(target_path: Path) -> dict:
    ext = target_path.suffix.lower()
    if ext == ".wav":
        acid = riff_chunks.read_acid(riff_chunks.read_chunks(target_path))
        smart_tempo_raw = smart_tempo.read_raw_chunk_data(target_path)
        return {
            "chunk_existed_before": acid is not None,
            "previous_tempo": acid.tempo if acid is not None else None,
            # Smart Tempo ('ResU') is tracked independently of ACID -- a
            # vendor file could already carry one, the other, both, or
            # neither, and undo must restore each correctly regardless of
            # what the other one was doing.
            "smart_tempo_existed_before": smart_tempo_raw is not None,
            "smart_tempo_previous_raw_b64": (
                base64.b64encode(smart_tempo_raw).decode("ascii") if smart_tempo_raw is not None else None
            ),
        }
    if ext in (".mp3", ".m4a", ".flac"):
        previous_bpm, _key = compressed_tags.read_tempo_key(target_path)
        return {"chunk_existed_before": previous_bpm is not None, "previous_tempo": previous_bpm}
    return {"chunk_existed_before": False, "previous_tempo": None}


def write_tempo_metadata(target_path: Path, bpm: float, duration_seconds: float | None = None) -> None:
    ext = target_path.suffix.lower()
    if ext == ".wav":
        riff_chunks.merge_tempo(target_path, bpm)
        # Also write Logic Pro's own "Smart Tempo" chunk, confirmed
        # empirically (2026-08-25) to be what actually drives Logic's "File
        # Tempo" field on a plain drag -- Logic never reads the ACID chunk
        # above for that. Needs duration, which should always be known for a
        # WAV by this point; skip gracefully if not rather than write a
        # nonsensical beat grid.
        if duration_seconds is not None:
            smart_tempo.write_smart_tempo(target_path, duration_seconds=duration_seconds, tempo=bpm)
    elif ext in (".mp3", ".m4a", ".flac"):
        compressed_tags.write_tempo(target_path, bpm)
    # AIFF has no writer yet -- would_write_tempo_metadata is already False for it


def undo_tempo_metadata(target_path: Path, previous_state: dict) -> None:
    """Restore a file's tempo metadata to what it was before write_tempo_metadata
    ran, using the previous_state captured in that manifest entry. WAV files
    carry two independent pieces (ACID and Smart Tempo/'ResU') restored
    separately, since either could have existed before while the other didn't.
    """
    ext = target_path.suffix.lower()

    if previous_state.get("chunk_existed_before"):
        write_tempo_metadata(target_path, previous_state["previous_tempo"])
    elif ext == ".wav":
        riff_chunks.remove_acid(target_path)
    elif ext in (".mp3", ".m4a", ".flac"):
        compressed_tags.remove_tempo(target_path)

    if ext == ".wav":
        if previous_state.get("smart_tempo_existed_before"):
            raw = base64.b64decode(previous_state["smart_tempo_previous_raw_b64"])
            riff_chunks.write_chunk(target_path, "ResU", raw)
        else:
            smart_tempo.remove_smart_tempo(target_path)
