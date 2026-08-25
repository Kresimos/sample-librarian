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

    public init(
        id: Int64,
        currentPath: String,
        bucket: String,
        cleanedFilename: String,
        bpm: Double?,
        musicalKey: String?,
        durationSeconds: Double?,
        tags: [String]
    ) {
        self.id = id
        self.currentPath = currentPath
        self.bucket = bucket
        self.cleanedFilename = cleanedFilename
        self.bpm = bpm
        self.musicalKey = musicalKey
        self.durationSeconds = durationSeconds
        self.tags = tags
    }

    /// The real on-disk file (vendor rows are symlinks; orphan rows are the
    /// real, moved file) -- resolved, per the drag-and-drop plan, so a drag
    /// payload never hands another app a symlink path.
    public var resolvedFileURL: URL {
        URL(fileURLWithPath: currentPath).resolvingSymlinksInPath()
    }
}
