import XCTest
@testable import SampleLibrarianCore

final class SearchQueryParserTests: XCTestCase {
    let knownTags: Set<String> = ["kick", "drum", "synth", "loop"]

    func testRecognizesExactKnownTagCaseInsensitive() {
        let token = SearchQueryParser.recognizeToken("Kick", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .tag("kick"))
    }

    func testUnknownWordIsNotRecognized() {
        XCTAssertNil(SearchQueryParser.recognizeToken("banjo", knownTags: knownTags))
    }

    func testSingleBpmValue() {
        let token = SearchQueryParser.recognizeToken("170bpm", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .bpmRange(min: 170, max: 170))
        XCTAssertEqual(token?.displayLabel, "170bpm")
    }

    func testBpmIsCaseInsensitive() {
        let token = SearchQueryParser.recognizeToken("140BPM", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .bpmRange(min: 140, max: 140))
    }

    func testBpmRange() {
        let token = SearchQueryParser.recognizeToken("160-170bpm", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .bpmRange(min: 160, max: 170))
        XCTAssertEqual(token?.displayLabel, "160-170bpm")
    }

    func testBpmRangeNormalizesReversedOrder() {
        let token = SearchQueryParser.recognizeToken("170-160bpm", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .bpmRange(min: 160, max: 170))
    }

    func testKeyWithMinorQuality() {
        let token = SearchQueryParser.recognizeToken("Amin", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "Amin", rootOnly: nil))
    }

    func testKeyIsCaseInsensitive() {
        let token = SearchQueryParser.recognizeToken("amin", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "Amin", rootOnly: nil))
    }

    func testKeyWithMajorQuality() {
        let token = SearchQueryParser.recognizeToken("Amaj", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "Amaj", rootOnly: nil))
    }

    func testBareRootNoteIsRootOnlyKey() {
        let token = SearchQueryParser.recognizeToken("A", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: nil, rootOnly: "A"))
    }

    func testSharpAccidentalKey() {
        let token = SearchQueryParser.recognizeToken("F#min", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "F#min", rootOnly: nil))
    }

    func testFlatAccidentalKeyRootOnly() {
        let token = SearchQueryParser.recognizeToken("Bb", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: nil, rootOnly: "Bb"))
    }

    func testShortMQualitySuffixNormalizesToMinor() {
        let token = SearchQueryParser.recognizeToken("Cm", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "Cmin", rootOnly: nil))
    }

    func testGarbageStartingWithNoteLetterIsNotAKey() {
        XCTAssertNil(SearchQueryParser.recognizeToken("grip", knownTags: knownTags))
    }

    func testCommitTokensConvertsEveryWordIncludingUnrecognizedOnes() {
        let filters = SearchQueryParser.commitTokens("kick 170bpm dark Amin", knownTags: knownTags)
        XCTAssertEqual(filters, [
            .officialTag("kick"),
            .bpmRange(min: 170, max: 170, label: "170bpm"),
            .freeText("dark"),
            .key(exact: "Amin", rootOnly: nil, label: "Amin"),
        ])
    }

    func testCommitTokensWithNothingRecognizedIsAllFreeText() {
        let filters = SearchQueryParser.commitTokens("some random phrase", knownTags: knownTags)
        XCTAssertEqual(filters, [.freeText("some"), .freeText("random"), .freeText("phrase")])
    }

    func testFreeTextFilterIsNotAnOfficialTag() {
        XCTAssertFalse(CommittedFilter.freeText("cymatics").isOfficialTag)
        XCTAssertTrue(CommittedFilter.officialTag("kick").isOfficialTag)
    }

    // MARK: - Negative search ("!kick")

    func testBangPrefixOnKnownTagCommitsAnExcludedTag() {
        let filters = SearchQueryParser.commitTokens("!kick", knownTags: knownTags)
        XCTAssertEqual(filters, [.excludedTag("kick")])
    }

    func testBangPrefixOnKnownTagIsCaseInsensitive() {
        let filters = SearchQueryParser.commitTokens("!Kick", knownTags: knownTags)
        XCTAssertEqual(filters, [.excludedTag("kick")])
    }

    func testBangPrefixOnUnknownWordCommitsExcludedFreeText() {
        let filters = SearchQueryParser.commitTokens("!cymatics", knownTags: knownTags)
        XCTAssertEqual(filters, [.excludedFreeText("cymatics")])
    }

    func testBangPrefixCombinesWithOrdinaryFiltersInOneCommit() {
        let filters = SearchQueryParser.commitTokens("drum !kick", knownTags: knownTags)
        XCTAssertEqual(filters, [.officialTag("drum"), .excludedTag("kick")])
    }

    func testExcludedFiltersAreMarkedIsExcludedAndNotOfficialTag() {
        XCTAssertTrue(CommittedFilter.excludedTag("kick").isExcluded)
        XCTAssertTrue(CommittedFilter.excludedFreeText("cymatics").isExcluded)
        XCTAssertFalse(CommittedFilter.excludedTag("kick").isOfficialTag)
        XCTAssertFalse(CommittedFilter.officialTag("kick").isExcluded)
    }

    func testExcludedTagDisplayLabelKeepsBangPrefix() {
        XCTAssertEqual(CommittedFilter.excludedTag("kick").displayLabel, "!kick")
        XCTAssertEqual(CommittedFilter.excludedFreeText("cymatics").displayLabel, "!cymatics")
    }

    // MARK: - Key prefix ("KeyAmin")

    func testKeyPrefixNoSeparator() {
        let token = SearchQueryParser.recognizeToken("KeyAmin", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "Amin", rootOnly: nil))
    }

    func testKeyPrefixWithDashSeparator() {
        let token = SearchQueryParser.recognizeToken("Key-Fmin", knownTags: knownTags)
        XCTAssertEqual(token?.kind, .key(exact: "Fmin", rootOnly: nil))
    }

    func testKeyPrefixDoesNotFalsePositiveOnKeyboard() {
        XCTAssertNil(SearchQueryParser.recognizeToken("Keyboard", knownTags: knownTags))
    }

    // MARK: - Tag synonyms

    let dnbKnownTags: Set<String> = ["dnb", "kick", "hihat"]

    func testWordSynonymResolvesToCanonicalTag() {
        let token = SearchQueryParser.recognizeToken("jungle", knownTags: dnbKnownTags)
        XCTAssertEqual(token?.kind, .tag("dnb"))
    }

    func testConcatenatedCamelCaseSynonymResolvesViaExplicitEntry() {
        let token = SearchQueryParser.recognizeToken("DrumNBass", knownTags: dnbKnownTags)
        XCTAssertEqual(token?.kind, .tag("dnb"))
    }

    func testSimplePluralOfKnownTagResolves() {
        let token = SearchQueryParser.recognizeToken("kicks", knownTags: dnbKnownTags)
        XCTAssertEqual(token?.kind, .tag("kick"))
    }

    func testCommitTokensCollapsesMultiWordPhraseIntoOneTagChip() {
        let filters = SearchQueryParser.commitTokens("drum and bass", knownTags: dnbKnownTags)
        XCTAssertEqual(filters, [.officialTag("dnb")])
    }

    func testCommitTokensCollapsesConcatenatedCamelCasePhraseIntoOneTagChip() {
        let filters = SearchQueryParser.commitTokens("DrumNBass", knownTags: dnbKnownTags)
        XCTAssertEqual(filters, [.officialTag("dnb")])
    }

    func testCommitTokensHandlesAmpersandPhraseVariant() {
        let filters = SearchQueryParser.commitTokens("drum & bass", knownTags: dnbKnownTags)
        XCTAssertEqual(filters, [.officialTag("dnb")])
    }

    func testCommitTokensPhraseMatchLeavesSurroundingWordsIntact() {
        let filters = SearchQueryParser.commitTokens("dark drum and bass 170bpm", knownTags: dnbKnownTags)
        XCTAssertEqual(filters, [
            .freeText("dark"),
            .officialTag("dnb"),
            .bpmRange(min: 170, max: 170, label: "170bpm"),
        ])
    }
}
