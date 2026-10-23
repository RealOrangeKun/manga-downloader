"""Finds newer releases on GitHub and installs them. Only the built app updates itself, not the source.

Each release carries a Nyanga-Setup-<version>.exe for Windows, a Nyanga-x86_64.AppImage for
Linux, .deb and .rpm packages, and Nyanga-linux-x86_64.tar.gz (the app folder) for those packages
to update from. On Windows, updating downloads the installer and runs it silently: it closes the
app, replaces its files, and opens the new version. The new AppImage replaces the old file and is
opened once the app has quit. A .deb/.rpm install starts through /usr/bin/nyanga (which sets
NYANGA_LAUNCHER): its updates go in the user's own folder (DATA/app/<version>, with `current`
pointing at the one to run), so no password is needed, and the launcher runs whichever of that
and the packaged copy is newer.

Windows and .deb/.rpm installs usually skip most of that download: each release also carries
Nyanga-update-<system>-x86_64.zip and .json (see scripts/pack_update.py), and only the files whose
hash differs from this copy's are fetched out of the zip with byte-range requests. The new app
folder is built next to this one (unchanged files copied over) and swapped in once the app quits;
if anything goes wrong on the way, the full download above is used instead. No GUI code in here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

import appmenu
import paths
from version import __version__

log = logging.getLogger(__name__)

REPO = "nyanga-app/nyanga-app"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHANGELOG = f"https://github.com/{REPO}/blob/main/CHANGELOG.md"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_FOLDER = Path(tempfile.gettempdir()) / "nyanga-update"
_APPS = paths.DATA / "app"  # updated copies of a .deb/.rpm install, one folder per version
# Where Inno Setup keeps what Installed apps shows; its AppId is in packaging/installer.iss.
_UNINSTALL_KEY = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{36C7F768-8CCD-453C-A53E-24898AD4D191}_is1"
_GAP = 256 * 1024  # changed files closer than this in the zip come in one request


@dataclass
class Release:
    version: str
    notes: str
    url: str  # the installer, or the AppImage
    size: int
    name: str = ""  # the file's name on GitHub
    patch: Patch | None = None  # just the changed files, when this copy can update that way


@dataclass
class Patch:
    url: str  # the zip with every file of the new version
    files: list[dict]  # the manifest: path, size, sha256, mode, offset, length, method
    links: list[dict]  # path, target
    fetch: list[list[dict]]  # the files this copy doesn't have, in runs fetched one request each

    @property
    def size(self) -> int:
        return sum(run[-1]["offset"] + run[-1]["length"] - run[0]["offset"] for run in self.fetch)


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


def launcher() -> Path | None:
    """/usr/bin/nyanga when this copy was started by the .deb/.rpm launcher, else None."""
    path = os.environ.get("NYANGA_LAUNCHER")
    if not (paths.FROZEN and sys.platform != "win32" and path):
        return None
    return Path(path) if Path(path).is_file() else None


def can_install() -> bool:
    """Running from source there's nothing to replace; pull the repo instead. An AppImage needs to be
    in a folder we can write to, or the new one can't take its place. A .deb/.rpm install updates
    into the user's own folder, which is always theirs to write to."""
    if not paths.FROZEN:
        return False
    if sys.platform == "win32" or launcher():
        return True
    image = appmenu.appimage()
    return image is not None and os.access(image.parent, os.W_OK)


def _ours(name: str) -> bool:
    """Whether a release file is the one for this computer."""
    name = name.lower()
    if sys.platform == "win32":
        return name.endswith(".exe") and "setup" in name
    if launcher():
        return name.endswith(".tar.gz") and "linux" in name and "x86_64" in name
    return name.endswith(".appimage") and "x86_64" in name


def latest() -> Release | None:
    """The newest release with an installer, or None when there's none yet."""
    resp = requests.get(_API, timeout=10, headers={"Accept": "application/vnd.github+json"})
    if resp.status_code == 404:  # no releases yet
        return None
    resp.raise_for_status()
    data = resp.json()
    asset = next((a for a in data.get("assets", []) if _ours(a["name"])), None)
    log.info("latest release %s, file for this system: %s", data.get("tag_name"), asset and asset["name"])
    if asset is None:
        return None
    release = Release(data["tag_name"].lstrip("v"), data.get("body") or "", asset["browser_download_url"],
                      asset["size"], asset["name"])
    if is_newer(release) and (sys.platform == "win32" or launcher()):
        release.patch = _patch(release.version, data.get("assets", []))
        if release.patch:
            release.size = release.patch.size
    return release


_patches: dict[str, Patch | None] = {}  # by version: hashing the app folder takes a moment


def _patch(version: str, assets: list[dict]) -> Patch | None:
    """What this copy needs from the release's update zip, or None to download it all."""
    if version in _patches:
        return _patches[version]
    system = "windows" if sys.platform == "win32" else "linux"
    urls = {a["name"].lower(): a["browser_download_url"] for a in assets}
    stem = f"nyanga-update-{system}-x86_64"
    patch = None
    if f"{stem}.zip" in urls and f"{stem}.json" in urls:
        try:
            resp = requests.get(urls[f"{stem}.json"], timeout=30)
            resp.raise_for_status()
            manifest = resp.json()
            here = Path(sys.executable).parent
            need = [f for f in manifest["files"] if not _same(here / f["path"], f)]
            patch = Patch(urls[f"{stem}.zip"], manifest["files"], manifest["links"], _runs(need))
            log.info("update %s: %d of %d files changed, %d bytes to fetch", version, len(need),
                     len(manifest["files"]), patch.size)
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
            log.warning("can't update %s by its changed files only", version, exc_info=True)
    _patches[version] = patch
    return patch


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same(path: Path, entry: dict) -> bool:
    """Whether this copy already has the file the manifest lists."""
    try:
        return (not path.is_symlink() and path.is_file() and path.stat().st_size == entry["size"]
                and _sha256(path) == entry["sha256"])
    except OSError:
        return False


def _runs(files: list[dict]) -> list[list[dict]]:
    """Groups files by where they are in the zip, so neighbours come in one request."""
    runs: list[list[dict]] = []
    for f in sorted(files, key=lambda f: f["offset"]):
        last = runs[-1][-1] if runs else None
        if last and f["offset"] - (last["offset"] + last["length"]) <= _GAP:
            runs[-1].append(f)
        else:
            runs.append([f])
    return runs


def notes_url(version: str = __version__) -> str:
    """This version's release notes, or the whole changelog when running a dev build."""
    return f"https://github.com/{REPO}/releases/tag/v{version}" if any(parse(version)) else CHANGELOG


def is_newer(release: Release) -> bool:
    return parse(release.version) > parse(__version__)


def download(release: Release, progress: Callable[[int, int], None]) -> Path:
    """Saves the installer (or AppImage) to the temp folder, calling progress(done, total) as it goes.
    With a patch, it builds the new app folder instead and returns that."""
    if release.patch:
        try:
            return _build(release, progress)
        except (requests.RequestException, OSError, ValueError, KeyError, zlib.error):
            log.warning("updating by changed files failed, downloading it all", exc_info=True)
            release.patch = None
    _FOLDER.mkdir(parents=True, exist_ok=True)
    out = _FOLDER / (Path(release.name).name or f"Nyanga-Setup-{release.version}.exe")
    part = out.with_suffix(".part")
    log.info("downloading update %s to %s", release.url, out)
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
    """Starts the installer on its own (or swaps in the new AppImage or app folder); the app should
    quit right after."""
    log.info("installing update from %s", installer)
    if installer.is_dir():  # built from the changed files
        _swap_windows(installer) if sys.platform == "win32" else _place(installer)
        return
    if sys.platform != "win32":
        _swap_folder(installer) if launcher() else _swap_appimage(installer)
        return
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/update=1"],
                     creationflags=flags, close_fds=True)


def cleanup() -> None:
    """Removes installers left over from the last update, and app copies a .deb/.rpm install no
    longer runs (never the one running now: its files may still be read)."""
    shutil.rmtree(_FOLDER, ignore_errors=True)
    if sys.platform == "win32" and paths.FROZEN:
        here = Path(sys.executable).parent
        for leftover in (".old", ".new"):
            shutil.rmtree(here.with_name(here.name + leftover), ignore_errors=True)
    if not launcher() or not _APPS.is_dir():
        return
    keep = {(_APPS / "current").resolve(), Path(sys.executable).resolve().parent}
    for folder in _APPS.iterdir():
        if folder.name != "current" and folder.resolve() not in keep:
            shutil.rmtree(folder, ignore_errors=True)


def _swap_folder(archive: Path) -> None:
    """Unpacks the new app folder next to the old ones, points `current` at it and opens it through
    the launcher once this app has quit. The old copy stays until the next start (see cleanup)."""
    _APPS.mkdir(parents=True, exist_ok=True)
    unpack = Path(tempfile.mkdtemp(prefix=".new-", dir=_APPS))
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(unpack, filter="data")  # refuses paths that would land outside the folder
        _place(unpack / "Nyanga")
    finally:
        shutil.rmtree(unpack, ignore_errors=True)


def _place(app: Path) -> None:
    """Moves a new app folder (somewhere inside _APPS) to _APPS/<version>, points `current` at it
    and opens it through the launcher once this app has quit."""
    start = launcher()
    if start is None:
        raise OSError("Nyanga wasn't started from its .deb or .rpm")
    try:
        version = (app / "VERSION").read_text().strip()
        if not (app / "Nyanga").is_file() or not any(parse(version)):
            raise OSError("The update didn't look right, try again")
        target = _APPS / version
        shutil.rmtree(target, ignore_errors=True)
        app.replace(target)
    finally:
        if app.parent != _APPS and app.parent.name.startswith(".new-"):
            shutil.rmtree(app.parent, ignore_errors=True)
    link = _APPS / ".current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(version)  # relative, so the folder can move with its owner's home
    link.replace(_APPS / "current")
    _reopen(start)


def _reopen(program: Path) -> None:
    """Opens `program` a moment after this app quits."""
    # A clean environment: the running AppImage and PyInstaller set paths meant for this copy only.
    env = {k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR", "ARGV0", "OWD")}
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    else:
        env.pop("LD_LIBRARY_PATH", None)
    subprocess.Popen(["sh", "-c", 'sleep 2; exec "$0"', str(program)], env=env, cwd=Path.home(),
                     start_new_session=True, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    _reopen(image)


def _build(release: Release, progress: Callable[[int, int], None]) -> Path:
    """Builds the new app folder from this copy's unchanged files and the changed ones fetched out of
    the update zip. On Linux it goes in _APPS, on Windows next to the installed folder (so swapping
    is a rename)."""
    patch = release.patch
    here = Path(sys.executable).parent
    if sys.platform == "win32":
        new = here.with_name(here.name + ".new")
        shutil.rmtree(new, ignore_errors=True)
    else:
        _APPS.mkdir(parents=True, exist_ok=True)
        new = Path(tempfile.mkdtemp(prefix=".new-", dir=_APPS)) / "Nyanga"
    try:
        fetched = {f["path"] for run in patch.fetch for f in run}
        for f in patch.files:
            if f["path"] not in fetched:
                _keep(here / f["path"], new / f["path"])
        for link in patch.links:
            dest = new / link["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(link["target"])
        if sys.platform == "win32":  # the uninstaller isn't part of the app folder we pack
            for extra in here.glob("unins*"):
                shutil.copy2(extra, new / extra.name)
        _fetch(patch, new, progress)
        for f in patch.files:
            if (new / f["path"]).stat().st_size != f["size"]:
                raise OSError("The update didn't look right, try again")
    except BaseException:
        shutil.rmtree(new if sys.platform == "win32" else new.parent, ignore_errors=True)
        raise
    _versions[new] = release.version
    return new


_versions: dict[Path, str] = {}  # built app folders and the version each one is


def _keep(old: Path, new: Path) -> None:
    """Puts an unchanged file in the new folder: a hard link when it can (instant, no extra space;
    files are never changed in place, only replaced), else a copy."""
    new.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.link(old, new)
            return
        except OSError:
            pass
    shutil.copy2(old, new)


def _fetch(patch: Patch, new: Path, progress: Callable[[int, int], None]) -> None:
    """Downloads the changed files, one byte-range request per run, checking each one's hash."""
    total, done = patch.size, 0
    progress(done, total)
    for run in patch.fetch:
        start, end = run[0]["offset"], run[-1]["offset"] + run[-1]["length"]
        headers = {"Range": f"bytes={start}-{end - 1}", "Accept-Encoding": "identity"}
        with requests.get(patch.url, headers=headers, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            if resp.status_code != 206:
                raise OSError("GitHub sent the whole file instead of the changed parts")
            at = start

            def read(n: int) -> bytes:
                nonlocal at, done
                data = resp.raw.read(n)
                if len(data) != n:
                    raise OSError("The download was cut off, try again")
                at += n
                done += n
                progress(done, total)
                return data

            for f in run:
                while at < f["offset"]:  # the bit of an unchanged file between two changed ones
                    read(min(f["offset"] - at, 256 * 1024))
                dest = new / f["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                unzip = zlib.decompressobj(-15) if f["method"] == 8 else None
                digest, left = hashlib.sha256(), f["length"]
                with dest.open("wb") as out:
                    while left:
                        piece = read(min(left, 256 * 1024))
                        left -= len(piece)
                        piece = unzip.decompress(piece) if unzip else piece
                        digest.update(piece)
                        out.write(piece)
                    if unzip:
                        piece = unzip.flush()
                        digest.update(piece)
                        out.write(piece)
                if digest.hexdigest() != f["sha256"]:
                    raise OSError("The update didn't look right, try again")
                dest.chmod(f["mode"])


# Runs once the app has quit: swaps the new folder in, puts the old one back if that fails, tells
# Installed apps the new version and opens the app. Wait-Process because a running exe can't move.
_SWAP_PS1 = r"""
param([int]$Id, [string]$App, [string]$New, [string]$Version, [string]$Key)
$name = Split-Path $App -Leaf
Wait-Process -Id $Id -Timeout 60 -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Remove-Item -LiteralPath "$App.old" -Recurse -Force -ErrorAction SilentlyContinue
$moved = $false
foreach ($n in 1..20) {
    try { Rename-Item -LiteralPath $App -NewName "$name.old" -ErrorAction Stop; $moved = $true; break }
    catch { Start-Sleep -Seconds 1 }
}
if ($moved) {
    try {
        Rename-Item -LiteralPath $New -NewName $name -ErrorAction Stop
        if (Test-Path $Key) {
            Set-ItemProperty -Path $Key -Name DisplayVersion -Value $Version
            Set-ItemProperty -Path $Key -Name DisplayName -Value "Nyanga $Version"
        }
    } catch {
        if (-not (Test-Path -LiteralPath $App)) { Rename-Item -LiteralPath "$App.old" -NewName $name }
    }
}
Start-Process -FilePath (Join-Path $App 'Nyanga.exe')
"""


def _swap_windows(new: Path) -> None:
    """Starts the helper that swaps in the new folder once this app has quit."""
    here = Path(sys.executable).parent
    _FOLDER.mkdir(parents=True, exist_ok=True)
    script = _FOLDER / "swap.ps1"
    script.write_text(_SWAP_PS1, encoding="utf-8-sig")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", str(script), "-Id", str(os.getpid()), "-App", str(here), "-New", str(new),
                      "-Version", _versions.get(new, ""), "-Key", _UNINSTALL_KEY],
                     creationflags=flags, close_fds=True, cwd=here.parent)
