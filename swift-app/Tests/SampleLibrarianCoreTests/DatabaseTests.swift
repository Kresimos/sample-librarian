import XCTest
import SQLite3
@testable import SampleLibrarianCore

final class DatabaseTests: XCTestCase {
    private var dbURL: URL!

    override func setUpWithError() throws {
        dbURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("sqlite3")
        try Self.createTestDatabase(at: dbURL)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dbURL)
    }

    func testSearchWithNoFiltersReturnsAllActive() throws {
        let db = try Database(path: dbURL)
        let results = try db.search()
        XCTAssertEqual(results.count, 5)  // 6 rows minus the 'missing' one
    }

    func testSearchByFreeTextMatchesFilename() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(text: "kick")
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav"])
    }

    func testSearchByFreeTextMatchesTag() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(text: "drum")
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav", "Bright Hihat.wav"])
    }

    func testSearchBySampleType() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(sampleType: "pad")
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Ambient Pad.wav"])
    }

    func testSearchByBpmRange() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(bpmMin: 100, bpmMax: 200)
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Bright Hihat.wav", "Break Groove.wav"])
    }

    func testSearchExcludesMissingStatus() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(text: "gone")
        XCTAssertTrue(results.isEmpty)
    }

    func testSearchByLoopType() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(loopType: "loop")
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Break Groove.wav"])
    }

    func testSongSampleTypeHasNoLoopType() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(sampleType: "song")
        XCTAssertEqual(results.count, 1)
        XCTAssertNil(results[0].loopType)
    }

    func testDistinctSampleTypes() throws {
        let db = try Database(path: dbURL)
        let types = try db.distinctSampleTypes()
        XCTAssertEqual(types, ["breakbeat", "hihat", "kick", "pad", "song"])
    }

    func testResolvedFileURLFollowsSymlink() throws {
        let realFile = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        FileManager.default.createFile(atPath: realFile.path, contents: Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: realFile) }

        let record = SampleRecord(
            id: 1, currentPath: realFile.path, bucket: "orphan", cleanedFilename: "x",
            sampleType: nil, loopType: nil, bpm: nil, musicalKey: nil, durationSeconds: nil, tags: []
        )
        XCTAssertEqual(record.resolvedFileURL.path, realFile.resolvingSymlinksInPath().path)
    }

    // MARK: - Test fixture DB builder (raw sqlite3 C API, mirrors schema.sql's shape)

    private static func createTestDatabase(at url: URL) throws {
        var handle: OpaquePointer?
        guard sqlite3_open(url.path, &handle) == SQLITE_OK else {
            throw NSError(domain: "test", code: 1)
        }
        defer { sqlite3_close(handle) }

        let schema = """
        CREATE TABLE samples (
            id INTEGER PRIMARY KEY, current_path TEXT, bucket TEXT,
            cleaned_filename TEXT, sample_type TEXT, loop_type TEXT, bpm REAL, musical_key TEXT,
            duration_seconds REAL, status TEXT DEFAULT 'active'
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE sample_tags (sample_id INTEGER, tag_id INTEGER);

        INSERT INTO samples (id, current_path, bucket, cleaned_filename, sample_type, loop_type, bpm, musical_key, status)
        VALUES
            (1, '/lib/unsorted/Deep Kick.wav', 'orphan', 'Deep Kick.wav', 'kick', 'one-shot', 95, 'Amin', 'active'),
            (2, '/lib/unsorted/Bright Hihat.wav', 'orphan', 'Bright Hihat.wav', 'hihat', 'one-shot', 140, NULL, 'active'),
            (3, '/lib/unsorted/Ambient Pad.wav', 'orphan', 'Ambient Pad.wav', 'pad', NULL, NULL, 'Cmaj', 'active'),
            (4, '/lib/unsorted/Gone.wav', 'orphan', 'Gone.wav', 'kick', 'one-shot', NULL, NULL, 'missing'),
            (5, '/lib/unsorted/Break Groove.wav', 'orphan', 'Break Groove.wav', 'breakbeat', 'loop', 128, NULL, 'active'),
            (6, '/lib/unsorted/Some Song.mp3', 'orphan', 'Some Song.mp3', 'song', NULL, NULL, NULL, 'active');

        INSERT INTO tags (id, name) VALUES (1, 'drum'), (2, 'one-shot'), (3, 'ambient');
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (1, 1), (1, 2), (2, 1), (2, 2), (3, 3);
        """

        var errorMessage: UnsafeMutablePointer<Int8>?
        guard sqlite3_exec(handle, schema, nil, nil, &errorMessage) == SQLITE_OK else {
            let message = errorMessage.map { String(cString: $0) } ?? "unknown error"
            sqlite3_free(errorMessage)
            throw NSError(domain: "test", code: 2, userInfo: [NSLocalizedDescriptionKey: message])
        }
    }
}
