"""Where the app's own files and the user's data live, from source and as a built app. No GUI code."""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# True inside the PyInstaller build.
FROZEN = getattr(sys, "frozen", False)

_HERE = Path(__file__).resolve().parent

# Bundled read-only files (assets/): next to the scripts, or PyInstaller's unpacked folder.
BUNDLE = Path(getattr(sys, "_MEIPASS", _HERE))

# The library (DATA) and settings.json (CONFIG). From source they stay next to the script
# (git-ignored); the installed app can't write to its own folder and an update replaces it, so it
# uses %APPDATA%\Nyanga on Windows. On Linux the library goes in ~/.local/share/Nyanga and the
# settings in ~/.config/Nyanga (or wherever $XDG_DATA_HOME / $XDG_CONFIG_HOME say).
if FROZEN and sys.platform == "win32":
    DATA = CONFIG = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Nyanga"
elif FROZEN:
    DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Nyanga"
    CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Nyanga"
elif "--memory" in sys.argv or os.environ.get("NYANGA_MEMORY"):
    # From source with --memory: a throwaway folder in RAM (/dev/shm), gone when the app quits.
    # Worker processes find it through NYANGA_MEMORY instead of making their own.
    if not os.environ.get("NYANGA_MEMORY"):
        shm = "/dev/shm" if os.path.isdir("/dev/shm") else None
        os.environ["NYANGA_MEMORY"] = tempfile.mkdtemp(prefix="nyanga-", dir=shm)
        atexit.register(shutil.rmtree, os.environ["NYANGA_MEMORY"], ignore_errors=True)
    DATA = CONFIG = Path(os.environ["NYANGA_MEMORY"])
else:
    DATA = CONFIG = _HERE
