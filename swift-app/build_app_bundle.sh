#!/bin/bash
# Builds a real double-clickable/Dock-launchable SampleLibrarian.app from the
# swift build output. Ad-hoc signed (no Developer ID needed) since this is a
# personal tool, not something distributed to other people.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="${1:-release}"
APP_NAME="SampleLibrarian"
BUNDLE=".build/${APP_NAME}.app"

echo "Building (${CONFIG})..."
swift build -c "$CONFIG"

BIN_PATH=".build/$([ "$CONFIG" = release ] && echo release || echo debug)/SampleLibrarianApp"

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS"
cp "$BIN_PATH" "$BUNDLE/Contents/MacOS/$APP_NAME"

cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.johnnybarr.sample-librarian</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$BUNDLE"

echo "Built: $BUNDLE"
echo "Move/symlink it to /Applications, then bind a shortcut via"
echo "System Settings > Keyboard > Keyboard Shortcuts > App Shortcuts."
