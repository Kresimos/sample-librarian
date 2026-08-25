# sample-librarian

Two-stage tool: organize a scattered sample/loop collection into one library without
breaking plugins that depend on hardcoded paths, then browse/search it and drag samples
into Logic Pro from a fast standalone app.

Full design/rationale: `~/.claude/plans/yep-that-s-a-good-compressed-papert.md` and the
`architecture-decisions` project memory.

## Two locations, do not conflate

- This repo (code only) lives under iCloud (`~/Library/Mobile Documents/.../Projects/sample-librarian`) — fine, it's just source.
- The actual library data (real files, `library.sqlite3`, symlink targets) lives at `~/SampleLibrary`, **local disk only, never iCloud**. `config.py` refuses to run if `library_root` resolves under `~/Library/Mobile Documents/`.

## Environment

- Python: Homebrew Python 3.11+ (`/opt/homebrew/bin/python3`).
- **Venv exception**: unlike this user's usual "no venv for single-script projects" convention, this repo uses a real venv because it does destructive filesystem operations on irreplaceable files — pinned, reproducible dependencies matter here.
- **Venv lives outside the repo**, at `~/.venvs/sample-librarian`, not `./.venv`. Discovered empirically: a venv created inside this iCloud-synced repo got its editable-install `.pth` file silently tagged with macOS's hidden flag, which Python's `site` module skips outright, so the package was uninstallable in place. Same underlying lesson as the data-root/symlink decision — anything that needs to just reliably work stays off iCloud. Run tools via `~/.venvs/sample-librarian/bin/pytest`, `~/.venvs/sample-librarian/bin/samplelib`, etc., or `source ~/.venvs/sample-librarian/bin/activate` first.
- `brew install ffmpeg` needed (ffprobe, for MP3/M4A/FLAC duration/samplerate).
- Swift/SwiftUI app lives in `swift-app/`, built after Stage 1 (Python) is solid.

## Safety rules for this codebase

- Never move or rewrite a file outside of `pipeline/per_file_pipeline.py`'s dry-run-gated path.
- Files under a configured `vendor_roots` entry are never moved or renamed, only symlinked.
- Every real move/symlink/metadata-write action must append to the JSONL manifest before/as it happens, so `undo` can always replay it.
