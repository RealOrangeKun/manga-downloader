#!/bin/sh
# Packs the app folder PyInstaller made (dist/Nyanga, from build_appimage.sh) three more ways:
# Nyanga-linux-x86_64.tar.gz (what .deb/.rpm installs update themselves from), a .deb and an .rpm.
# Run from the project folder after build_appimage.sh, with nfpm on PATH (or NFPM=/path/to/nfpm).
# The version comes from version.py (CI writes the real one); NYANGA_VERSION overrides it.
set -eu

PYTHON=${PYTHON:-python}
NFPM=${NFPM:-nfpm}
VERSION=${NYANGA_VERSION:-$("$PYTHON" -c 'from version import __version__; print(__version__)')}
case $VERSION in
    *[!0-9.]* | "") echo "No release version to package ($VERSION): set NYANGA_VERSION" >&2; exit 1 ;;
esac
[ -x dist/Nyanga/Nyanga ] || { echo "Build dist/Nyanga first (packaging/build_appimage.sh)" >&2; exit 1; }

echo "$VERSION" > dist/Nyanga/VERSION  # the launcher and updater compare copies by this
tar -C dist --owner=0 --group=0 --numeric-owner -czf dist/Nyanga-linux-x86_64.tar.gz Nyanga
export NYANGA_VERSION="$VERSION"
"$NFPM" package --config packaging/nfpm.yaml --packager deb --target dist/
"$NFPM" package --config packaging/nfpm.yaml --packager rpm --target dist/
