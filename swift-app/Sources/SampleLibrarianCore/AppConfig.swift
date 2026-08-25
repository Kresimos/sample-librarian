import Foundation

/// Resolves where the shared library lives. Deliberately doesn't parse the
/// Python side's settings.toml (that file lives inside the code repo, which
/// isn't a reliable thing for a standalone launched .app to locate) --
/// instead this uses the confirmed default library_root, overridable via
/// environment variable for development/testing.
public enum AppConfig {
    /// Override with `SAMPLELIB_LIBRARY_ROOT=/some/path` when running via
    /// `swift run` for local testing against a scratch library.
    public static var libraryRoot: URL {
        if let override = ProcessInfo.processInfo.environment["SAMPLELIB_LIBRARY_ROOT"] {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
            "SampleLibrary", isDirectory: true
        )
    }

    public static var databasePath: URL {
        libraryRoot.appendingPathComponent("db/library.sqlite3", isDirectory: false)
    }
}
