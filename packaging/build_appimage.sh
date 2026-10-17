#!/bin/sh
# Builds dist/Nyanga-x86_64.AppImage from scratch: the icon, the PyInstaller folder, then the AppImage.
# Run from the project folder with a Python that has requirements.txt and pyinstaller installed
# (PYTHON=.venv/bin/python packaging/build_appimage.sh; plain `python` by default).
# The file name has no version in it, so the updater can put a new one in its place.
set -eu

PYTHON=${PYTHON:-python}
QT_QPA_PLATFORM=offscreen "$PYTHON" scripts/make_icon.py
"$PYTHON" -m PyInstaller packaging/nyanga.spec --noconfirm

APPDIR=build/AppDir
TOOL=build/appimagetool-x86_64.AppImage

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -r dist/Nyanga "$APPDIR/usr/lib/nyanga"
cp packaging/appimage/AppRun packaging/appimage/nyanga.desktop "$APPDIR/"
cp build/icon.png "$APPDIR/nyanga.png"
chmod +x "$APPDIR/AppRun"

if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
# Extract-and-run: CI runners have no FUSE to mount the tool itself.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOL" --no-appstream "$APPDIR" dist/Nyanga-x86_64.AppImage
