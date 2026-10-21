import AppKit
import Carbon.HIToolbox

/// Global summon hotkey (Cmd+Opt+L): brings the main window to front (never
/// hides it -- closing/leaving it open is left to the window's normal
/// controls), no special positioning or full-screen tricks. Two earlier,
/// more ambitious
/// approaches were tried and abandoned here: floating the window over a
/// full-screen app via NSWindow.collectionBehavior (.fullScreenAuxiliary
/// only works for a *same-app* auxiliary panel, not a different app's
/// full-screen Space), and driving native Split View via AppleScript/System
/// Events (needs Accessibility + Automation permission, and the AXShowMenu
/// trick on the zoom button didn't reliably work in practice). Just a plain
/// show/hide toggle now.
///
/// Registered via Carbon's RegisterEventHotKey rather than an NSEvent global
/// monitor -- it needs no Accessibility/Input Monitoring permission, since
/// it's a real OS-level hotkey registration (the same mechanism system
/// utilities have used for this for decades), not a synthetic input tap.
final class AppDelegate: NSObject, NSApplicationDelegate {
    private static let mainWindowTitle = "Sample Librarian"

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandlerRef: EventHandlerRef?

    func applicationDidFinishLaunching(_ notification: Notification) {
        registerGlobalHotkey()
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
        }
        if let eventHandlerRef {
            RemoveEventHandler(eventHandlerRef)
        }
    }

    private func registerGlobalHotkey() {
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: OSType(kEventHotKeyPressed)
        )

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(
            GetEventDispatcherTarget(),
            { _, _, userData -> OSStatus in
                guard let userData else { return noErr }
                Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue().bringWindowToFront()
                return noErr
            },
            1,
            &eventType,
            selfPtr,
            &eventHandlerRef
        )

        // Signature is an arbitrary 4-char OSType identifying this app's
        // hotkeys -- 'SLIB' for Sample LIBrarian.
        let hotKeyID = EventHotKeyID(signature: OSType(0x534C4942), id: 1)
        let keyCode = UInt32(kVK_ANSI_L)
        let modifiers = UInt32(cmdKey | optionKey)
        let status = RegisterEventHotKey(
            keyCode, modifiers, hotKeyID, GetEventDispatcherTarget(), 0, &hotKeyRef
        )
        // This used to be discarded, which made "the summon hotkey stopped
        // working" impossible to tell apart from "it fired but found no
        // window". eventHotKeyExistsErr (-9878) means something else already
        // owns Cmd+Opt+L -- including a previous copy of this app that didn't
        // get to unregister (a crash, or a SIGKILL rather than a real quit).
        if status != noErr {
            NSLog("[SampleLibrarian] RegisterEventHotKey(Cmd+Opt+L) failed: OSStatus \(status)")
        }
    }

    private func bringWindowToFront() {
        // Prefer the real main window by title, but fall back to any ordinary
        // window rather than doing nothing: SwiftUI can retitle or rebuild the
        // WindowGroup's window, and silently no-op'ing on a title mismatch
        // reads to the user as "the hotkey is dead".
        let window = NSApp.windows.first { $0.title == Self.mainWindowTitle }
            ?? NSApp.windows.first { $0.canBecomeMain && !$0.isExcludedFromWindowsMenu }
        guard let window else {
            NSLog("[SampleLibrarian] summon hotkey fired but found no window to raise")
            return
        }
        NSApp.activate(ignoringOtherApps: true)
        // A minimized window ignores makeKeyAndOrderFront -- it has to be
        // deminiaturized first, or the hotkey looks like it did nothing.
        if window.isMiniaturized {
            window.deminiaturize(nil)
        }
        window.makeKeyAndOrderFront(nil)
        // activate(ignoringOtherApps:) is deprecated and recent macOS is
        // increasingly free to refuse a background app's request to take
        // focus. orderFrontRegardless raises the window even when that
        // refusal happens, so the summon still does something visible.
        window.orderFrontRegardless()
    }
}
