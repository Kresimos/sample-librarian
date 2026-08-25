import Foundation
import SQLite3

/// Read-only access to the shared library.sqlite3 (Python writes it, WAL
/// mode so this can read concurrently). Uses the raw SQLite3 C API directly
/// -- deliberately no external package dependency, so this builds without
/// network access to resolve one, and stays as light as the "not ADSR"
/// design goal wants.
public final class Database {
    private var handle: OpaquePointer?

    public enum DatabaseError: Error, CustomStringConvertible {
        case openFailed(String)
        case queryFailed(String)

        public var description: String {
            switch self {
            case .openFailed(let msg): return "Failed to open database: \(msg)"
            case .queryFailed(let msg): return "Query failed: \(msg)"
            }
        }
    }

    public init(path: URL) throws {
        // SQLITE_OPEN_READONLY: this process only ever reads. All writes
        // happen through the Python CLI (samplelib), which is the single
        // source of truth for the per-file pipeline logic.
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX
        if sqlite3_open_v2(path.path, &handle, flags, nil) != SQLITE_OK {
            let message = String(cString: sqlite3_errmsg(handle))
            sqlite3_close(handle)
            throw DatabaseError.openFailed(message)
        }
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
        bpmMin: Double? = nil,
        bpmMax: Double? = nil,
        musicalKey: String? = nil
    ) throws -> [SampleRecord] {
        let (clauses, bindings) = Self.baseFilter(text: text, tags: tags, bpmMin: bpmMin, bpmMax: bpmMax, musicalKey: musicalKey)

        let sql = """
        SELECT s.id, s.current_path, s.bucket, s.cleaned_filename,
               s.bpm, s.musical_key, s.duration_seconds
        FROM samples s
        WHERE \(clauses.joined(separator: " AND "))
        ORDER BY s.cleaned_filename
        """

        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        Self.bind(bindings, to: statement)

        var results: [SampleRecord] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            let sampleId = sqlite3_column_int64(statement, 0)
            results.append(SampleRecord(from: statement!, tags: try fetchTags(forSampleId: sampleId)))
        }
        return results
    }

    /// For faceted narrowing: given the same filters as `search`, how many
    /// matching samples have each tag? Already-selected tags are excluded
    /// (nothing to learn from re-showing them). Called with no filters at
    /// all, this is just the overall tag cloud.
    public func tagCounts(
        text: String? = nil,
        tags: [String] = [],
        bpmMin: Double? = nil,
        bpmMax: Double? = nil,
        musicalKey: String? = nil
    ) throws -> [(tag: String, count: Int)] {
        let (clauses, bindings) = Self.baseFilter(text: text, tags: tags, bpmMin: bpmMin, bpmMax: bpmMax, musicalKey: musicalKey)

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

        let alreadySelected = Set(tags)
        var results: [(String, Int)] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            guard let cString = sqlite3_column_text(statement, 0) else { continue }
            let tag = String(cString: cString)
            if alreadySelected.contains(tag) { continue }
            results.append((tag, Int(sqlite3_column_int64(statement, 1))))
        }
        return results
    }

    private func fetchTags(forSampleId sampleId: Int64) throws -> [String] {
        let sql = """
        SELECT t.name FROM tags t
        JOIN sample_tags st ON st.tag_id = t.id
        WHERE st.sample_id = ?
        ORDER BY t.name
        """
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        sqlite3_bind_int64(statement, 1, sampleId)

        var result: [String] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            if let cString = sqlite3_column_text(statement, 0) {
                result.append(String(cString: cString))
            }
        }
        return result
    }

    // MARK: - Shared filter building (mirrors repository._base_filter on the Python side)

    private static func baseFilter(
        text: String?,
        tags: [String],
        bpmMin: Double?,
        bpmMax: Double?,
        musicalKey: String?
    ) -> (clauses: [String], bindings: [Bindable]) {
        var clauses = ["s.status = 'active'"]
        var bindings: [Bindable] = []

        if let text, !text.isEmpty {
            clauses.append(
                "(s.cleaned_filename LIKE ? OR EXISTS (" +
                "SELECT 1 FROM sample_tags st JOIN tags t ON t.id = st.tag_id " +
                "WHERE st.sample_id = s.id AND t.name LIKE ?))"
            )
            let like = "%\(text)%"
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

        self.init(
            id: id,
            currentPath: currentPath,
            bucket: bucket,
            cleanedFilename: cleanedFilename,
            bpm: bpm,
            musicalKey: musicalKey,
            durationSeconds: duration,
            tags: tags
        )
    }
}
