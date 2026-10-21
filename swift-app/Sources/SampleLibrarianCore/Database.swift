import Foundation
import SQLite3

/// Access to the shared library.sqlite3 (Python owns the schema/pipeline
/// logic and is the only writer of everything except `rating`, which this
/// app writes directly -- a single-column, purely-UI-state field isn't worth
/// round-tripping through the Python CLI for). Uses the raw SQLite3 C API
/// directly -- deliberately no external package dependency, so this builds
/// without network access to resolve one, and stays as light as the "not
/// ADSR" design goal wants.
///
/// Safe to use from any thread (hence `@unchecked Sendable`): the handle is
/// opened with SQLITE_OPEN_FULLMUTEX -- SQLite's "serialized" threading mode,
/// which puts a mutex around the connection itself -- and `handle` is the only
/// stored property, set once in `init`. That's what lets the browser run its
/// queries off the main actor in a detached task.
public final class Database: @unchecked Sendable {
    private var handle: OpaquePointer?

    public enum DatabaseError: Error, CustomStringConvertible {
        case openFailed(String)
        case queryFailed(String)
        case invalidRating(Int)

        public var description: String {
            switch self {
            case .openFailed(let msg): return "Failed to open database: \(msg)"
            case .queryFailed(let msg): return "Query failed: \(msg)"
            case .invalidRating(let value): return "rating must be between -2 and 2, got \(value)"
            }
        }
    }

    /// One row of `tagCounts` -- a tag still available to narrow by, and how
    /// many of the currently-matching samples carry it. A named struct rather
    /// than the `(tag:, count:)` tuple this used to be: tuples are neither
    /// `Sendable` (so they can't come back out of a detached query task) nor
    /// `Equatable` (so SwiftUI could never skip re-rendering the chip row).
    public struct Facet: Identifiable, Hashable, Sendable {
        public let tag: String
        public let count: Int

        public var id: String { tag }

        public init(tag: String, count: Int) {
            self.tag = tag
            self.count = count
        }
    }

    /// Default sort is `.rating` (highest first) -- with a large scattered
    /// library, browsing lowest-rated junk first defeats the point of rating
    /// things at all.
    public enum SortOption: String, CaseIterable, Sendable {
        case alphabetical, rating, dateAdded, length, key, random

        /// Menu label, in the order the dropdown lists them.
        public var displayName: String {
            switch self {
            case .alphabetical: return "Alphabetical"
            case .rating: return "Rating"
            case .dateAdded: return "Date"
            case .length: return "Length"
            case .key: return "Key"
            case .random: return "Random"
            }
        }

        /// The direction each sort starts in when first selected (matches
        /// what used to be hardcoded before ascending/descending became
        /// toggleable) -- rating/date/length default to "biggest first",
        /// alphabetical/key default to "A first". Meaningless for `.random`.
        public var defaultDirection: SortDirection {
            switch self {
            case .rating, .dateAdded, .length: return .descending
            case .alphabetical, .key: return .ascending
            case .random: return .descending
            }
        }

        /// Random has no direction to flip -- there's nothing for the UI's
        /// ascending/descending toggle to do while it's selected.
        public var supportsDirection: Bool {
            self != .random
        }

        func orderByClause(direction: SortDirection) -> String {
            switch self {
            case .random:
                return "RANDOM()"
            case .rating:
                return "s.rating \(direction.sqlKeyword), s.date_added \(direction.sqlKeyword)"
            case .dateAdded:
                return "s.date_added \(direction.sqlKeyword)"
            case .alphabetical:
                return "s.cleaned_filename COLLATE NOCASE \(direction.sqlKeyword)"
            // NULLs sort first in SQLite's default ASC ordering -- the
            // `IS NULL` clause pushes samples missing this value to the
            // bottom regardless of direction, in both cases.
            case .length:
                return "s.duration_seconds IS NULL, s.duration_seconds \(direction.sqlKeyword)"
            case .key:
                return "s.musical_key IS NULL, s.musical_key COLLATE NOCASE \(direction.sqlKeyword)"
            }
        }
    }

    public enum SortDirection: String, CaseIterable, Sendable {
        case ascending, descending

        var sqlKeyword: String {
            self == .ascending ? "ASC" : "DESC"
        }

        public var toggled: SortDirection {
            self == .ascending ? .descending : .ascending
        }

        public var systemImage: String {
            self == .ascending ? "arrow.up" : "arrow.down"
        }
    }

    public init(path: URL) throws {
        let flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX
        if sqlite3_open_v2(path.path, &handle, flags, nil) != SQLITE_OK {
            let message = String(cString: sqlite3_errmsg(handle))
            sqlite3_close(handle)
            throw DatabaseError.openFailed(message)
        }
        // Python (samplelib CLI) can be writing at the same moment -- WAL
        // mode allows one writer + concurrent readers, but two writers still
        // briefly contend. Wait rather than fail outright on that.
        sqlite3_busy_timeout(handle, 5000)
    }

    deinit {
        sqlite3_close(handle)
    }

    /// Mirrors sample_librarian.db.repository.search_samples on the Python
    /// side -- same filters, same plain LIKE/JOIN approach (see schema.sql
    /// for why this isn't FTS5). `tags` requires ALL given tags (AND, not
    /// any-of) -- there's no separate type/loop-type filter anymore, it's
    /// all just tags now.
    public func search(
        text: String? = nil,
        tags: [String] = [],
        excludedTags: [String] = [],
        freeTextTerms: [String] = [],
        excludedFreeTextTerms: [String] = [],
        bpmMin: Double? = nil,
        bpmMax: Double? = nil,
        musicalKey: String? = nil,
        musicalKeyRootOnly: String? = nil,
        sort: SortOption = .rating,
        // nil (rather than defaulting to a fixed SortDirection) means "use
        // this sort's own default direction" -- a plain `= .descending`
        // default would silently sort .alphabetical/.key backwards for any
        // caller that only passes `sort:`, since Swift default-parameter
        // values can't reference another parameter.
        direction: SortDirection? = nil,
        // The browser pages through results rather than materializing the
        // whole library (24k+ rows) on every keystroke. nil means "no LIMIT"
        // -- kept as the default so callers that genuinely want everything
        // (and the tests) read unchanged.
        limit: Int? = nil,
        offset: Int = 0
    ) throws -> [SampleRecord] {
        var (clauses, bindings) = Self.baseFilter(
            text: text, tags: tags, excludedTags: excludedTags,
            freeTextTerms: freeTextTerms, excludedFreeTextTerms: excludedFreeTextTerms,
            bpmMin: bpmMin, bpmMax: bpmMax,
            musicalKey: musicalKey, musicalKeyRootOnly: musicalKeyRootOnly
        )

        var limitClause = ""
        if let limit {
            limitClause = "\nLIMIT ? OFFSET ?"
            bindings.append(.int(limit))
            bindings.append(.int(offset))
        }

        let sql = """
        SELECT s.id, s.current_path, s.bucket, s.cleaned_filename,
               s.bpm, s.musical_key, s.duration_seconds, s.rating
        FROM samples s
        WHERE \(clauses.joined(separator: " AND "))
        ORDER BY \(sort.orderByClause(direction: direction ?? sort.defaultDirection))\(limitClause)
        """

        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        Self.bind(bindings, to: statement)

        // Rows first, tags second. Fetching each row's tags inline here would
        // mean one prepare/step/finalize cycle per result -- 24k of them for a
        // broad search -- so the rows come out untagged and a single grouped
        // query below fills them in.
        var rows: [SampleRecord] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            rows.append(SampleRecord(from: statement!, tags: []))
        }

        let tagsBySample = try fetchTags(forSampleIds: rows.map(\.id))
        return rows.map { $0.withTags(tagsBySample[$0.id] ?? []) }
    }

    /// How many samples match these filters in total, ignoring any LIMIT --
    /// what the browser's "N samples" label shows while only a page of rows is
    /// actually loaded. Same clauses as `search`, so the two can't disagree.
    public func count(
        text: String? = nil,
        tags: [String] = [],
        excludedTags: [String] = [],
        freeTextTerms: [String] = [],
        excludedFreeTextTerms: [String] = [],
        bpmMin: Double? = nil,
        bpmMax: Double? = nil,
        musicalKey: String? = nil,
        musicalKeyRootOnly: String? = nil
    ) throws -> Int {
        let (clauses, bindings) = Self.baseFilter(
            text: text, tags: tags, excludedTags: excludedTags,
            freeTextTerms: freeTextTerms, excludedFreeTextTerms: excludedFreeTextTerms,
            bpmMin: bpmMin, bpmMax: bpmMax,
            musicalKey: musicalKey, musicalKeyRootOnly: musicalKeyRootOnly
        )

        let sql = "SELECT COUNT(*) FROM samples s WHERE \(clauses.joined(separator: " AND "))"

        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        Self.bind(bindings, to: statement)

        guard sqlite3_step(statement) == SQLITE_ROW else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        return Int(sqlite3_column_int64(statement, 0))
    }

    /// For faceted narrowing: given the same filters as `search`, how many
    /// matching samples have each tag? Already-selected tags are excluded
    /// (nothing to learn from re-showing them). Called with no filters at
    /// all, this is just the overall tag cloud.
    public func tagCounts(
        text: String? = nil,
        tags: [String] = [],
        excludedTags: [String] = [],
        freeTextTerms: [String] = [],
        excludedFreeTextTerms: [String] = [],
        bpmMin: Double? = nil,
        bpmMax: Double? = nil,
        musicalKey: String? = nil,
        musicalKeyRootOnly: String? = nil
    ) throws -> [Facet] {
        let (clauses, bindings) = Self.baseFilter(
            text: text, tags: tags, excludedTags: excludedTags,
            freeTextTerms: freeTextTerms, excludedFreeTextTerms: excludedFreeTextTerms,
            bpmMin: bpmMin, bpmMax: bpmMax,
            musicalKey: musicalKey, musicalKeyRootOnly: musicalKeyRootOnly
        )

        let sql = """
        SELECT t.name AS tag, COUNT(DISTINCT s.id) AS n
        FROM samples s
        JOIN sample_tags st ON st.sample_id = s.id
        JOIN tags t ON t.id = st.tag_id
        WHERE \(clauses.joined(separator: " AND "))
        GROUP BY t.name
        ORDER BY n DESC, t.name
        """

        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        Self.bind(bindings, to: statement)

        // Neither an already-required tag nor an already-excluded one is
        // worth re-offering as an "available" facet chip -- selecting the
        // former is a no-op, and selecting the latter would create a
        // contradictory require-and-exclude filter pair.
        let alreadySelected = Set(tags).union(excludedTags)
        var results: [Facet] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            guard let cString = sqlite3_column_text(statement, 0) else { continue }
            let tag = String(cString: cString)
            if alreadySelected.contains(tag) { continue }
            results.append(Facet(tag: tag, count: Int(sqlite3_column_int64(statement, 1))))
        }
        return results
    }

    /// Persists a rating change immediately -- called on every left/right
    /// arrow keypress while browsing, so this needs to be cheap and never
    /// touch classification/tags/anything Python owns.
    public func setRating(sampleId: Int64, rating: Int) throws {
        guard (-2...2).contains(rating) else { throw DatabaseError.invalidRating(rating) }
        let sql = "UPDATE samples SET rating = ? WHERE id = ?"
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        sqlite3_bind_int64(statement, 1, Int64(rating))
        sqlite3_bind_int64(statement, 2, sampleId)
        guard sqlite3_step(statement) == SQLITE_DONE else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
    }

    /// The full tag vocabulary, for recognizing an exact tag name typed into
    /// the search box (see SearchQueryParser) -- distinct from tagCounts,
    /// which is scoped to the current filter and excludes selected tags.
    public func allTagNames() throws -> Set<String> {
        let sql = "SELECT name FROM tags"
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        var result: Set<String> = []
        while sqlite3_step(statement) == SQLITE_ROW {
            if let cString = sqlite3_column_text(statement, 0) {
                result.insert(String(cString: cString))
            }
        }
        return result
    }

    /// Every given sample's tags in one query, grouped by sample id. Doing
    /// this per-row inside `search`'s step loop is what made a broad search
    /// slow once the library passed ~20k samples -- one prepare/step/finalize
    /// per result adds up far faster than the row scan itself.
    ///
    /// Samples with no tags are simply absent from the result; callers
    /// substitute an empty array.
    private func fetchTags(forSampleIds sampleIds: [Int64]) throws -> [Int64: [String]] {
        // One bound parameter per id, and SQLite caps those per statement
        // (SQLITE_MAX_VARIABLE_NUMBER). The browser only ever asks for a page
        // at a time, but an unlimited search() can hand us the whole library,
        // so chunk rather than depend on the caller staying small.
        var result: [Int64: [String]] = [:]
        for chunk in stride(from: 0, to: sampleIds.count, by: Self.maxBindParameters) {
            let slice = Array(sampleIds[chunk..<min(chunk + Self.maxBindParameters, sampleIds.count)])
            result.merge(try fetchTagsChunk(forSampleIds: slice)) { existing, _ in existing }
        }
        return result
    }

    /// Conservative: SQLite's compile-time default was 999 before 3.32.
    private static let maxBindParameters = 900

    private func fetchTagsChunk(forSampleIds sampleIds: [Int64]) throws -> [Int64: [String]] {
        guard !sampleIds.isEmpty else { return [:] }

        let placeholders = sampleIds.map { _ in "?" }.joined(separator: ",")
        let sql = """
        SELECT st.sample_id, t.name FROM tags t
        JOIN sample_tags st ON st.tag_id = t.id
        WHERE st.sample_id IN (\(placeholders))
        ORDER BY st.sample_id, t.name
        """
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        for (index, sampleId) in sampleIds.enumerated() {
            sqlite3_bind_int64(statement, Int32(index + 1), sampleId)
        }

        var result: [Int64: [String]] = [:]
        while sqlite3_step(statement) == SQLITE_ROW {
            guard let cString = sqlite3_column_text(statement, 1) else { continue }
            result[sqlite3_column_int64(statement, 0), default: []].append(String(cString: cString))
        }
        return result
    }

    // MARK: - Shared filter building (mirrors repository._base_filter on the Python side)

    private static func baseFilter(
        text: String?,
        tags: [String],
        excludedTags: [String] = [],
        freeTextTerms: [String] = [],
        excludedFreeTextTerms: [String] = [],
        bpmMin: Double?,
        bpmMax: Double?,
        musicalKey: String?,
        musicalKeyRootOnly: String? = nil
    ) -> (clauses: [String], bindings: [Bindable]) {
        var clauses = ["s.status = 'active'"]
        var bindings: [Bindable] = []

        // The live (not-yet-committed) search box text, plus one clause per
        // committed free-text chip -- each is its own AND'd condition, same
        // shape as a tag, which is what makes "cymatics kick 170bpm" work as
        // a composite search even though "cymatics" isn't an official tag.
        for term in ([text].compactMap { $0 } + freeTextTerms) where !term.isEmpty {
            clauses.append(
                "(s.cleaned_filename LIKE ? OR EXISTS (" +
                "SELECT 1 FROM sample_tags st JOIN tags t ON t.id = st.tag_id " +
                "WHERE st.sample_id = s.id AND t.name LIKE ?))"
            )
            let like = "%\(term)%"
            bindings.append(.text(like))
            bindings.append(.text(like))
        }
        // One negated clause per "!"-committed free-text chip -- excludes
        // any sample whose filename or tags substring-match the term,
        // mirroring the inclusion clause above but wrapped in NOT.
        for term in excludedFreeTextTerms where !term.isEmpty {
            clauses.append(
                "NOT (s.cleaned_filename LIKE ? OR EXISTS (" +
                "SELECT 1 FROM sample_tags st JOIN tags t ON t.id = st.tag_id " +
                "WHERE st.sample_id = s.id AND t.name LIKE ?))"
            )
            let like = "%\(term)%"
            bindings.append(.text(like))
            bindings.append(.text(like))
        }
        if !tags.isEmpty {
            let placeholders = tags.map { _ in "?" }.joined(separator: ",")
            clauses.append(
                "(SELECT COUNT(DISTINCT t.name) FROM sample_tags st JOIN tags t ON t.id = st.tag_id " +
                "WHERE st.sample_id = s.id AND t.name IN (\(placeholders))) = ?"
            )
            for tag in tags { bindings.append(.text(tag)) }
            bindings.append(.int(tags.count))
        }
        if !excludedTags.isEmpty {
            let placeholders = excludedTags.map { _ in "?" }.joined(separator: ",")
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM sample_tags st JOIN tags t ON t.id = st.tag_id " +
                "WHERE st.sample_id = s.id AND t.name IN (\(placeholders)))"
            )
            for tag in excludedTags { bindings.append(.text(tag)) }
        }
        if let bpmMin {
            clauses.append("s.bpm >= ?")
            bindings.append(.double(bpmMin))
        }
        if let bpmMax {
            clauses.append("s.bpm <= ?")
            bindings.append(.double(bpmMax))
        }
        if let musicalKey, !musicalKey.isEmpty {
            clauses.append("s.musical_key = ?")
            bindings.append(.text(musicalKey))
        }
        if let musicalKeyRootOnly, !musicalKeyRootOnly.isEmpty {
            // A bare root with no major/minor (e.g. searching "A") matches
            // either quality, but must not also match a different root's
            // accidental (e.g. "A" must not match "A#min").
            clauses.append("(s.musical_key = ? OR s.musical_key = ?)")
            bindings.append(.text("\(musicalKeyRootOnly)maj"))
            bindings.append(.text("\(musicalKeyRootOnly)min"))
        }

        return (clauses, bindings)
    }

    private static func bind(_ bindings: [Bindable], to statement: OpaquePointer?) {
        for (index, binding) in bindings.enumerated() {
            let position = Int32(index + 1)
            switch binding {
            case .text(let value):
                sqlite3_bind_text(statement, position, value, -1, SQLITE_TRANSIENT)
            case .double(let value):
                sqlite3_bind_double(statement, position, value)
            case .int(let value):
                sqlite3_bind_int64(statement, position, Int64(value))
            }
        }
    }
}

private enum Bindable {
    case text(String)
    case double(Double)
    case int(Int)
}

// sqlite3_bind_text needs an explicit "destructor" telling it whether to
// copy the string; SQLITE_TRANSIENT (-1 cast to the expected function
// pointer type) tells it to copy, since our Swift String's buffer isn't
// guaranteed to outlive the call.
private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

extension SampleRecord {
    /// column order must match the SELECT in Database.search(text:...)
    init(from statement: OpaquePointer, tags: [String]) {
        let id = sqlite3_column_int64(statement, 0)
        let currentPath = String(cString: sqlite3_column_text(statement, 1))
        let bucket = String(cString: sqlite3_column_text(statement, 2))
        let cleanedFilename = String(cString: sqlite3_column_text(statement, 3))
        let bpm = sqlite3_column_type(statement, 4) == SQLITE_NULL
            ? nil : sqlite3_column_double(statement, 4)
        let musicalKey = sqlite3_column_type(statement, 5) == SQLITE_NULL
            ? nil : String(cString: sqlite3_column_text(statement, 5))
        let duration = sqlite3_column_type(statement, 6) == SQLITE_NULL
            ? nil : sqlite3_column_double(statement, 6)
        let rating = Int(sqlite3_column_int64(statement, 7))

        self.init(
            id: id,
            currentPath: currentPath,
            bucket: bucket,
            cleanedFilename: cleanedFilename,
            bpm: bpm,
            musicalKey: musicalKey,
            durationSeconds: duration,
            tags: tags,
            rating: rating
        )
    }
}
