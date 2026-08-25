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
    /// for why this isn't FTS5).
    public func search(
        text: String? = nil,
        sampleType: String? = nil,
        loopType: String? = nil,
        bpmMin: Double? = nil,
        bpmMax: Double? = nil,
        musicalKey: String? = nil
    ) throws -> [SampleRecord] {
        var clauses = ["s.status = 'active'"]
        var bindings: [Bindable] = []

        if let text, !text.isEmpty {
            clauses.append(
                "(s.cleaned_filename LIKE ? OR s.sample_type LIKE ? OR EXISTS (" +
                "SELECT 1 FROM sample_tags st JOIN tags t ON t.id = st.tag_id " +
                "WHERE st.sample_id = s.id AND t.name LIKE ?))"
            )
            let like = "%\(text)%"
            bindings.append(.text(like))
            bindings.append(.text(like))
            bindings.append(.text(like))
        }
        if let sampleType, !sampleType.isEmpty {
            clauses.append("s.sample_type = ?")
            bindings.append(.text(sampleType))
        }
        if let loopType, !loopType.isEmpty {
            clauses.append("s.loop_type = ?")
            bindings.append(.text(loopType))
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

        let sql = """
        SELECT s.id, s.current_path, s.bucket, s.cleaned_filename, s.sample_type,
               s.loop_type, s.bpm, s.musical_key, s.duration_seconds
        FROM samples s
        WHERE \(clauses.joined(separator: " AND "))
        ORDER BY s.cleaned_filename
        """

        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }

        for (index, binding) in bindings.enumerated() {
            let position = Int32(index + 1)
            switch binding {
            case .text(let value):
                sqlite3_bind_text(statement, position, value, -1, SQLITE_TRANSIENT)
            case .double(let value):
                sqlite3_bind_double(statement, position, value)
            }
        }

        var results: [SampleRecord] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            results.append(SampleRecord(from: statement!, tags: try tags(forSampleId: sqlite3_column_int64(statement, 0))))
        }
        return results
    }

    private func tags(forSampleId sampleId: Int64) throws -> [String] {
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

        var tags: [String] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            if let cString = sqlite3_column_text(statement, 0) {
                tags.append(String(cString: cString))
            }
        }
        return tags
    }

    /// Distinct sample_type values currently in the library, for populating
    /// a type filter dropdown.
    public func distinctSampleTypes() throws -> [String] {
        let sql = "SELECT DISTINCT sample_type FROM samples WHERE sample_type IS NOT NULL AND status = 'active' ORDER BY sample_type"
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError.queryFailed(String(cString: sqlite3_errmsg(handle)))
        }
        var types: [String] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            if let cString = sqlite3_column_text(statement, 0) {
                types.append(String(cString: cString))
            }
        }
        return types
    }
}

private enum Bindable {
    case text(String)
    case double(Double)
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
        let sampleType = sqlite3_column_type(statement, 4) == SQLITE_NULL
            ? nil : String(cString: sqlite3_column_text(statement, 4))
        let loopType = sqlite3_column_type(statement, 5) == SQLITE_NULL
            ? nil : String(cString: sqlite3_column_text(statement, 5))
        let bpm = sqlite3_column_type(statement, 6) == SQLITE_NULL
            ? nil : sqlite3_column_double(statement, 6)
        let musicalKey = sqlite3_column_type(statement, 7) == SQLITE_NULL
            ? nil : String(cString: sqlite3_column_text(statement, 7))
        let duration = sqlite3_column_type(statement, 8) == SQLITE_NULL
            ? nil : sqlite3_column_double(statement, 8)

        self.init(
            id: id,
            currentPath: currentPath,
            bucket: bucket,
            cleanedFilename: cleanedFilename,
            sampleType: sampleType,
            loopType: loopType,
            bpm: bpm,
            musicalKey: musicalKey,
            durationSeconds: duration,
            tags: tags
        )
    }
}
