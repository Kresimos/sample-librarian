# sample-librarian

A two-stage tool for taming a large, scattered sample library.

1. **Python pipeline (`samplelib`)** scans messy folders (Downloads, Desktop, vendor packs) and organises samples into a tag-based library without breaking plugins that depend on hardcoded paths. Files are moved into a clean structure and the original location is replaced by a symlink. Every command is dry-run by default (pass `--apply` to act) and every operation is recorded so it can be undone.
2. **SwiftUI macOS app** to browse, search and audition the resulting library, and drag samples straight into Logic Pro.

## Features

- Dry-run-by-default, undoable file operations (`samplelib undo`), with a manifest of every move
- Rule-based classification from a YAML taxonomy (instrument, genre, one-shot vs loop, and so on), plus BPM and key extraction from filenames and audio metadata (RIFF, AIFF/CAF, ID3/MP4/FLAC tags)
- Remediation commands for mangled names, wrong tempos, wrong BPMs and stale tags
- Logic Pro Smart Tempo chunk writing, so tempo-aware loops follow the project tempo
- Composable search: every typed word becomes a filter chip, with negation (`!kick`), `bpm` tokens (`170bpm`, `160-170bpm`), key tokens (`Amin`, `F#min`, bare `A`) and tag synonyms
- Keyboard-driven browsing, autoplay on selection, and ratings
- Frequency-coloured waveforms in the preview panel
- Drag and drop from the app into Logic Pro

## Setup

Requires macOS, Python 3.11+, `ffmpeg` (for `ffprobe`), and Swift 5.9+ / Xcode for the app.

```sh
brew install ffmpeg
python3 -m venv ~/.venvs/sample-librarian
~/.venvs/sample-librarian/bin/pip install -e ".[dev]"
cp config/settings.example.toml config/settings.toml   # edit to taste (gitignored)
```

The library itself (`library_root`) must live on local disk, not iCloud. The config loader refuses to run otherwise.

## Usage

```sh
samplelib init
samplelib scan                 # dry run
samplelib scan --apply
samplelib search kick 170bpm
samplelib undo
```

Run `samplelib --help` for the full command list.

## Build and test

```sh
# Python
~/.venvs/sample-librarian/bin/pytest

# Swift app
cd swift-app
swift build
swift test
./build_app_bundle.sh          # produces .build/SampleLibrarian.app
```

## Architecture

```
src/sample_librarian/
  scanner/     directory walking, bucket classification
  audio/       probing, RIFF/AIFF/CAF chunks, Smart Tempo, tag readers, filename parsing
  classify/    taxonomy-driven classifier (config/taxonomy.yaml)
  naming/      filename cleaning
  organize/    mover, symlinker, manifest (basis for undo)
  pipeline/    initial sweep, inbox/vendor rescans, remediation passes
  db/          SQLite schema and repository
  cli.py       click entry point
swift-app/
  SampleLibrarianCore/   DB access, search-token parser, waveform generation (unit tested)
  SampleLibrarianApp/    SwiftUI views, audio playback, drag and drop
```

The two stages share a SQLite database (`library.sqlite3`), which the Python pipeline writes and the app reads (WAL-aware, no external Swift dependencies).
