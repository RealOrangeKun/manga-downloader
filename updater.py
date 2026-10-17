"""Finds newer releases on GitHub and installs them. Only the built app updates itself, not the source.

Each release carries a Nyanga-Setup-<version>.exe for Windows and a Nyanga-x86_64.AppImage for
Linux. On Windows, updating downloads the installer and runs it silently: it closes the app,
replaces its files, and opens the new version. On Linux the new AppImage replaces the old file and
is opened once the app has quit. No GUI code in here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

import appmenu
import paths
from version import __version__

REPO = "nyanga-app/nyanga-app"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHANGELOG = f"https://github.com/{REPO}/blob/main/CHANGELOG.md"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_FOLDER = Path(tempfile.gettempdir()) / "nyanga-update"


@dataclass
class Release:
    version: str
    notes: str
    url: str  # the installer, or the AppImage
    size: int
    name: str = ""  # the file's name on GitHub


def parse(version: str) -> tuple[int, int, int]:
    """'v1.2.3' -> (1, 2, 3); anything unreadable (like the dev version) counts as 0.0.0."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)$", version.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else (0, 0, 0)


def notes() -> list[dict]:
    """The release notes the release workflow bundles into the exe (newest first); none from source."""
    try:
        return json.loads((paths.BUNDLE / "whats_new.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def notes_since(seen: str, current: str | None = None) -> list[dict]:
    """The releases after `seen` up to `current` (this version) that changed something you can see."""
    upto = parse(current or __version__)
    return [r for r in notes() if parse(seen) < parse(r["version"]) <= upto and r["items"]]


def can_install() -> bool:
    """Running from source there's nothing to replace; pull the repo instead. An AppImage needs to be
    in a folder we can write to, or the new one can't take its place."""
    if not paths.FROZEN:
        return False
    if sys.platform == "win32":
        return True
    image = appmenu.appimage()
    return image is not None and os.access(image.parent, os.W_OK)


def _ours(name: str) -> bool:
    """Whether a release file is the one for this computer."""
    name = name.lower()
    if sys.platform == "win32":
        return name.endswith(".exe") and "setup" in name
    return name.endswith(".appimage") and "x86_64" in name


def latest() -> Release | None:
    """The newest release with an installer, or None when there's none yet."""
    resp = requests.get(_API, timeout=10, headers={"Accept": "application/vnd.github+json"})
    if resp.status_code == 404:  # no releases yet
        return None
    resp.raise_for_status()
    data = resp.json()
    asset = next((a for a in data.get("assets", []) if _ours(a["name"])), None)
    if asset is None:
        return None
    return Release(data["tag_name"].lstrip("v"), data.get("body") or "", asset["browser_download_url"],
                   asset["size"], asset["name"])


def notes_url(version: str = __version__) -> str:
    """This version's release notes, or the whole changelog when running a dev build."""
    return f"https://github.com/{REPO}/releases/tag/v{version}" if any(parse(version)) else CHANGELOG


def is_newer(release: Release) -> bool:
    return parse(release.version) > parse(__version__)


def download(release: Release, progress: Callable[[int, int], None]) -> Path:
    """Saves the installer (or AppImage) to the temp folder, calling progress(done, total) as it goes."""
    _FOLDER.mkdir(parents=True, exist_ok=True)
    out = _FOLDER / (Path(release.name).name or f"Nyanga-Setup-{release.version}.exe")
    part = out.with_suffix(".part")
    with requests.get(release.url, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or release.size)
        done = 0
        with part.open("wb") as f:
            for chunk in resp.iter_content(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
    if done != total:
        part.unlink(missing_ok=True)
        raise OSError("The download was cut off, try again")
    part.replace(out)
    return out


def install(installer: Path) -> None:
    """Starts the installer on its own (or swaps in the new AppImage); the app should quit right after."""
    if sys.platform != "win32":
        _swap_appimage(installer)
        return
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/update=1"],
                     creationflags=flags, close_fds=True)


def cleanup() -> None:
    """Removes installers left over from the last update."""
    shutil.rmtree(_FOLDER, ignore_errors=True)


def _swap_appimage(new: Path) -> None:
    """Puts the new AppImage where the old one is and opens it once this app has quit. Linux keeps
    the running file readable until it closes, so replacing it under us is fine."""
    image = appmenu.appimage()
    if image is None:
        raise OSError("Nyanga isn't running as an AppImage")
    staged = image.with_name(f".{image.name}.new")
    shutil.copyfile(new, staged)
    staged.chmod(0o755)
    staged.replace(image)
    # A clean environment: the running AppImage and PyInstaller set paths meant for this copy only.
    env = {k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR", "ARGV0", "OWD")}
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    else:
        env.pop("LD_LIBRARY_PATH", None)
    subprocess.Popen(["sh", "-c", 'sleep 2; exec "$0"', str(image)], env=env, cwd=Path.home(),
                     start_new_session=True, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
