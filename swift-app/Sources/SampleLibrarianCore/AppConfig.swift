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

    /// Where the Python CLI's settings.toml can be found. The CLI's "real"
    /// home is config/settings.toml inside the code repo (which this app has
    /// no reliable way to locate -- it's just wherever the repo happens to be
    /// checked out), so triggering the CLI from here relies on a second
    /// convention: also keep a copy (or symlink) of settings.toml at the
    /// library root itself, which this app *does* always know how to find.
    /// Override with `SAMPLELIB_CONFIG_PATH` if that's inconvenient.
    public static var settingsPath: URL {
        if let override = ProcessInfo.processInfo.environment["SAMPLELIB_CONFIG_PATH"] {
            return URL(fileURLWithPath: override, isDirectory: false)
        }
        return libraryRoot.appendingPathComponent("settings.toml", isDirectory: false)
    }

    /// Override with `SAMPLELIB_CLI_PATH` if samplelib isn't at the default
    /// venv location (see CLAUDE.md's venv note).
    public static var cliExecutablePath: URL {
        if let override = ProcessInfo.processInfo.environment["SAMPLELIB_CLI_PATH"] {
            return URL(fileURLWithPath: override, isDirectory: false)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".venvs/sample-librarian/bin/samplelib", isDirectory: false)
    }
}
