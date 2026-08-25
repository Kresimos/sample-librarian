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
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav", "Bright Hihat.wav", "Break Groove.wav"])
    }

    func testSearchBySingleTag() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(tags: ["pad"])
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Ambient Pad.wav"])
    }

    func testSearchByMultipleTagsRequiresAll() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(tags: ["drum", "kick"])
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav"])

        let none = try db.search(tags: ["kick", "pad"])
        XCTAssertTrue(none.isEmpty)
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

    func testSongTaggedSampleHasNoLoopOrOneShotTag() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(tags: ["song"])
        XCTAssertEqual(results.count, 1)
        XCTAssertFalse(results[0].tags.contains("loop"))
        XCTAssertFalse(results[0].tags.contains("one-shot"))
    }

    func testTagCountsNoFiltersIsGlobalTagCloud() throws {
        let db = try Database(path: dbURL)
        let counts = Dictionary(uniqueKeysWithValues: try db.tagCounts())
        XCTAssertEqual(counts["drum"], 3)  // kick + hihat + breakbeat
        XCTAssertEqual(counts["pad"], 1)
    }

    func testTagCountsReflectsCurrentFiltersForFacetedNarrowing() throws {
        let db = try Database(path: dbURL)
        let counts = Dictionary(uniqueKeysWithValues: try db.tagCounts(tags: ["drum"]))
        XCTAssertNil(counts["pad"])  // no longer relevant once narrowed to drum-tagged samples
        XCTAssertNil(counts["drum"])  // already-selected tags aren't re-offered
        XCTAssertEqual(counts["one-shot"], 2)
    }

    func testResolvedFileURLFollowsSymlink() throws {
        let realFile = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        FileManager.default.createFile(atPath: realFile.path, contents: Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: realFile) }

        let record = SampleRecord(
            id: 1, currentPath: realFile.path, bucket: "orphan", cleanedFilename: "x",
            bpm: nil, musicalKey: nil, durationSeconds: nil, tags: []
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
            cleaned_filename TEXT, bpm REAL, musical_key TEXT,
            duration_seconds REAL, status TEXT DEFAULT 'active'
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE sample_tags (sample_id INTEGER, tag_id INTEGER);

        INSERT INTO samples (id, current_path, bucket, cleaned_filename, bpm, musical_key, status)
        VALUES
            (1, '/lib/unsorted/Deep Kick.wav', 'orphan', 'Deep Kick.wav', 95, 'Amin', 'active'),
            (2, '/lib/unsorted/Bright Hihat.wav', 'orphan', 'Bright Hihat.wav', 140, NULL, 'active'),
            (3, '/lib/unsorted/Ambient Pad.wav', 'orphan', 'Ambient Pad.wav', NULL, 'Cmaj', 'active'),
            (4, '/lib/unsorted/Gone.wav', 'orphan', 'Gone.wav', NULL, NULL, 'missing'),
            (5, '/lib/unsorted/Break Groove.wav', 'orphan', 'Break Groove.wav', 128, NULL, 'active'),
            (6, '/lib/unsorted/Some Song.mp3', 'orphan', 'Some Song.mp3', NULL, NULL, 'active');

        INSERT INTO tags (id, name) VALUES
            (1, 'drum'), (2, 'one-shot'), (3, 'ambient'), (4, 'kick'), (5, 'hihat'),
            (6, 'pad'), (7, 'melodic'), (8, 'synth'), (9, 'breakbeat'), (10, 'loop'), (11, 'song');

        -- kick: drum, one-shot, kick
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (1, 1), (1, 2), (1, 4);
        -- hihat: drum, one-shot, hihat
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (2, 1), (2, 2), (2, 5);
        -- pad: pad, melodic, synth, ambient
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (3, 6), (3, 7), (3, 8), (3, 3);
        -- gone (missing): kick, one-shot -- must never surface via search
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (4, 4), (4, 2);
        -- breakbeat loop: breakbeat, drum, loop
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (5, 9), (5, 1), (5, 10);
        -- song: just 'song', no loop/one-shot
        INSERT INTO sample_tags (sample_id, tag_id) VALUES (6, 11);
        """

        var errorMessage: UnsafeMutablePointer<Int8>?
        guard sqlite3_exec(handle, schema, nil, nil, &errorMessage) == SQLITE_OK else {
            let message = errorMessage.map { String(cString: $0) } ?? "unknown error"
            sqlite3_free(errorMessage)
            throw NSError(domain: "test", code: 2, userInfo: [NSLocalizedDescriptionKey: message])
        }
    }
}
