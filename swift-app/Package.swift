// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SampleLibrarianApp",
    platforms: [.macOS(.v13)],
    targets: [
        // Pure logic: DB access, models, search query building. No SwiftUI/AppKit,
        // so it's fully unit-testable without a display/window server.
        .target(
            name: "SampleLibrarianCore",
            path: "Sources/SampleLibrarianCore",
            linkerSettings: [.linkedLibrary("sqlite3")]
        ),
        // The windowed app: SwiftUI views + the AppKit drag-and-drop bridge.
        .executableTarget(
            name: "SampleLibrarianApp",
            dependencies: ["SampleLibrarianCore"],
            path: "Sources/SampleLibrarianApp"
        ),
        .testTarget(
            name: "SampleLibrarianCoreTests",
            dependencies: ["SampleLibrarianCore"],
            path: "Tests/SampleLibrarianCoreTests"
        ),
    ]
)
