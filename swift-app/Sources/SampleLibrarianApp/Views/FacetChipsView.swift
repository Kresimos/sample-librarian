import SwiftUI

/// The "structured browsing" layer on top of pure tag search: selected tags
/// show as removable chips, and the remaining available tags (with counts,
/// scoped to whatever the current filters already narrowed down to) show as
/// clickable chips below. Click one to narrow further; the available list
/// then re-narrows again. There's no fixed type/genre/event hierarchy under
/// the hood -- see BrowserViewModel.reload(), which just re-queries
/// Database.tagCounts() with the current filters each time -- but clicking
/// through progressively narrower tag sets produces the same drill-down feel.
struct FacetChipsView: View {
    let selectedTags: [String]
    let availableFacets: [(tag: String, count: Int)]
    let onSelect: (String) -> Void
    let onDeselect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !selectedTags.isEmpty {
                chipRow {
                    ForEach(selectedTags, id: \.self) { tag in
                        Chip(text: tag, count: nil, style: .selected) { onDeselect(tag) }
                    }
                }
            }
            if !availableFacets.isEmpty {
                chipRow {
                    ForEach(availableFacets, id: \.tag) { facet in
                        Chip(text: facet.tag, count: facet.count, style: .available) { onSelect(facet.tag) }
                    }
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.top, 4)
        .padding(.bottom, 6)
    }

    @ViewBuilder
    private func chipRow<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) { content() }
        }
    }
}

private struct Chip: View {
    enum Style { case selected, available }

    let text: String
    let count: Int?
    let style: Style
    let action: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            Text(text)
            if let count {
                Text("\(count)").foregroundStyle(.secondary)
            }
            if style == .selected {
                Image(systemName: "xmark.circle.fill")
                    .imageScale(.small)
            }
        }
        .font(.system(.caption, design: .monospaced))
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(backgroundColor, in: Capsule())
        .foregroundStyle(style == .selected ? Color.accentColor : .primary)
        .contentShape(Capsule())
        .onTapGesture(perform: action)
    }

    private var backgroundColor: Color {
        style == .selected ? Color.accentColor.opacity(0.18) : Color.secondary.opacity(0.12)
    }
}
