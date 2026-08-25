import SwiftUI

@main
struct SampleLibrarianApp: App {
    var body: some Scene {
        WindowGroup("Sample Librarian") {
            BrowserView()
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
        .defaultSize(width: 640, height: 420)
        .commands {
            CommandGroup(replacing: .newItem) {}  // single-window tool, no "New Window"
        }
    }
}
