#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Free-Browser"
VERSION="0.1"
ARCH="$(uname -m)"
APPDIR="$ROOT/AppDir"
OUTPUT="$ROOT/${APP_NAME}-${VERSION}-${ARCH}.AppImage"

if [[ "$ARCH" != "x86_64" ]]; then
    echo "This first AppImage build script currently targets x86_64; detected: $ARCH" >&2
    exit 1
fi

for cmd in make python3 pkg-config; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "Missing $cmd. Run ./dep.sh --build first." >&2
        exit 1
    }
done

if ! pkg-config --exists gtk4 webkitgtk-6.0 libsoup-3.0; then
    echo "GTK 4 / WebKitGTK 6.0 / libsoup 3 development metadata is missing. Run ./dep.sh --build." >&2
    exit 1
fi

cd "$ROOT"
make clean
make

EXTENSION="$(python3-config --extension-suffix)"
if [[ ! -f "$ROOT/connections$EXTENSION" ]]; then
    echo "Build failed: connections$EXTENSION was not created." >&2
    exit 1
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/free-browser" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"

install -m 644 main.py "$APPDIR/usr/lib/free-browser/main.py"
install -m 644 "connections$EXTENSION" "$APPDIR/usr/lib/free-browser/"
install -m 644 packaging/free-browser.desktop "$APPDIR/usr/share/applications/free-browser.desktop"
install -m 644 packaging/free-browser.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/free-browser.svg"
install -m 644 packaging/free-browser.svg "$APPDIR/free-browser.svg"
install -m 644 packaging/free-browser.desktop "$APPDIR/free-browser.desktop"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname -- "$(readlink -f -- "$0")")"
export PYTHONPATH="$HERE/usr/lib/free-browser${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 "$HERE/usr/lib/free-browser/main.py" "$@"
APPRUN
chmod 755 "$APPDIR/AppRun"

if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL="$(command -v appimagetool)"
else
    APPIMAGETOOL="$ROOT/appimagetool-x86_64.AppImage"
    if [[ ! -x "$APPIMAGETOOL" ]]; then
        echo "Downloading appimagetool..."
        curl -fL --retry 3 \
            https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage \
            -o "$APPIMAGETOOL"
        chmod +x "$APPIMAGETOOL"
    fi
fi

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"
echo "Created: $OUTPUT"
echo "Runtime note: this AppImage uses the host Python, GTK 4, WebKitGTK 6.0, libsoup and GStreamer. Run ./dep.sh on a new system before launching it."
