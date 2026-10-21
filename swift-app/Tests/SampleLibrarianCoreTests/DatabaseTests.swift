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

    // MARK: - Paging (the browser loads results a page at a time)

    func testLimitAndOffsetWalkTheFullResultSetInSortOrder() throws {
        let db = try Database(path: dbURL)
        let all = try db.search(sort: .alphabetical)
        XCTAssertEqual(all.count, 5)

        var paged: [SampleRecord] = []
        for offset in stride(from: 0, to: all.count, by: 2) {
            paged += try db.search(sort: .alphabetical, limit: 2, offset: offset)
        }
        XCTAssertEqual(paged.map(\.id), all.map(\.id))
    }

    func testOffsetPastTheEndReturnsNothingRatherThanWrapping() throws {
        let db = try Database(path: dbURL)
        XCTAssertTrue(try db.search(limit: 10, offset: 99).isEmpty)
    }

    func testLimitAppliesAfterFiltering() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(text: "drum", sort: .alphabetical, limit: 2)
        XCTAssertEqual(results.map(\.cleanedFilename), ["Break Groove.wav", "Bright Hihat.wav"])
    }

    /// Guards the bulk tag fetch that replaced the per-row query inside
    /// search()'s result loop -- a paged result must still carry its tags.
    func testPagedResultsStillCarryTheirOwnTags() throws {
        let db = try Database(path: dbURL)
        let all = try db.search(sort: .alphabetical)
        let tagsById = Dictionary(uniqueKeysWithValues: all.map { ($0.id, $0.tags) })

        for offset in 0..<all.count {
            let page = try db.search(sort: .alphabetical, limit: 1, offset: offset)
            XCTAssertEqual(page.count, 1)
            XCTAssertEqual(page[0].tags, tagsById[page[0].id])
            XCTAssertFalse(page[0].tags.isEmpty)
        }
    }

    func testTagsComeBackSortedByName() throws {
        let db = try Database(path: dbURL)
        for sample in try db.search() {
            XCTAssertEqual(sample.tags, sample.tags.sorted())
        }
    }

    // MARK: - count (the "N samples" label, which ignores the page limit)

    func testCountMatchesUnlimitedSearchForEveryFilterShape() throws {
        let db = try Database(path: dbURL)
        XCTAssertEqual(try db.count(), try db.search().count)
        XCTAssertEqual(try db.count(text: "drum"), try db.search(text: "drum").count)
        XCTAssertEqual(try db.count(tags: ["drum", "kick"]), try db.search(tags: ["drum", "kick"]).count)
        XCTAssertEqual(try db.count(excludedTags: ["kick"]), try db.search(excludedTags: ["kick"]).count)
        XCTAssertEqual(try db.count(bpmMin: 100, bpmMax: 200), try db.search(bpmMin: 100, bpmMax: 200).count)
    }

    func testCountIsUnaffectedByThePageLimit() throws {
        let db = try Database(path: dbURL)
        XCTAssertEqual(try db.search(limit: 1).count, 1)
        XCTAssertEqual(try db.count(), 5)
    }

    func testTagCountsNoFiltersIsGlobalTagCloud() throws {
        let db = try Database(path: dbURL)
        let counts = Dictionary(uniqueKeysWithValues: try db.tagCounts().map { ($0.tag, $0.count) })
        XCTAssertEqual(counts["drum"], 3)  // kick + hihat + breakbeat
        XCTAssertEqual(counts["pad"], 1)
    }

    func testTagCountsReflectsCurrentFiltersForFacetedNarrowing() throws {
        let db = try Database(path: dbURL)
        let counts = Dictionary(uniqueKeysWithValues: try db.tagCounts(tags: ["drum"]).map { ($0.tag, $0.count) })
        XCTAssertNil(counts["pad"])  // no longer relevant once narrowed to drum-tagged samples
        XCTAssertNil(counts["drum"])  // already-selected tags aren't re-offered
        XCTAssertEqual(counts["one-shot"], 2)
    }

    func testDefaultSortIsRatingDescendingThenDateAdded() throws {
        let db = try Database(path: dbURL)
        let results = try db.search()
        // ratings: Kick=2, Hihat=-1, Pad=0, Break Groove=1, Song=0 (date_added tiebreaks the two 0s)
        XCTAssertEqual(results.map(\.cleanedFilename), ["Deep Kick.wav", "Break Groove.wav", "Some Song.mp3", "Ambient Pad.wav", "Bright Hihat.wav"])
    }

    func testSortByDateAdded() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(sort: .dateAdded)
        XCTAssertEqual(results.map(\.cleanedFilename), ["Break Groove.wav", "Some Song.mp3", "Bright Hihat.wav", "Ambient Pad.wav", "Deep Kick.wav"])
    }

    func testSortAlphabetical() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(sort: .alphabetical)
        XCTAssertEqual(results.map(\.cleanedFilename), ["Ambient Pad.wav", "Break Groove.wav", "Bright Hihat.wav", "Deep Kick.wav", "Some Song.mp3"])
    }

    func testSetRatingPersistsAndSurvivesReopen() throws {
        let db = try Database(path: dbURL)
        try db.setRating(sampleId: 3, rating: -2)

        let reopened = try Database(path: dbURL)
        let results = try reopened.search(text: "Ambient")
        XCTAssertEqual(results.first?.rating, -2)
    }

    func testSetRatingRejectsOutOfRange() throws {
        let db = try Database(path: dbURL)
        XCTAssertThrowsError(try db.setRating(sampleId: 1, rating: 3))
    }

    func testAllTagNamesReturnsFullVocabulary() throws {
        let db = try Database(path: dbURL)
        let names = try db.allTagNames()
        XCTAssertTrue(names.isSuperset(of: ["drum", "kick", "hihat", "pad", "song", "breakbeat"]))
    }

    func testSearchByRootOnlyKeyMatchesEitherQuality() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(musicalKeyRootOnly: "A")
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav"])  // Amin, not Cmaj
    }

    func testFreeTextTermsAreAndedTogetherLikeTags() throws {
        let db = try Database(path: dbURL)
        // "deep" matches only Deep Kick; "kick" (as a substring) also only
        // matches Deep Kick -- combined they should still just be that one,
        // not an OR across both.
        let results = try db.search(freeTextTerms: ["deep", "kick"])
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav"])

        let none = try db.search(freeTextTerms: ["deep", "hihat"])
        XCTAssertTrue(none.isEmpty)
    }

    func testFreeTextTermMatchesTagNameTooNotJustFilename() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(freeTextTerms: ["breakbeat"])
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Break Groove.wav"])
    }

    func testExcludedTagRemovesMatchingSamples() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(tags: ["drum"], excludedTags: ["kick"])
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Bright Hihat.wav", "Break Groove.wav"])
    }

    func testExcludedFreeTextTermRemovesFilenameAndTagMatches() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(excludedFreeTextTerms: ["kick"])
        XCTAssertFalse(results.map(\.cleanedFilename).contains("Deep Kick.wav"))
        XCTAssertEqual(results.count, 4)  // 5 active minus Deep Kick
    }

    func testTagCountsExcludesAlreadyExcludedTagFromAvailableFacets() throws {
        let db = try Database(path: dbURL)
        let counts = Dictionary(uniqueKeysWithValues: try db.tagCounts(excludedTags: ["kick"]).map { ($0.tag, $0.count) })
        XCTAssertNil(counts["kick"])
    }

    func testSortDirectionCanBeToggledAscending() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(sort: .dateAdded, direction: .ascending)
        XCTAssertEqual(results.map(\.cleanedFilename), ["Deep Kick.wav", "Ambient Pad.wav", "Bright Hihat.wav", "Some Song.mp3", "Break Groove.wav"])
    }

    func testSortByRandomReturnsAllActiveSamples() throws {
        let db = try Database(path: dbURL)
        let results = try db.search(sort: .random)
        XCTAssertEqual(Set(results.map(\.cleanedFilename)), ["Deep Kick.wav", "Break Groove.wav", "Some Song.mp3", "Ambient Pad.wav", "Bright Hihat.wav"])
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
            duration_seconds REAL, status TEXT DEFAULT 'active',
            rating INTEGER DEFAULT 0, date_added TEXT
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE sample_tags (sample_id INTEGER, tag_id INTEGER);

        INSERT INTO samples (id, current_path, bucket, cleaned_filename, bpm, musical_key, status, rating, date_added)
        VALUES
            (1, '/lib/unsorted/Deep Kick.wav', 'orphan', 'Deep Kick.wav', 95, 'Amin', 'active', 2, '2026-01-01T00:00:00Z'),
            (2, '/lib/unsorted/Bright Hihat.wav', 'orphan', 'Bright Hihat.wav', 140, NULL, 'active', -1, '2026-01-03T00:00:00Z'),
            (3, '/lib/unsorted/Ambient Pad.wav', 'orphan', 'Ambient Pad.wav', NULL, 'Cmaj', 'active', 0, '2026-01-02T00:00:00Z'),
            (4, '/lib/unsorted/Gone.wav', 'orphan', 'Gone.wav', NULL, NULL, 'missing', 0, '2026-01-01T00:00:00Z'),
            (5, '/lib/unsorted/Break Groove.wav', 'orphan', 'Break Groove.wav', 128, NULL, 'active', 1, '2026-01-05T00:00:00Z'),
            (6, '/lib/unsorted/Some Song.mp3', 'orphan', 'Some Song.mp3', NULL, NULL, 'active', 0, '2026-01-04T00:00:00Z');

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
