# PyInstaller build of the app as a folder: dist/MangaDownloader/MangaDownloader.exe
# Run from the project folder: pyinstaller packaging/manga_dl.spec --noconfirm
# (after python scripts/make_icon.py, for the icon)

from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = ROOT / "build" / "icon.ico"

a = Analysis(
    [str(ROOT / "manga_dl.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets" / d), f"assets/{d}") for d in ("fonts", "icons")],  # not the README pictures
    excludes=["tkinter"],
)
# Qt plugins drag in QML, Quick, the virtual keyboard and PDF; the app uses none of them.
UNUSED = ("qml", "quick", "virtualkeyboard", "qt6pdf", "qpdf", "translations")
a.binaries = [b for b in a.binaries if not any(u in b[0].lower() for u in UNUSED)]
a.datas = [d for d in a.datas if not any(u in d[0].lower() for u in UNUSED)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MangaDownloader",
    console=False,
    icon=str(ICON) if ICON.exists() else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MangaDownloader", upx=False)
