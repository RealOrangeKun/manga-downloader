"""Finds newer releases on GitHub and installs them. Only the installed Windows app updates itself.

Each release carries a Nyanga-Setup-<version>.exe. Updating downloads it and runs it
silently: it closes the app, replaces its files, and opens the new version. No GUI code in here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

import paths
from version import __version__

REPO = "RealOrangeKun/nyanga"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHANGELOG = f"https://github.com/{REPO}/blob/main/CHANGELOG.md"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_FOLDER = Path(tempfile.gettempdir()) / "nyanga-update"


@dataclass
class Release:
    version: str
    notes: str
    url: str  # the installer
    size: int


def parse(version: str) -> tuple[int, int, int]:
    """'v1.2.3' -> (1, 2, 3); anything unreadable (like the dev version) counts as 0.0.0."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)$", version.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else (0, 0, 0)


def can_install() -> bool:
    """Running from source there's nothing to replace; pull the repo instead."""
    return paths.FROZEN and sys.platform == "win32"


def latest() -> Release | None:
    """The newest release with an installer, or None when there's none yet."""
    resp = requests.get(_API, timeout=10, headers={"Accept": "application/vnd.github+json"})
    if resp.status_code == 404:  # no releases yet
        return None
    resp.raise_for_status()
    data = resp.json()
    asset = next((a for a in data.get("assets", [])
                  if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower()), None)
    if asset is None:
        return None
    return Release(data["tag_name"].lstrip("v"), data.get("body") or "", asset["browser_download_url"], asset["size"])


def notes_url(version: str = __version__) -> str:
    """This version's release notes, or the whole changelog when running a dev build."""
    return f"https://github.com/{REPO}/releases/tag/v{version}" if any(parse(version)) else CHANGELOG


def is_newer(release: Release) -> bool:
    return parse(release.version) > parse(__version__)


def download(release: Release, progress: Callable[[int, int], None]) -> Path:
    """Saves the installer to the temp folder, calling progress(done, total) as it goes."""
    _FOLDER.mkdir(parents=True, exist_ok=True)
    out = _FOLDER / f"Nyanga-Setup-{release.version}.exe"
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
    """Starts the installer on its own; the app should quit right after so its files can be replaced."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/update=1"],
                     creationflags=flags, close_fds=True)


def cleanup() -> None:
    """Removes installers left over from the last update."""
    shutil.rmtree(_FOLDER, ignore_errors=True)
