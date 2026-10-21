import Foundation

/// A single committed search-box term, once Enter has been pressed. Every
/// word typed becomes one of these -- there's no "unrecognized, do nothing"
/// case anymore: a word that isn't an official tag/bpm/key just becomes a
/// `.freeText` filter, which still narrows results (filename or tag
/// substring match) and still ANDs with everything else, matching AND
/// semantics of real tags. This is what lets composite searches like
/// "cymatics kick 170bpm" work even though "cymatics" isn't in the taxonomy.
public enum CommittedFilter: Identifiable, Equatable, Sendable {
    case officialTag(String)
    /// A tag prefixed with "!" on commit (e.g. "!kick") -- samples carrying
    /// this tag are excluded rather than required. See classifyForCommit.
    case excludedTag(String)
    case freeText(String)
    /// A non-tag word prefixed with "!" -- excludes samples whose filename
    /// or tags substring-match this term, the negated mirror of `.freeText`.
    case excludedFreeText(String)
    case bpmRange(min: Double, max: Double, label: String)
    case key(exact: String?, rootOnly: String?, label: String)

    /// Stable identity for list diffing/dedup -- one bpm/key filter replaces
    /// any previous one of the same category (see BrowserViewModel), so
    /// those two ids are constant regardless of value.
    public var id: String {
        switch self {
        case .officialTag(let tag): return "tag:\(tag)"
        case .excludedTag(let tag): return "extag:\(tag)"
        case .freeText(let text): return "text:\(text)"
        case .excludedFreeText(let text): return "extext:\(text)"
        case .bpmRange: return "bpm"
        case .key: return "key"
        }
    }

    public var displayLabel: String {
        switch self {
        case .officialTag(let tag): return tag
        case .excludedTag(let tag): return "!\(tag)"
        case .freeText(let text): return text
        case .excludedFreeText(let text): return "!\(text)"
        case .bpmRange(_, _, let label): return label
        case .key(_, _, let label): return label
        }
    }

    public var isOfficialTag: Bool {
        if case .officialTag = self { return true }
        return false
    }

    /// Whether this filter narrows results by exclusion ("!kick") rather
    /// than requiring a match -- used by SearchFilterBar to render excluded
    /// chips in a distinct (red) color from included tag/free-text chips.
    public var isExcluded: Bool {
        switch self {
        case .excludedTag, .excludedFreeText: return true
        case .officialTag, .freeText, .bpmRange, .key: return false
        }
    }
}

/// Recognizes structured filter tokens typed into the single search box
/// ("kick", "170bpm", "160-170bpm", "Amin", "amin", "A", "Amaj") so pressing
/// Enter can promote them into removable filter chips, the same way clicking
/// a facet chip does -- see BrowserViewModel. A word that isn't an official
/// tag/bpm/key still becomes a chip (a "free text" one, see CommittedFilter)
/// rather than being dropped -- every search term is taggable.
public enum SearchQueryParser {
    public struct RecognizedToken: Equatable {
        public enum Kind: Equatable {
            case tag(String)
            case bpmRange(min: Double, max: Double)
            /// Exactly one of exact/rootOnly is set: a full key ("Amin") is
            /// an exact match; a bare root ("A") matches either quality.
            case key(exact: String?, rootOnly: String?)
        }
        public let kind: Kind
        /// What to show on the resulting chip, e.g. "170bpm", "160-170bpm", "Amin", "A".
        public let displayLabel: String
    }

    /// Splits `text` on whitespace and converts every token into a
    /// CommittedFilter -- used on Enter, when the whole search box gets
    /// committed to chips at once. Unlike `parse`, nothing is left over:
    /// an unrecognized word becomes `.freeText` rather than being dropped.
    ///
    /// Before splitting, a concatenated multi-word alias typed with no
    /// spaces (e.g. "DrumNBass") is split at its camelCase boundaries, and
    /// "&" is normalized to "and" -- both so a phrase like "drum n bass" or
    /// "drum and bass" can be recognized the same way whether it arrived as
    /// one run-together word or as several separately-typed ones. Once
    /// split, consecutive words are matched against `TagSynonyms.phraseSynonyms`
    /// greedily (longest phrase first) before falling back to per-word
    /// classification, so "drum and bass" collapses to one `dnb` chip
    /// instead of three separate free-text chips.
    public static func commitTokens(_ text: String, knownTags: Set<String>) -> [CommittedFilter] {
        let words = camelSplit(text)
            .split(separator: " ", omittingEmptySubsequences: true)
            .map { $0 == "&" ? "and" : String($0) }

        var result: [CommittedFilter] = []
        var i = 0
        while i < words.count {
            if let (tag, consumed) = matchPhraseSynonym(words, at: i) {
                result.append(.officialTag(tag))
                i += consumed
                continue
            }
            result.append(classifyForCommit(words[i], knownTags: knownTags))
            i += 1
        }
        return result
    }

    /// Splits camelCase/PascalCase runs into separate words, e.g. "DrumNBass"
    /// -> "Drum N Bass". Mirrors classifier.py's `_CAMEL_BOUNDARY` on the
    /// Python (classification-time) side -- see that file for why two rules
    /// are needed (a single capital standing in for its own word, like the
    /// "N" in "DrumNBass", is itself all-caps and needs the second rule to split).
    private static let camelBoundaryRegex = try! NSRegularExpression(
        pattern: "(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
    )

    private static func camelSplit(_ text: String) -> String {
        let range = NSRange(text.startIndex..., in: text)
        return camelBoundaryRegex.stringByReplacingMatches(in: text, range: range, withTemplate: " ")
    }

    /// Tries the longest phrase (3 words, then 2) starting at `index` against
    /// `TagSynonyms.phraseSynonyms`. Returns the matched tag and how many
    /// words it consumed, or nil if nothing matched.
    private static func matchPhraseSynonym(_ words: [String], at index: Int) -> (tag: String, consumed: Int)? {
        let maxLength = min(3, words.count - index)
        guard maxLength >= 2 else { return nil }
        for length in stride(from: maxLength, through: 2, by: -1) {
            let phrase = words[index..<(index + length)].joined(separator: " ").lowercased()
            if let tag = TagSynonyms.phraseSynonyms[phrase] {
                return (tag, length)
            }
        }
        return nil
    }

    /// A "!"-prefixed token (e.g. "!kick", "!cymatics") commits to an
    /// exclusion filter instead of an inclusion one. Only tag/free-text
    /// negation is supported -- a "!" in front of something that would
    /// otherwise parse as a bpm/key token (e.g. "!170bpm") just falls back
    /// to excluding that literal substring, same as any other unrecognized
    /// negated word, since "exclude this bpm range" isn't what "!" implies
    /// here.
    public static func classifyForCommit(_ rawToken: String, knownTags: Set<String>) -> CommittedFilter {
        let token = rawToken.trimmingCharacters(in: .whitespaces)
        if token.hasPrefix("!") {
            let inner = String(token.dropFirst()).trimmingCharacters(in: .whitespaces)
            guard !inner.isEmpty else { return .freeText(token) }
            if let recognized = recognizeToken(inner, knownTags: knownTags), case .tag(let tag) = recognized.kind {
                return .excludedTag(tag)
            }
            return .excludedFreeText(inner)
        }
        if let recognized = recognizeToken(token, knownTags: knownTags) {
            switch recognized.kind {
            case .tag(let tag): return .officialTag(tag)
            case .bpmRange(let min, let max): return .bpmRange(min: min, max: max, label: recognized.displayLabel)
            case .key(let exact, let rootOnly): return .key(exact: exact, rootOnly: rootOnly, label: recognized.displayLabel)
            }
        }
        return .freeText(token)
    }

    public static func recognizeToken(_ rawToken: String, knownTags: Set<String>) -> RecognizedToken? {
        let token = rawToken.trimmingCharacters(in: .whitespaces)
        guard !token.isEmpty else { return nil }

        if knownTags.contains(token.lowercased()) {
            return RecognizedToken(kind: .tag(token.lowercased()), displayLabel: token.lowercased())
        }
        if let bpm = parseBPM(token) {
            let label = bpm.min == bpm.max ? "\(Int(bpm.min))bpm" : "\(Int(bpm.min))-\(Int(bpm.max))bpm"
            return RecognizedToken(kind: .bpmRange(min: bpm.min, max: bpm.max), displayLabel: label)
        }
        if let key = parseKey(token) {
            return RecognizedToken(kind: .key(exact: key.exact, rootOnly: key.rootOnly), displayLabel: key.label)
        }
        if let tag = resolveWordSynonym(token, knownTags: knownTags) {
            return RecognizedToken(kind: .tag(tag), displayLabel: tag)
        }
        return nil
    }

    /// Resolves a single word to a tag via `TagSynonyms.wordSynonyms`, or a
    /// simple trailing-"s" plural of an already-known tag/synonym (mirrors
    /// classifier.py's `s?` plural tolerance, e.g. "claps" -> "clap").
    private static func resolveWordSynonym(_ token: String, knownTags: Set<String>) -> String? {
        let lower = token.lowercased()
        if let tag = TagSynonyms.wordSynonyms[lower] { return tag }
        if lower.hasSuffix("s"), lower.count > 1 {
            let singular = String(lower.dropLast())
            if knownTags.contains(singular) { return singular }
            if let tag = TagSynonyms.wordSynonyms[singular] { return tag }
        }
        return nil
    }

    // MARK: - BPM

    private static let bpmRangeRegex = try! NSRegularExpression(pattern: #"^(\d{2,3})\s*-\s*(\d{2,3})\s*bpm$"#, options: [.caseInsensitive])
    private static let bpmSingleRegex = try! NSRegularExpression(pattern: #"^(\d{2,3})\s*bpm$"#, options: [.caseInsensitive])

    private static func parseBPM(_ token: String) -> (min: Double, max: Double)? {
        let fullRange = NSRange(token.startIndex..., in: token)
        if let m = bpmRangeRegex.firstMatch(in: token, range: fullRange),
           let r1 = Range(m.range(at: 1), in: token), let r2 = Range(m.range(at: 2), in: token),
           let v1 = Double(token[r1]), let v2 = Double(token[r2]) {
            return (Swift.min(v1, v2), Swift.max(v1, v2))
        }
        if let m = bpmSingleRegex.firstMatch(in: token, range: fullRange),
           let r1 = Range(m.range(at: 1), in: token), let v1 = Double(token[r1]) {
            return (v1, v1)
        }
        return nil
    }

    // MARK: - Key
    // Mirrors sample_librarian.audio.filename_regex._normalize_key on the
    // Python side: canonical form is "{Letter}{#|b|}{min|maj}", e.g. "C#min".

    private static func parseKey(_ token: String) -> (exact: String?, rootOnly: String?, label: String)? {
        var chars = Array(token)
        // An explicit "key" prefix (KeyAmin, Key-Amin, Key_Amin) is an
        // unambiguous signal -- strip it (and one optional separator) before
        // the normal parse, mirroring filename_regex.py's _KEY_PREFIX.
        if chars.count > 3, String(chars[0..<3]).lowercased() == "key" {
            var rest = Array(chars[3...])
            if let sep = rest.first, sep == "-" || sep == "_" {
                rest.removeFirst()
            }
            chars = rest
        }
        guard let first = chars.first, ("A"..."G").contains(Character(first.uppercased())) else { return nil }

        var idx = 1
        var accidental = ""
        if idx < chars.count, chars[idx] == "#" {
            accidental = "#"
            idx += 1
        } else if idx < chars.count, chars[idx].lowercased() == "b" {
            accidental = "b"
            idx += 1
        }

        let root = "\(first.uppercased())\(accidental)"
        let qualityRaw = String(chars[idx...]).lowercased()

        if qualityRaw.isEmpty {
            return (exact: nil, rootOnly: root, label: root)
        }

        let quality: String
        switch qualityRaw {
        case "min", "minor", "m": quality = "min"
        case "maj", "major": quality = "maj"
        default: return nil  // trailing junk that isn't a recognized quality -> not a key token at all
        }
        let exact = root + quality
        return (exact: exact, rootOnly: nil, label: exact)
    }
}
