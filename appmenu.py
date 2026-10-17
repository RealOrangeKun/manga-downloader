"""Adds the Linux AppImage to the app menu (a .desktop file in ~/.local/share), or takes it out. No GUI code.

Tools like Gear Lever or AppImageLauncher make their own entry; then we leave the menu alone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import paths

NAME = "nyanga"
_MARK = "X-Nyanga-Menu=true"  # only in entries we wrote; the one inside the AppImage doesn't have it
_DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
_APPS = _DATA / "applications"
ENTRY = _APPS / f"{NAME}.desktop"
ICON = _DATA / "icons" / "hicolor" / "256x256" / "apps" / f"{NAME}.png"

OURS, THEIRS, NONE = "ours", "theirs", "none"


def appimage() -> Path | None:
    """The AppImage file we run from (its runtime sets $APPIMAGE), or None anywhere else."""
    found = os.environ.get("APPIMAGE")
    return Path(found) if paths.FROZEN and sys.platform.startswith("linux") and found else None


def available() -> bool:
    return appimage() is not None


def _quote(path: Path) -> str:
    """A path as a .desktop Exec argument: in double quotes, with the reserved characters escaped."""
    text = str(path)
    for ch in '\\"`$':
        text = text.replace(ch, "\\" + ch)
    return f'"{text}"'


def _entries() -> list[Path]:
    dirs = [_APPS] + [Path(d) / "applications"
                      for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    return [f for d in dirs if d.is_dir() for f in d.glob("*.desktop")]


def _keys(text: str) -> dict[str, str]:
    """The [Desktop Entry] group's keys."""
    keys, inside = {}, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
        elif inside and "=" in line:
            key, value = line.split("=", 1)
            keys.setdefault(key.strip(), value.strip())
    return keys


def _find() -> tuple[str, Path | None]:
    """Which kind of entry Nyanga has in the menu, and its file."""
    image = appimage()
    found: tuple[str, Path | None] = (NONE, None)
    for f in _entries():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _MARK in text:
            found = (OURS, f)
            continue
        keys = _keys(text)
        run = keys.get("Exec", "")
        if (image and str(image) in run) or (keys.get("Name") == "Nyanga" and "appimage" in run.lower()):
            return THEIRS, f  # theirs wins: two entries would show the app twice
    return found


def state() -> str:
    """OURS when we added the entry, THEIRS when another tool did, NONE when Nyanga isn't in the menu."""
    return _find()[0]


def desktop_id() -> str | None:
    """The menu entry's name (without .desktop), for Qt to tell the desktop which app this is.
    None when there's no entry: the desktop would only complain it can't find one."""
    if not available():
        return None
    entry = _find()[1]
    return entry.stem if entry else None


def add(icon_png: bytes) -> None:
    """Writes our entry and icon, pointing at the AppImage where it is now."""
    image = appimage()
    if image is None:
        raise OSError("Nyanga isn't running as an AppImage")
    ICON.parent.mkdir(parents=True, exist_ok=True)
    ICON.write_bytes(icon_png)
    _APPS.mkdir(parents=True, exist_ok=True)
    ENTRY.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Nyanga\n"
        "Comment=A cute & cozy app that downloads manga\n"
        f"Exec={_quote(image)} %U\n"
        f"TryExec={image}\n"  # hides the entry if the AppImage is deleted
        f"Icon={NAME}\n"
        f"StartupWMClass={NAME}\n"
        "Categories=Network;FileTransfer;\n"
        "Terminal=false\n"
        f"{_MARK}\n", encoding="utf-8")
    _refresh()


def remove() -> None:
    ENTRY.unlink(missing_ok=True)
    ICON.unlink(missing_ok=True)
    _refresh()


def follow() -> None:
    """If our entry points somewhere else (the AppImage was moved), point it here again."""
    image = appimage()
    if image is None or not ENTRY.exists():
        return
    try:
        text = ENTRY.read_text(encoding="utf-8")
        if _MARK in text and f"TryExec={image}\n" not in text:
            add(ICON.read_bytes())
    except OSError:
        pass


def _refresh() -> None:
    """Most desktops notice the change by themselves; this nudges the ones that don't."""
    if tool := shutil.which("update-desktop-database"):
        subprocess.run([tool, "-q", str(_APPS)], check=False, capture_output=True)
