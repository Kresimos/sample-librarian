import SampleLibrarianCore
import SwiftUI

/// The "structured browsing" layer on top of pure tag search: the remaining
/// available official tags (with counts, scoped to whatever the current
/// filters already narrowed down to) show as clickable chips -- click, or
/// keyboard-select, one to narrow further. Already-committed filters no
/// longer render here; they live inline in the search field itself (see
/// SearchFilterBar) so they can be backspaced out like typed text. There's no
/// fixed type/genre/event hierarchy under the hood -- see
/// BrowserViewModel.reload(), which just re-queries Database.tagCounts() with
/// the current filters each time -- but clicking through progressively
/// narrower tag sets produces the same drill-down feel.
struct FacetChipsView: View {
    let availableFacets: [Database.Facet]
    let onSelect: (String) -> Void
    /// The tag currently highlighted via keyboard nav (Left/Right while this
    /// area has focus) -- nil when the chips area doesn't have keyboard
    /// focus, or there's nothing to highlight.
    var focusedTag: String? = nil

    var body: some View {
        if !availableFacets.isEmpty {
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    // Deliberately NOT a LazyHStack: a lazy stack can't size
                    // itself to its content on the cross axis (it doesn't know
                    // its children's heights up front), so it takes the full
                    // height the ScrollView proposes and this bar renders
                    // several times taller than the chips in it. The whole tag
                    // vocabulary is ~96 small capsules -- building them all is
                    // not worth a layout regression.
                    HStack(spacing: 6) {
                        ForEach(availableFacets) { facet in
                            Chip(text: facet.tag, count: facet.count, isFocused: focusedTag == facet.tag) {
                                onSelect(facet.tag)
                            }
                            .id(facet.tag)
                        }
                    }
                }
                .padding(.horizontal, 8)
                .padding(.top, 4)
                .padding(.bottom, 6)
                // Left/Right keyboard nav can move the highlighted chip past
                // the visible edge of the scroll area -- keep it in view.
                .onChange(of: focusedTag) { _, newTag in
                    guard let newTag else { return }
                    withAnimation(.easeOut(duration: 0.15)) {
                        proxy.scrollTo(newTag, anchor: nil)
                    }
                }
            }
        }
    }
}

private struct Chip: View {
    let text: String
    let count: Int
    var isFocused: Bool = false
    let action: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            Text(text)
            Text("\(count)").foregroundStyle(.secondary)
        }
        .font(.system(.caption, design: .monospaced))
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Color.secondary.opacity(0.12), in: Capsule())
        .foregroundStyle(.primary)
        .overlay(
            Capsule().stroke(Color.primary, lineWidth: isFocused ? 2 : 0)
        )
        .contentShape(Capsule())
        .onTapGesture(perform: action)
    }
}
