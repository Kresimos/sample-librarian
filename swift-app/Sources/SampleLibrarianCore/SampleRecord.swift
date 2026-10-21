import Foundation

/// Mirrors a row of the `samples` table (see db/schema.sql on the Python
/// side). Only the fields the browser/search UI actually needs.
///
/// There's no separate type/loop-type field -- everything (instrument,
/// drum/melodic/vocal/fx, loop vs one-shot, "song", "app-foley") is just a
/// tag, matching the Python side's classify/classifier.py.
public struct SampleRecord: Identifiable, Hashable, Sendable {
    public let id: Int64
    public let currentPath: String
    public let bucket: String  // "vendor" | "orphan"
    public let cleanedFilename: String
    public let bpm: Double?
    public let musicalKey: String?
    public let durationSeconds: Double?
    public let tags: [String]
    /// User-set from the browser, -2...+2. Never touched by a rescan (see
    /// db/schema.sql / repository.upsert_sample on the Python side).
    public let rating: Int

    public init(
        id: Int64,
        currentPath: String,
        bucket: String,
        cleanedFilename: String,
        bpm: Double?,
        musicalKey: String?,
        durationSeconds: Double?,
        tags: [String],
        rating: Int = 0
    ) {
        self.id = id
        self.currentPath = currentPath
        self.bucket = bucket
        self.cleanedFilename = cleanedFilename
        self.bpm = bpm
        self.musicalKey = musicalKey
        self.durationSeconds = durationSeconds
        self.tags = tags
        self.rating = rating
    }

    /// A copy with a different rating -- used for optimistic local updates
    /// right after a keyboard rating change, before/without a full reload.
    public func withRating(_ newRating: Int) -> SampleRecord {
        SampleRecord(
            id: id, currentPath: currentPath, bucket: bucket, cleanedFilename: cleanedFilename,
            bpm: bpm, musicalKey: musicalKey, durationSeconds: durationSeconds, tags: tags, rating: newRating
        )
    }

    /// A copy carrying these tags -- how `Database.search` attaches the tags
    /// it fetches in one grouped query after the rows themselves are read,
    /// rather than querying per row inside the result loop.
    public func withTags(_ newTags: [String]) -> SampleRecord {
        SampleRecord(
            id: id, currentPath: currentPath, bucket: bucket, cleanedFilename: cleanedFilename,
            bpm: bpm, musicalKey: musicalKey, durationSeconds: durationSeconds, tags: newTags, rating: rating
        )
    }

    /// Length expressed in beats (duration / (60/bpm)), when both duration
    /// and tempo are known -- nil (not zero) when either is missing, so
    /// callers can distinguish "unknown" from "silent"/zero-length.
    public var beatCount: Double? {
        guard let bpm, bpm > 0, let durationSeconds else { return nil }
        return durationSeconds * bpm / 60.0
    }

    /// The real on-disk file (vendor rows are symlinks; orphan rows are the
    /// real, moved file) -- resolved, per the drag-and-drop plan, so a drag
    /// payload never hands another app a symlink path.
    public var resolvedFileURL: URL {
        URL(fileURLWithPath: currentPath).resolvingSymlinksInPath()
    }
}
