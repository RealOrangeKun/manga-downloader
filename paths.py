"""Where the app's own files and the user's data live, from source and as a built exe. No GUI code."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# True inside the PyInstaller build.
FROZEN = getattr(sys, "frozen", False)

_HERE = Path(__file__).resolve().parent

# Bundled read-only files (assets/): next to the scripts, or PyInstaller's unpacked folder.
BUNDLE = Path(getattr(sys, "_MEIPASS", _HERE))

# Settings and library. From source they stay next to the script (git-ignored); the installed app
# can't write to its own folder and an update replaces it, so it uses %APPDATA%\Manga Downloader.
if FROZEN:
    DATA = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "Manga Downloader"
else:
    DATA = _HERE
