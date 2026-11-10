#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
DEVELOPER_ID="${MACNATIVE_MODS_DEVELOPER_ID:-}"
NOTARY_PROFILE="${MACNATIVE_MODS_NOTARY_PROFILE:-}"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    printf 'MacNative Mods requires Apple silicon.\n' >&2
    exit 1
fi
if [[ -n "$DEVELOPER_ID" || -n "$NOTARY_PROFILE" ]]; then
    if [[ "$DEVELOPER_ID" != "Developer ID Application: "* || -z "$NOTARY_PROFILE" ]]; then
        printf 'Release builds require a Developer ID Application identity and a notarytool keychain profile.\n' >&2
        exit 1
    fi
fi
STAGING="$(mktemp -d /private/tmp/macnative-mods-build.XXXXXXXX)"
trap 'rm -rf "$STAGING"' EXIT
APP="$STAGING/MacNative Mods.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/Mods"
xcrun swift "$ROOT/scripts/generate-mods-icon.swift" "$STAGING/MacNativeMods.iconset"
/usr/bin/iconutil -c icns "$STAGING/MacNativeMods.iconset" -o "$APP/Contents/Resources/MacNativeMods.icns"
xcrun swiftc -O -warnings-as-errors -target arm64-apple-macosx26.0 \
    "$ROOT/Sources/MacNativeMods.swift" "$ROOT/Sources/ModsModel.swift" "$ROOT/Sources/ModsView.swift" \
    -o "$APP/Contents/MacOS/MacNativeMods" -framework SwiftUI -framework AppKit

cp "$ROOT/scripts/"{mods,mod_environment,mod_import,mod_bcml,mod_profiles,mod_rstb,mod_demos,mod_models,mod_weapon_stats,extract_destinations,extract_items,extract_map}.py \
    "$APP/Contents/Resources/Mods/"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>dev.christianfurr.macnative-mods</string>
<key>CFBundleName</key><string>MacNative Mods</string>
<key>CFBundleExecutable</key><string>MacNativeMods</string>
<key>CFBundleIconFile</key><string>MacNativeMods</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.2.5</string>
<key>CFBundleVersion</key><string>10</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
<key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
<key>CFBundleDocumentTypes</key>
<array><dict>
<key>CFBundleTypeName</key><string>BCML BNP Pack</string>
<key>CFBundleTypeRole</key><string>Viewer</string>
<key>LSHandlerRank</key><string>Alternate</string>
<key>LSItemContentTypes</key><array><string>dev.christianfurr.macnative-mods.bnp</string></array>
</dict></array>
<key>UTImportedTypeDeclarations</key>
<array><dict>
<key>UTTypeIdentifier</key><string>dev.christianfurr.macnative-mods.bnp</string>
<key>UTTypeDescription</key><string>BCML BNP Pack</string>
<key>UTTypeConformsTo</key><array><string>public.archive</string></array>
<key>UTTypeTagSpecification</key><dict>
<key>public.filename-extension</key><array><string>bnp</string></array>
</dict>
</dict></array>
<key>UTExportedTypeDeclarations</key>
<array><dict>
<key>UTTypeIdentifier</key><string>dev.christianfurr.macnative-mods.load-order</string>
<key>UTTypeDescription</key><string>MacNative Mods Load Order Item</string>
<key>UTTypeConformsTo</key><array><string>public.data</string></array>
</dict></array>
</dict></plist>
PLIST

/usr/bin/xattr -dr com.apple.FinderInfo "$APP" 2>/dev/null || true
/usr/bin/xattr -dr com.apple.ResourceFork "$APP" 2>/dev/null || true
if [[ -n "$DEVELOPER_ID" ]]; then
    /usr/bin/codesign --force --options runtime --timestamp --sign "$DEVELOPER_ID" "$APP"
else
    /usr/bin/codesign --force --sign - "$APP"
fi
/usr/bin/codesign --verify --strict "$APP"

ARCHIVE="$STAGING/MacNative.Mods.zip"
/usr/bin/ditto -c -k --keepParent "$APP" "$ARCHIVE"
if [[ -n "$DEVELOPER_ID" ]]; then
    xcrun notarytool submit "$ARCHIVE" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$APP"
    xcrun stapler validate "$APP"
    /usr/sbin/spctl --assess --type execute --verbose "$APP"
    rm "$ARCHIVE"
    /usr/bin/ditto -c -k --keepParent "$APP" "$ARCHIVE"
fi
OUTPUT_APP="$BUILD/manager/MacNative Mods.app"
mkdir -p "$BUILD/manager"
rm -rf "$OUTPUT_APP"
/usr/bin/ditto "$APP" "$OUTPUT_APP"
mv "$ARCHIVE" "$BUILD/MacNative.Mods.zip"
(cd "$BUILD" && /usr/bin/shasum -a 256 MacNative.Mods.zip > MacNative.Mods.zip.sha256)
printf 'App: %s\nArchive: %s\n' "$OUTPUT_APP" "$BUILD/MacNative.Mods.zip"
