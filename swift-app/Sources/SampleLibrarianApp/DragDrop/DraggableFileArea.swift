import AppKit
import SwiftUI

/// ALTERNATE drag implementation, not wired in by default -- see
/// SampleRowView, which uses SwiftUI's `.onDrag` as the first thing to try
/// (that's what the project plan calls for trying first, and it doesn't risk
/// interfering with List's built-in click-to-select/arrow-key navigation the
/// way an overlaid AppKit view intercepting mouseDown could).
///
/// If hands-on testing shows `.onDrag` doesn't reliably work against Logic
/// Pro (an older AppKit/Cocoa app, not a modern drag-and-drop-API-native
/// one -- exactly the case the plan flagged as a risk), swap SampleRowView's
/// `.onDrag` modifier for this instead: wrap the row's content in
/// `.background(DraggableFileArea(fileURL: sample.resolvedFileURL))` (background
/// rather than overlay, so it sits behind hit-testing for taps but still
/// receives the mouseDragged that starts a real NSDraggingSession -- test
/// that layering choice too, it's a guess, not something verified here).
///
/// NEEDS HANDS-ON VERIFICATION either way: this file has never been run
/// against a live Logic Pro session.
struct DraggableFileArea: NSViewRepresentable {
    let fileURL: URL

    func makeNSView(context: Context) -> DragSourceView {
        let view = DragSourceView()
        view.fileURL = fileURL
        return view
    }

    func updateNSView(_ nsView: DragSourceView, context: Context) {
        nsView.fileURL = fileURL
    }
}

final class DragSourceView: NSView {
    var fileURL: URL?
    private var mouseDownLocation: NSPoint?

    override var acceptsFirstResponder: Bool { false }

    override func mouseDown(with event: NSEvent) {
        mouseDownLocation = event.locationInWindow
    }

    override func mouseDragged(with event: NSEvent) {
        guard let fileURL, let start = mouseDownLocation else { return }
        let current = event.locationInWindow
        // small threshold so a plain click isn't misread as a drag attempt
        guard hypot(current.x - start.x, current.y - start.y) > 3 else { return }

        let draggingItem = NSDraggingItem(pasteboardWriter: fileURL as NSURL)
        draggingItem.setDraggingFrame(
            NSRect(x: 0, y: 0, width: bounds.width, height: bounds.height),
            contents: NSWorkspace.shared.icon(forFile: fileURL.path)
        )

        beginDraggingSession(with: [draggingItem], event: event, source: self)
        mouseDownLocation = nil
    }
}

extension DragSourceView: NSDraggingSource {
    func draggingSession(_ session: NSDraggingSession, sourceOperationMaskFor context: NSDraggingContext) -> NSDragOperation {
        .copy
    }
}
