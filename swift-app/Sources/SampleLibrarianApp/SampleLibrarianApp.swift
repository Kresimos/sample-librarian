import SwiftUI

@main
struct SampleLibrarianApp: App {
    // Hosts the global summon hotkey (Cmd+Opt+L) -- see HotkeyWindowController.swift.
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("Sample Librarian") {
            BrowserView()
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
        .defaultSize(width: 720, height: 520)
        .commands {
            CommandGroup(replacing: .newItem) {}  // single-window tool, no "New Window"
        }
    }
}
