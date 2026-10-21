import SampleLibrarianCore
import SwiftUI

/// The search field itself acts as a token field: committed filters (tags,
/// free-text terms, bpm/key) render as small pills inline, in typed order,
/// followed by the live text-entry area. Backspace on an empty text entry
/// removes the most recently committed one -- the same interaction Mail's
/// To: field uses for recipients.
struct SearchFilterBar: View {
    @Binding var searchText: String
    let committedFilters: [CommittedFilter]
    @Binding var sort: Database.SortOption
    @Binding var sortDirection: Database.SortDirection
    let sampleCount: Int
    var isSearchFocused: FocusState<BrowserFocusArea?>.Binding
    /// Enter: every word in the box commits to a filter chip -- see
    /// BrowserViewModel.commitSearchText. Backspace-to-remove-last-filter is
    /// NOT handled here via .onKeyPress(.delete) -- a focused TextField
    /// swallows Backspace for its own (no-op, since it's already empty)
    /// text editing before SwiftUI's key-press modifiers ever see it. See
    /// BrowserView's NSEvent monitor instead.
    var isRescanning: Bool = false
    var onSubmit: () -> Void = {}
    var onFocusDown: () -> Void = {}
    var onRefresh: () -> Void = {}
    var onRescanInbox: () -> Void = {}

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)

            HStack(spacing: 4) {
                ForEach(committedFilters) { filter in
                    InlineFilterChip(filter: filter)
                }
                TextField(committedFilters.isEmpty ? "Search -- any word becomes a filter on Enter..." : "", text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.system(.body, design: .monospaced))
                    .focused(isSearchFocused, equals: .search)
                    .onSubmit(onSubmit)
                    .onKeyPress(.downArrow) {
                        onFocusDown()
                        return .handled
                    }
            }

            Text("\(sampleCount) sample\(sampleCount == 1 ? "" : "s")")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)

            SortMenu(sort: $sort)

            if sort.supportsDirection {
                DirectionToggle(direction: $sortDirection)
            }

            Divider().frame(height: 14)

            BarButton(systemImage: "arrow.clockwise", label: "Refresh", help: "Reload from the database (e.g. after running samplelib scan elsewhere)", action: onRefresh)

            BarButton(systemImage: "tray.and.arrow.down", label: "Process Inbox", help: "Process new files dropped into the inbox/ folder", isLoading: isRescanning, action: onRescanInbox)
                .disabled(isRescanning)
        }
        .padding(8)
        .background(.thinMaterial)
    }
}

/// Sort-order dropdown, styled to match the search bar's flat monospaced
/// pill/chip look (see FacetChipsView's Chip) rather than a native macOS
/// segmented control.
private struct SortMenu: View {
    @Binding var sort: Database.SortOption

    var body: some View {
        Menu {
            ForEach(Database.SortOption.allCases, id: \.self) { option in
                Button {
                    sort = option
                } label: {
                    if option == sort {
                        Label(option.displayName, systemImage: "checkmark")
                    } else {
                        Text(option.displayName)
                    }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Text(sort.displayName)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 9, weight: .semibold))
            }
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .font(.system(.caption, design: .monospaced))
        .foregroundStyle(.primary)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Color.secondary.opacity(0.12), in: Capsule())
    }
}

/// Ascending/descending flip button, styled to match SortMenu -- hidden
/// entirely for `.random`, which has no direction to flip (see
/// SortOption.supportsDirection).
private struct DirectionToggle: View {
    @Binding var direction: Database.SortDirection

    var body: some View {
        Button {
            direction = direction.toggled
        } label: {
            Image(systemName: direction.systemImage)
                .font(.system(size: 10, weight: .semibold))
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(Color.secondary.opacity(0.12), in: Capsule())
        .help(direction == .ascending ? "Ascending -- click for descending" : "Descending -- click for ascending")
    }
}

/// Icon+label pill button matching SortMenu/FacetChipsView's chip styling --
/// used for Refresh and Process Inbox, in place of the native macOS toolbar
/// buttons those used to be.
private struct BarButton: View {
    let systemImage: String
    let label: String
    let help: String
    var isLoading: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if isLoading {
                    ProgressView()
                        .controlSize(.mini)
                } else {
                    Image(systemName: systemImage)
                }
                Text(label)
            }
            .font(.system(.caption, design: .monospaced))
            .foregroundStyle(.primary)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Color.secondary.opacity(0.12), in: Capsule())
        }
        .buttonStyle(.plain)
        .help(help)
    }
}

private struct InlineFilterChip: View {
    let filter: CommittedFilter

    var body: some View {
        Text(filter.displayLabel)
            .font(.system(.caption, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(backgroundColor, in: Capsule())
            .foregroundStyle(foregroundColor)
    }

    private var foregroundColor: Color {
        if filter.isExcluded { return .red }
        return filter.isOfficialTag ? .accentColor : .purple
    }

    private var backgroundColor: Color {
        if filter.isExcluded { return Color.red.opacity(0.15) }
        return (filter.isOfficialTag ? Color.accentColor : Color.purple).opacity(0.15)
    }
}
