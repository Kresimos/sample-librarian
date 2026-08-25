import XCTest
@testable import SampleLibrarianCore

final class InboxRescannerTests: XCTestCase {
    func testRunThrowsCliNotFoundWhenExecutableMissing() async throws {
        setenv("SAMPLELIB_CLI_PATH", "/nonexistent/path/to/samplelib", 1)
        defer { unsetenv("SAMPLELIB_CLI_PATH") }

        do {
            _ = try await InboxRescanner.run()
            XCTFail("expected cliNotFound to be thrown")
        } catch let error as InboxRescanner.RescanError {
            guard case .cliNotFound = error else {
                XCTFail("expected .cliNotFound, got \(error)")
                return
            }
        }
    }

    func testRunThrowsSettingsNotFoundWhenCliExistsButConfigDoesnt() async throws {
        // /bin/echo definitely exists and is executable, standing in for a
        // real samplelib binary just to get past the first guard.
        setenv("SAMPLELIB_CLI_PATH", "/bin/echo", 1)
        setenv("SAMPLELIB_CONFIG_PATH", "/nonexistent/settings.toml", 1)
        defer {
            unsetenv("SAMPLELIB_CLI_PATH")
            unsetenv("SAMPLELIB_CONFIG_PATH")
        }

        do {
            _ = try await InboxRescanner.run()
            XCTFail("expected settingsNotFound to be thrown")
        } catch let error as InboxRescanner.RescanError {
            guard case .settingsNotFound = error else {
                XCTFail("expected .settingsNotFound, got \(error)")
                return
            }
        }
    }

    func testRunSucceedsAndCapturesOutputWithStandInExecutable() async throws {
        let tmpConfig = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        FileManager.default.createFile(atPath: tmpConfig.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: tmpConfig) }

        setenv("SAMPLELIB_CLI_PATH", "/bin/echo", 1)
        setenv("SAMPLELIB_CONFIG_PATH", tmpConfig.path, 1)
        defer {
            unsetenv("SAMPLELIB_CLI_PATH")
            unsetenv("SAMPLELIB_CONFIG_PATH")
        }

        let result = try await InboxRescanner.run()
        XCTAssertTrue(result.succeeded)
        XCTAssertTrue(result.output.contains("rescan-inbox"))
    }
}
