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

        public var description: String {
            switch self {
            case .cliNotFound(let url):
                return "samplelib CLI not found at \(url.path). Set SAMPLELIB_CLI_PATH if it's installed elsewhere."
            case .settingsNotFound(let url):
                return "settings.toml not found at \(url.path). Copy or symlink your config there, " +
                    "or set SAMPLELIB_CONFIG_PATH."
            }
        }
    }

    public static func run() async throws -> Result {
        let cliPath = AppConfig.cliExecutablePath
        let settingsPath = AppConfig.settingsPath

        guard FileManager.default.isExecutableFile(atPath: cliPath.path) else {
            throw RescanError.cliNotFound(cliPath)
        }
        guard FileManager.default.fileExists(atPath: settingsPath.path) else {
            throw RescanError.settingsNotFound(settingsPath)
        }

        return try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = cliPath
            process.arguments = ["rescan-inbox", "--config", settingsPath.path]

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
