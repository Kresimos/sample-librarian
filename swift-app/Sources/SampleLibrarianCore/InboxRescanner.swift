import Foundation

/// Shells out to the Python CLI's `rescan-inbox` command rather than
/// reimplementing the per-file pipeline in Swift -- keeps exactly one
/// authoritative implementation of "what happens to a file" (see the
/// project plan). This is the GUI's "keep the library current" button.
public enum InboxRescanner {
    public struct Result: Sendable {
        public let succeeded: Bool
        public let output: String
    }

    public enum RescanError: Error, CustomStringConvertible {
        case cliNotFound(URL)
        case settingsNotFound(URL)
        case taxonomyNotFound(URL)

        public var description: String {
            switch self {
            case .cliNotFound(let url):
                return "samplelib CLI not found at \(url.path). Set SAMPLELIB_CLI_PATH if it's installed elsewhere."
            case .settingsNotFound(let url):
                return "settings.toml not found at \(url.path). Copy or symlink your config there, " +
                    "or set SAMPLELIB_CONFIG_PATH."
            case .taxonomyNotFound(let url):
                return "taxonomy.yaml not found at \(url.path). Copy or symlink it there, " +
                    "or set SAMPLELIB_TAXONOMY_PATH."
            }
        }
    }


    /// A GUI app launched from Finder inherits a bare `PATH`
    /// (`/usr/bin:/bin:/usr/sbin:/sbin`), not the login shell's -- so a child
    /// process can't find Homebrew binaries. The CLI shells out to `ffprobe`
    /// (`audio/probe.py`) for duration/samplerate on MP3/M4A/FLAC and raises
    /// `FfprobeNotFoundError` when `shutil.which` comes up empty, which would
    /// fail every compressed file in the inbox with no obvious cause.
    private static func cliEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        let brewPaths = ["/opt/homebrew/bin", "/usr/local/bin"]
        let existing = env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        let current = Set(existing.split(separator: ":").map(String.init))
        let missing = brewPaths.filter { !current.contains($0) }
        if !missing.isEmpty {
            env["PATH"] = (missing + [existing]).joined(separator: ":")
        }
        return env
    }

    public static func run() async throws -> Result {
        let cliPath = AppConfig.cliExecutablePath
        let settingsPath = AppConfig.settingsPath
        let taxonomyPath = AppConfig.taxonomyPath

        guard FileManager.default.isExecutableFile(atPath: cliPath.path) else {
            throw RescanError.cliNotFound(cliPath)
        }
        guard FileManager.default.fileExists(atPath: settingsPath.path) else {
            throw RescanError.settingsNotFound(settingsPath)
        }
        guard FileManager.default.fileExists(atPath: taxonomyPath.path) else {
            throw RescanError.taxonomyNotFound(taxonomyPath)
        }

        return try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = cliPath
            process.arguments = [
                "rescan-inbox",
                "--config", settingsPath.path,
                "--taxonomy", taxonomyPath.path,
            ]
            process.currentDirectoryURL = AppConfig.libraryRoot
            process.environment = cliEnvironment()

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            process.terminationHandler = { proc in
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""
                continuation.resume(returning: Result(succeeded: proc.terminationStatus == 0, output: output))
            }

            do {
                try process.run()
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }
}
