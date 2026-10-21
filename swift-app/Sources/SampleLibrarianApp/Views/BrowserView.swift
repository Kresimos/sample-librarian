import AppKit
import SwiftUI
import SampleLibrarianCore

/// The three keyboard-focusable regions of the browser. Up/Down move between
/// them (search -> chips -> list, top to bottom) rather than Tab, which is
/// already a system-wide "full keyboard access" accessibility key that draws
/// its own focus-ring UI the user doesn't want triggered here. "/" jumps
/// straight to search from either of the other two.
enum BrowserFocusArea: Hashable {
    case search, chips, list
}

@MainActor
final class BrowserViewModel: ObservableObject {
    @Published var searchText: String = "" {
        // Debounced rather than queried outright: this is bound straight to
        // the search TextField, so an immediate reload here means a full
        // round trip to SQLite on every single keystroke.
        didSet { scheduleReload(debounce: Self.typingDebounce) }
    }
    /// Every committed filter chip -- official tags, free-text terms
    /// (anything typed that isn't a known tag still becomes one of these,
    /// so composite searches like "cymatics kick 170bpm" work), and at most
    /// one bpm-range / one key filter (a new one replaces the old). Rendered
    /// inline in the search field itself (see SearchFilterBar).
    @Published private(set) var committedFilters: [CommittedFilter] = [] {
        // No debounce delay -- a chip click should feel immediate. Going
        // through scheduleReload anyway still coalesces addFilter's two
        // mutations (removeAll then append) into a single query.
        didSet { scheduleReload(debounce: .zero) }
    }
    @Published var sort: Database.SortOption = .rating {
        // Reassigning sortDirection (even to an equal value) always fires
        // its own didSet below, which does the actual reload -- so this
        // doesn't also call reload() itself, to avoid querying twice per
        // sort change.
        didSet { sortDirection = sort.defaultDirection }
    }
    @Published var sortDirection: Database.SortDirection = Database.SortOption.rating.defaultDirection {
        didSet { scheduleReload(debounce: .zero) }
    }
    /// Only the pages loaded so far, not every match -- see `totalCount`.
    @Published private(set) var samples: [SampleRecord] = []
    /// How many samples match the current filters in total, including rows not
    /// yet paged in. This is what the "N samples" label shows.
    @Published private(set) var totalCount: Int = 0
    @Published private(set) var availableFacets: [Database.Facet] = []
    @Published var errorMessage: String?
    @Published var selection: SampleRecord.ID? {
        didSet { autoplaySelection() }
    }
    @Published private(set) var isRescanning = false
    @Published var rescanStatusMessage: String?
    /// Index into availableFacets -- which chip Left/Right keyboard nav is on.
    @Published var focusedChipIndex: Int = 0

    let player = AudioPlayerController()

    private let database: Database?
    /// The full tag vocabulary, for recognizing a typed word as an official
    /// tag on Enter. Only changes when the library itself does, so it's cached
    /// here rather than re-queried on every reload.
    private var knownTags: Set<String> = []

    /// The browser loads results a page at a time: a broad search matches tens
    /// of thousands of rows, and decoding all of them into a @Published array
    /// on every keystroke is what made typing stutter.
    /// nonisolated so the detached query tasks can read it without hopping
    /// back to the main actor.
    private nonisolated static let pageSize = 500
    /// Start fetching the next page once the list gets this close to the end,
    /// so scrolling never visibly stops at a page boundary.
    private static let pagePrefetchMargin = 50
    private static let typingDebounce: Duration = .milliseconds(120)

    private var reloadTask: Task<Void, Never>?
    private var loadMoreTask: Task<Void, Never>?
    private var isLoadingPage = false
    /// Bumped by every reload, so a page still in flight from the previous
    /// result set can tell that it's stale rather than clobbering the new one's
    /// paging state.
    private var resultGeneration = 0

    var hasMore: Bool { samples.count < totalCount }

    var selectedSample: SampleRecord? {
        guard let selection else { return nil }
        return samples.first { $0.id == selection }
    }

    var focusedTag: String? {
        guard !availableFacets.isEmpty else { return nil }
        return availableFacets[focusedChipIndex.clamped(to: 0...(availableFacets.count - 1))].tag
    }

    init() {
        do {
            database = try Database(path: AppConfig.databasePath)
        } catch {
            database = nil
            errorMessage = "Couldn't open library database at \(AppConfig.databasePath.path): \(error)"
        }
        reload()
    }

    /// Re-reads the tag vocabulary. Only worth doing when the library could
    /// have gained tags -- startup, an explicit Refresh, or after a rescan.
    private func refreshKnownTags() {
        guard let database else { return }
        knownTags = (try? database.allTagNames()) ?? knownTags
    }

    // MARK: - Filters / search

    func selectTag(_ tag: String) {
        addFilter(.officialTag(tag))
    }

    /// Replaces any existing filter of the same category (see
    /// CommittedFilter.id -- bpm/key have a constant id regardless of value)
    /// and skips exact duplicates for tag/free-text.
    private func addFilter(_ filter: CommittedFilter) {
        committedFilters.removeAll { $0.id == filter.id }
        committedFilters.append(filter)
    }

    /// Backspace on an empty search field: remove the most recently
    /// committed filter, same as deleting the last typed character would.
    func removeLastFilter() {
        guard !committedFilters.isEmpty else { return }
        committedFilters.removeLast()
    }

    /// Enter in the search box: every word becomes a committed filter chip,
    /// including words that aren't official tags (those become `.freeText`
    /// chips, colored differently -- see SearchFilterBar) so a search like
    /// "cymatics kick 170bpm" works as a composite AND search even though
    /// "cymatics" was never in the taxonomy.
    func commitSearchText() {
        guard !searchText.isEmpty else { return }
        for filter in SearchQueryParser.commitTokens(searchText, knownTags: knownTags) {
            addFilter(filter)
        }
        searchText = ""
    }

    /// The current filter state flattened into the shape Database.search /
    /// .count / .tagCounts all take. Sendable, so it can cross into the
    /// detached task that actually runs the queries.
    private struct Query: Sendable {
        var text: String?
        var tags: [String] = []
        var excludedTags: [String] = []
        var freeTextTerms: [String] = []
        var excludedFreeTextTerms: [String] = []
        var bpmMin: Double?
        var bpmMax: Double?
        var musicalKey: String?
        var musicalKeyRootOnly: String?
        var sort: Database.SortOption = .rating
        var direction: Database.SortDirection = .descending
    }

    private var currentQuery: Query {
        let bpm = committedFilters.lazy.compactMap { filter -> (min: Double, max: Double)? in
            if case .bpmRange(let min, let max, _) = filter { return (min, max) }
            return nil
        }.first
        let key = committedFilters.lazy.compactMap { filter -> (exact: String?, rootOnly: String?)? in
            if case .key(let exact, let rootOnly, _) = filter { return (exact, rootOnly) }
            return nil
        }.first

        return Query(
            text: searchText.isEmpty ? nil : searchText,
            tags: committedFilters.compactMap { filter in
                if case .officialTag(let tag) = filter { return tag }
                return nil
            },
            excludedTags: committedFilters.compactMap { filter in
                if case .excludedTag(let tag) = filter { return tag }
                return nil
            },
            freeTextTerms: committedFilters.compactMap { filter in
                if case .freeText(let term) = filter { return term }
                return nil
            },
            excludedFreeTextTerms: committedFilters.compactMap { filter in
                if case .excludedFreeText(let term) = filter { return term }
                return nil
            },
            bpmMin: bpm?.min,
            bpmMax: bpm?.max,
            musicalKey: key?.exact,
            musicalKeyRootOnly: key?.rootOnly,
            sort: sort,
            direction: sortDirection
        )
    }

    private struct ReloadResult: Sendable {
        let samples: [SampleRecord]
        let totalCount: Int
        let facets: [Database.Facet]
    }

    /// Runs the first page, the total count and the facet counts together, off
    /// the main actor. `Database` is opened SQLITE_OPEN_FULLMUTEX, so using it
    /// from a detached task is safe (see its `@unchecked Sendable` note).
    private nonisolated static func runReload(_ database: Database, _ query: Query) throws -> ReloadResult {
        let samples = try database.search(
            text: query.text, tags: query.tags, excludedTags: query.excludedTags,
            freeTextTerms: query.freeTextTerms, excludedFreeTextTerms: query.excludedFreeTextTerms,
            bpmMin: query.bpmMin, bpmMax: query.bpmMax,
            musicalKey: query.musicalKey, musicalKeyRootOnly: query.musicalKeyRootOnly,
            sort: query.sort, direction: query.direction,
            limit: pageSize, offset: 0
        )
        let totalCount = try database.count(
            text: query.text, tags: query.tags, excludedTags: query.excludedTags,
            freeTextTerms: query.freeTextTerms, excludedFreeTextTerms: query.excludedFreeTextTerms,
            bpmMin: query.bpmMin, bpmMax: query.bpmMax,
            musicalKey: query.musicalKey, musicalKeyRootOnly: query.musicalKeyRootOnly
        )
        let facets = try database.tagCounts(
            text: query.text, tags: query.tags, excludedTags: query.excludedTags,
            freeTextTerms: query.freeTextTerms, excludedFreeTextTerms: query.excludedFreeTextTerms,
            bpmMin: query.bpmMin, bpmMax: query.bpmMax,
            musicalKey: query.musicalKey, musicalKeyRootOnly: query.musicalKeyRootOnly
        )
        return ReloadResult(samples: samples, totalCount: totalCount, facets: facets)
    }

    /// Cancels any in-flight reload and starts a new one after `debounce`.
    /// Same shape as PreviewPanel's waveform debounce: sleep, bail if
    /// cancelled, do the work off the main actor, re-check cancellation before
    /// publishing so a stale result can never overwrite a newer one.
    private func scheduleReload(debounce: Duration) {
        guard let database else { return }
        reloadTask?.cancel()
        loadMoreTask?.cancel()
        isLoadingPage = false
        resultGeneration += 1
        let query = currentQuery
        reloadTask = Task { [weak self] in
            if debounce > .zero {
                try? await Task.sleep(for: debounce)
                if Task.isCancelled { return }
            }
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    try Self.runReload(database, query)
                }.value
                if Task.isCancelled { return }
                guard let self else { return }
                self.samples = result.samples
                self.totalCount = result.totalCount
                self.availableFacets = result.facets
                self.errorMessage = nil
            } catch {
                if Task.isCancelled { return }
                self?.errorMessage = "Search failed: \(error)"
            }
        }
    }

    /// An explicit, undebounced reload -- startup, the Refresh button, and
    /// after a rescan. Also re-reads the tag vocabulary, which a rescan can
    /// have added to.
    func reload() {
        refreshKnownTags()
        scheduleReload(debounce: .zero)
    }

    // MARK: - Paging

    /// Called as each row appears (and as the keyboard selection moves): once
    /// the list is within `pagePrefetchMargin` of the loaded rows, fetch the
    /// next page and append it.
    func loadMoreIfNeeded(currentItem: SampleRecord) {
        guard hasMore, !isLoadingPage, let database else { return }
        guard let index = samples.firstIndex(where: { $0.id == currentItem.id }),
              index >= samples.count - Self.pagePrefetchMargin else { return }

        let query = currentQuery
        let offset = samples.count
        let generation = resultGeneration
        isLoadingPage = true
        loadMoreTask = Task { [weak self] in
            let page = try? await Task.detached(priority: .userInitiated) {
                try database.search(
                    text: query.text, tags: query.tags, excludedTags: query.excludedTags,
                    freeTextTerms: query.freeTextTerms, excludedFreeTextTerms: query.excludedFreeTextTerms,
                    bpmMin: query.bpmMin, bpmMax: query.bpmMax,
                    musicalKey: query.musicalKey, musicalKeyRootOnly: query.musicalKeyRootOnly,
                    sort: query.sort, direction: query.direction,
                    limit: Self.pageSize, offset: offset
                )
            }.value
            // A reload could have replaced the result set while this page was
            // in flight; appending it then would splice in rows from the old
            // search, and clearing isLoadingPage would be clearing the newer
            // reload's state rather than this task's.
            guard let self, self.resultGeneration == generation else { return }
            self.isLoadingPage = false
            guard !Task.isCancelled, let page, !page.isEmpty,
                  self.samples.count == offset else { return }
            self.samples.append(contentsOf: page)
        }
    }

    // MARK: - Chip keyboard navigation (available/unselected tags only --
    // committed ones live in the search field and are removed via backspace)

    func moveChipFocus(by delta: Int) {
        let count = availableFacets.count
        guard count > 0 else { return }
        focusedChipIndex = (focusedChipIndex + delta).clamped(to: 0...(count - 1))
    }

    func resetChipFocus() {
        focusedChipIndex = 0
    }

    /// Return/Space while the chips area has focus: select the highlighted
    /// available tag.
    func selectFocusedChip() {
        guard let tag = focusedTag else { return }
        selectTag(tag)
    }

    var isSelectionAtTop: Bool {
        guard let selection, let first = samples.first?.id else { return true }
        return selection == first
    }

    /// Up/Down while the list has focus. Deliberately NOT delegated to
    /// List's native arrow-key handling -- SampleRowView's click handler sets
    /// `selection` directly (see its comment: .onDrag competes with, and
    /// often wins over, List's native click-to-select), which leaves
    /// AppKit's real internal table selection stale even though our
    /// `selection` binding and the on-screen highlight are correct. Native
    /// arrow-key nav then moves relative to that stale internal selection --
    /// observed as pressing Down jumping back to a much earlier row. Driving
    /// Up/Down off `samples`/`selection` ourselves, the same source of truth
    /// a click already uses, keeps click and keyboard nav consistent.
    func selectAdjacent(by delta: Int) {
        guard !samples.isEmpty else { return }
        guard let id = selection, let index = samples.firstIndex(where: { $0.id == id }) else {
            selection = samples.first?.id
            return
        }
        let next = samples[(index + delta).clamped(to: 0...(samples.count - 1))]
        selection = next.id
        // Arrowing toward the end of the loaded rows pages in more, the same
        // as scrolling there would -- List only calls onAppear for rows it
        // actually renders, and a held-down arrow key can outrun that.
        loadMoreIfNeeded(currentItem: next)
    }

    // MARK: - Playback

    private func autoplaySelection() {
        guard let sample = selectedSample else {
            player.stop()
            return
        }
        player.play(url: sample.resolvedFileURL)
    }

    /// Enter: restart the currently selected sample from the beginning.
    func restartPlayback() {
        guard let sample = selectedSample else { return }
        if player.currentURL == sample.resolvedFileURL {
            player.restart()
        } else {
            player.play(url: sample.resolvedFileURL)
        }
    }

    /// Space: a real stop, not a pause -- see AudioPlayerController.stop.
    func stopPlayback() {
        player.stop()
    }

    // MARK: - Rating

    /// Right arrow = +1, left arrow = -1, clamped to -2...+2. Persists
    /// immediately and updates the row in place without a full reload/re-sort,
    /// so rating repeatedly while browsing doesn't reshuffle the list under you.
    func adjustRating(by delta: Int) {
        guard let id = selection, let index = samples.firstIndex(where: { $0.id == id }) else { return }
        let newRating = max(-2, min(2, samples[index].rating + delta))
        guard newRating != samples[index].rating else { return }
        samples[index] = samples[index].withRating(newRating)
        try? database?.setRating(sampleId: id, rating: newRating)
    }

    // MARK: - Inbox rescan

    func rescanInbox() {
        guard !isRescanning else { return }
        isRescanning = true
        rescanStatusMessage = nil
        Task {
            do {
                let result = try await InboxRescanner.run()
                rescanStatusMessage = result.succeeded
                    ? "Inbox rescanned."
                    : "Rescan failed: \(result.output.trimmingCharacters(in: .whitespacesAndNewlines))"
                if result.succeeded {
                    reload()
                }
            } catch {
                rescanStatusMessage = "Rescan failed: \(error)"
            }
            isRescanning = false
        }
    }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

struct BrowserView: View {
    @StateObject private var viewModel = BrowserViewModel()
    @FocusState private var focusedArea: BrowserFocusArea?
    // A focused TextField swallows the Backspace key for its own (no-op,
    // since there's nothing left to delete) text editing before SwiftUI's
    // .onKeyPress modifiers on that field ever see it -- confirmed by
    // hands-on testing (2026-08-25), so removing the last committed filter
    // needs a raw NSEvent monitor instead, which sees the key press
    // regardless of what the focused control does with it.
    @State private var searchBackspaceMonitor: Any?

    private var hasChips: Bool {
        !viewModel.availableFacets.isEmpty
    }

    private static let kVKDelete: UInt16 = 51  // the physical Backspace key on every Mac keyboard

    var body: some View {
        VStack(spacing: 0) {
            SearchFilterBar(
                searchText: $viewModel.searchText,
                committedFilters: viewModel.committedFilters,
                sort: $viewModel.sort,
                sortDirection: $viewModel.sortDirection,
                // The true match count, not just the pages loaded so far.
                sampleCount: viewModel.totalCount,
                isSearchFocused: $focusedArea,
                isRescanning: viewModel.isRescanning,
                onSubmit: viewModel.commitSearchText,
                onFocusDown: { focusedArea = hasChips ? .chips : .list },
                onRefresh: viewModel.reload,
                onRescanInbox: viewModel.rescanInbox
            )

            FacetChipsView(
                availableFacets: viewModel.availableFacets,
                onSelect: viewModel.selectTag,
                focusedTag: focusedArea == .chips ? viewModel.focusedTag : nil
            )
            .focusable()
            .focusEffectDisabled()
            .focused($focusedArea, equals: .chips)
            .onKeyPress(KeyEquivalent("/")) {
                focusedArea = .search
                return .handled
            }
            .onKeyPress(.leftArrow) {
                viewModel.moveChipFocus(by: -1)
                return .handled
            }
            .onKeyPress(.rightArrow) {
                viewModel.moveChipFocus(by: 1)
                return .handled
            }
            .onKeyPress(.return) {
                viewModel.selectFocusedChip()
                return .handled
            }
            .onKeyPress(.space) {
                viewModel.selectFocusedChip()
                return .handled
            }
            .onKeyPress(.upArrow) {
                focusedArea = .search
                return .handled
            }
            .onKeyPress(.downArrow) {
                focusedArea = .list
                return .handled
            }
            Divider()

            if let errorMessage = viewModel.errorMessage {
                ContentUnavailableMessage(message: errorMessage)
            } else if viewModel.samples.isEmpty {
                ContentUnavailableMessage(message: "No samples match. Try a different search, or run `samplelib scan --apply` first.")
            } else {
                // List gives arrow-key up/down navigation + selection
                // highlighting for free once it has focus. Left/Right
                // (rating), Return (restart preview), and Space (stop
                // preview) are layered on top via onKeyPress; a click always
                // selects AND moves keyboard focus into the list (see
                // SampleRowView's onSelect) so arrow keys/space/enter
                // immediately control the list right after a click, even if
                // focus was previously in the search field.
                //
                // selectAdjacent() drives `selection` ourselves rather than
                // relying on List's native arrow-key handling (see that
                // method's comment), which means List's own auto-scroll --
                // which only kicks in for its own internal keyboard
                // navigation -- never fires either. Without the
                // ScrollViewReader below, arrowing past the visible rows
                // moves the selection but leaves the viewport stuck in
                // place, so the highlighted row disappears off-screen.
                ScrollViewReader { proxy in
                    List(viewModel.samples, selection: $viewModel.selection) { sample in
                        SampleRowView(sample: sample) {
                            viewModel.selection = sample.id
                            focusedArea = .list
                        }
                        .id(sample.id)
                        // Results load a page at a time; List renders rows
                        // lazily, so this fires as you scroll toward the end.
                        .onAppear { viewModel.loadMoreIfNeeded(currentItem: sample) }
                    }
                    .listStyle(.plain)
                    .font(.system(.body, design: .monospaced))
                    .focused($focusedArea, equals: .list)
                    .onKeyPress(.leftArrow) {
                        viewModel.adjustRating(by: -1)
                        return .handled
                    }
                    .onKeyPress(.rightArrow) {
                        viewModel.adjustRating(by: 1)
                        return .handled
                    }
                    .onKeyPress(.return) {
                        viewModel.restartPlayback()
                        return .handled
                    }
                    .onKeyPress(.space) {
                        viewModel.stopPlayback()
                        return .handled
                    }
                    .onKeyPress(.upArrow) {
                        if viewModel.isSelectionAtTop {
                            focusedArea = hasChips ? .chips : .search
                            return .handled
                        }
                        viewModel.selectAdjacent(by: -1)
                        return .handled
                    }
                    .onKeyPress(.downArrow) {
                        viewModel.selectAdjacent(by: 1)
                        return .handled
                    }
                    .onKeyPress(KeyEquivalent("/")) {
                        focusedArea = .search
                        return .handled
                    }
                    // selectAdjacent()/adjustRating() drive `selection`
                    // directly rather than going through List's native
                    // arrow-key handling (see selectAdjacent's comment for
                    // why), which means List's own keyboard-driven
                    // auto-scroll never kicks in either -- the highlighted
                    // row can end up scrolled out of view. Scroll it back
                    // into the viewport ourselves whenever selection changes.
                    .onChange(of: viewModel.selection) { _, newSelection in
                        guard let newSelection else { return }
                        withAnimation(.easeOut(duration: 0.1)) {
                            proxy.scrollTo(newSelection, anchor: nil)
                        }
                    }
                }
            }

            Divider()
            PreviewPanel(sample: viewModel.selectedSample, player: viewModel.player)
        }
        .frame(minWidth: 640, minHeight: 460)
        .background(Color(nsColor: .textBackgroundColor))
        .onAppear {
            focusedArea = .list
            if searchBackspaceMonitor == nil {
                searchBackspaceMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
                    guard focusedArea == .search, event.keyCode == Self.kVKDelete,
                          viewModel.searchText.isEmpty, !viewModel.committedFilters.isEmpty else {
                        return event
                    }
                    viewModel.removeLastFilter()
                    return nil  // swallow -- there's nothing in the text field for the system to also act on
                }
            }
        }
        .onDisappear {
            if let searchBackspaceMonitor {
                NSEvent.removeMonitor(searchBackspaceMonitor)
            }
            searchBackspaceMonitor = nil
        }
        .onChange(of: focusedArea) { _, newValue in
            if newValue == .chips { viewModel.resetChipFocus() }
        }
        // The database is written by an entirely separate process (the
        // samplelib CLI, possibly run from a Terminal while this app was
        // already open) -- there's no push notification for "new data
        // showed up", so refresh whenever the window regains focus. A
        // manual button covers the case where the app was already frontmost
        // the whole time a scan ran elsewhere, so focus never changed.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            viewModel.reload()
        }
        // Refresh/Process Inbox used to live here as native toolbar buttons;
        // they're now in SearchFilterBar's own top-right corner so they
        // match its flat monospaced pill style instead of standard macOS
        // toolbar chrome.
        .alert(
            "Inbox Rescan",
            isPresented: Binding(
                get: { viewModel.rescanStatusMessage != nil },
                set: { if !$0 { viewModel.rescanStatusMessage = nil } }
            )
        ) {
            Button("OK") { viewModel.rescanStatusMessage = nil }
        } message: {
            Text(viewModel.rescanStatusMessage ?? "")
        }
    }
}

private struct ContentUnavailableMessage: View {
    let message: String

    var body: some View {
        VStack {
            Spacer()
            Text(message)
                .font(.system(.body, design: .monospaced))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding()
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }
}
