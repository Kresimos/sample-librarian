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
- Real `config/settings.toml` exists (gitignored, personal) -- scoped to `~/Downloads` + `~/Desktop` for phase 1, `vendor_roots` pre-filled from a manual look at this machine (Logic's own content, both Native Instruments locations). No real `--apply` run against it yet, dry-run only so far.

## Classification is all tags, no exclusive type

`classify/classifier.py` (Python) and `Database.swift`/`SampleRecord.swift` (Swift) have no
`sample_type`/`loop_type` columns or fields -- everything a file gets labeled with (instrument,
drum/melodic/vocal/fx, loop vs one-shot, "song", "app-foley") is a tag in one flat set, and a file
can match several taxonomy rules at once (a "Guitar Riff" gets both `guitar` and `melody`; a kick
with a sub-bass tail gets both `kick` and `bass`). This was a deliberate pivot from an earlier
single-exclusive-type design, per the user: "I think everything is just tags is the way to go."
`repository.search_samples`/`tag_counts` (and their Swift mirrors) take `tags: list[str]` with
AND semantics (must have all requested tags). `tag_counts` is the faceted-narrowing backend --
given the current filters, how many matching samples have each remaining tag -- which Stage 2's
`FacetChipsView` uses to show clickable "what's still available" chips instead of a fixed
type/genre hierarchy.

## Stage 2 (swift-app/)

- SwiftUI app, no external SPM dependencies (raw SQLite3 C API, read-only, WAL-aware). Two targets: `SampleLibrarianCore` (DB access, models, search -- pure logic, unit tested) and `SampleLibrarianApp` (the windowed UI + drag-and-drop, imports Core).
- Build: `cd swift-app && swift build`. Test: `swift test`. Package a launchable `.app`: `./build_app_bundle.sh release`, then move/symlink `.build/SampleLibrarian.app` to `/Applications` and bind a shortcut via System Settings > Keyboard > Keyboard Shortcuts > App Shortcuts.
- `AppConfig.libraryRoot` defaults to `~/SampleLibrary`; override with `SAMPLELIB_LIBRARY_ROOT=/some/path` for testing against a scratch library.
- **Drag-and-drop needs hands-on verification.** `SampleRowView` uses SwiftUI's `.onDrag` first (per the project plan). `DragDrop/DraggableFileArea.swift` is a documented, ready-to-swap-in AppKit fallback (`NSDraggingSession`) for if `.onDrag` proves unreliable against Logic Pro specifically -- Logic is an older AppKit/Cocoa app, not a modern drag-and-drop-API-native one, which is exactly the case the plan flagged as a risk. Nobody has dragged a row from a running instance onto a live Logic Pro session yet; that's the first thing to try by hand.
- **"Rescan Inbox" toolbar button** shells out to the real `samplelib` CLI (`InboxRescanner.swift`) rather than reimplementing the pipeline in Swift. It needs two things findable at fixed, predictable paths (this app has no reliable way to locate the code repo, wherever it happens to be checked out): the CLI binary at `~/.venvs/sample-librarian/bin/samplelib` (default venv location) and a copy or symlink of `settings.toml` at `~/SampleLibrary/settings.toml` (i.e. `library_root`, not the repo's `config/` dir). Both overridable via `SAMPLELIB_CLI_PATH` / `SAMPLELIB_CONFIG_PATH`. **Setup step still needed**: `ln -s "<repo>/config/settings.toml" ~/SampleLibrary/settings.toml` -- a real settings.toml exists now (see Environment above) but hasn't been symlinked into place yet.
- **Faceted browsing**: `FacetChipsView` + `BrowserViewModel.selectedTags`/`availableFacets` -- see "Classification is all tags" above for why there's no fixed type/genre picker.
- Verified so far (2026-08-25): full package builds clean (`swift build`), all 11 `SampleLibrarianCoreTests` pass (including InboxRescanner's guard logic against a stand-in `/bin/echo` executable, not the real CLI), and a debug build of the packaged app launches against a scratch library and stays running without crashing. None of that touches actual window rendering, drag behavior, or a real end-to-end click of the Rescan Inbox button -- only a human at the keyboard can confirm those.

## Safety rules for this codebase

- Never move or rewrite a file outside of `pipeline/per_file_pipeline.py`'s dry-run-gated path.
- Files under a configured `vendor_roots` entry are never moved or renamed, only symlinked.
- Every real move/symlink/metadata-write action must append to the JSONL manifest before/as it happens, so `undo` can always replay it.
