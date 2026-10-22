"""Download history: which chapters of which manga are downloaded, failed or still waiting.

Stored as JSON in library/history.json next to the script (git-ignored), with covers in
library/covers/. History is kept per chapter, so it stays right if the number of chapters
per file changes between downloads.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import paths

LIBRARY = paths.DATA / "library"
log = logging.getLogger(__name__)


def chapter_key(number: float) -> str:
    return f"{number:g}"


class History:
    def __init__(self, folder: Path = LIBRARY):
        self.folder = folder
        self.path = folder / "history.json"
        try:
            self.data: dict[str, dict] = json.loads(self.path.read_text())
        except (OSError, ValueError) as e:
            log.info("no history read from %s (%s)", self.path, e)
            self.data = {}

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)  # never leave a half-written file behind

    # ---- reading

    def entries(self) -> list[tuple[str, dict]]:
        """The library: most recently used first."""
        shown = [kv for kv in self.data.items() if kv[1].get("in_library", True)]
        return sorted(shown, key=lambda kv: kv[1].get("last_used", 0), reverse=True)

    def in_library(self, key: str) -> bool:
        return self.data.get(key, {}).get("in_library", True) if key in self.data else False

    def files(self, key: str) -> list[Path]:
        """Downloaded files of a manga that are still there."""
        found = {Path(f) for f in self.data.get(key, {}).get("downloaded", {}).values()}
        return sorted(f for f in found if f.exists())

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def cover_path(self, key: str) -> Path:
        return self.folder / "covers" / (re.sub(r"[^a-z0-9_.-]+", "_", key.lower()) + ".img")

    def by_chapter(self, key: str) -> list[Path]:
        """The files that are still there, in chapter order (file names like "Ch. 101-110" don't sort)."""
        first: dict[Path, float] = {}
        for c, f in self.data.get(key, {}).get("downloaded", {}).items():
            first[Path(f)] = min(first.get(Path(f), float("inf")), float(c))
        return sorted((f for f in first if f.exists()), key=lambda f: (first[f], f.name))

    def reads(self, key: str) -> dict[str, dict]:
        """Per file: when it was last read here ("read", with "page" and "pages") or opened elsewhere ("opened")."""
        return self.data.get(key, {}).get("reads", {})

    def last_read(self, key: str) -> tuple[Path, dict] | None:
        """The file read or opened most recently, if it's still there."""
        done = [(Path(f), r) for f, r in self.reads(key).items() if Path(f).exists()]
        return max(done, key=lambda fr: max(fr[1].get("read", 0), fr[1].get("opened", 0)), default=None)

    @staticmethod
    def percent(entry: dict) -> float:
        total = entry.get("total_chapters") or 0
        return min(1.0, len(entry.get("downloaded", {})) / total) if total else 0.0

    # ---- writing

    def remember(self, key: str, url: str, title: str, total: int, status: str, cover: bytes | None) -> dict:
        """Create or refresh a manga's entry after it is looked up."""
        entry = self.data.setdefault(key, {"downloaded": {}, "failed": [], "pending": [], "known": []})
        entry.update(url=url, title=title, total_chapters=total, status=status, last_used=time.time(), in_library=True)
        if cover:
            path = self.cover_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(cover)
        self.save()
        return entry

    def mark_seen(self, key: str, chapters: list[str]) -> None:
        """The user has now seen these chapters, so they no longer count as new."""
        entry = self.data[key]
        entry["known"] = chapters
        entry["new_chapters"] = 0
        self.save()

    def start_run(self, key: str, chapters: list[str], fmt: str, per_file: int, save_to: str) -> None:
        entry = self.data[key]
        downloaded = entry["downloaded"]
        entry["pending"] = sorted(set(entry["pending"]) | {c for c in chapters if c not in downloaded},
                                  key=float)
        entry["last_run"] = {"format": fmt, "per_file": per_file, "save_to": save_to, "started": time.time()}
        entry["last_used"] = time.time()
        self.save()

    def file_done(self, key: str, chapters: list[str], path: str) -> None:
        entry = self.data[key]
        for c in chapters:
            entry["downloaded"][c] = path
        done = set(chapters)
        entry["pending"] = [c for c in entry["pending"] if c not in done]
        entry["failed"] = [c for c in entry["failed"] if c not in done]
        entry["last_download"] = time.time()
        log.info("%s: chapters %s saved as %s", key, ",".join(chapters), path)
        self.save()

    def file_failed(self, key: str, chapters: list[str]) -> None:
        entry = self.data[key]
        bad = set(chapters)
        entry["pending"] = [c for c in entry["pending"] if c not in bad]
        entry["failed"] = sorted(set(entry["failed"]) | bad, key=float)
        log.warning("%s: chapters %s failed", key, ",".join(chapters))
        self.save()

    def log_read(self, key: str, path: Path, page: int, pages: int) -> None:
        """Remember where the reader is in a file, so it can carry on from there."""
        self.data[key].setdefault("reads", {}).setdefault(str(path), {}).update(read=time.time(), page=page, pages=pages)
        self.save()

    def log_opened(self, key: str, path: Path) -> None:
        self.data[key].setdefault("reads", {}).setdefault(str(path), {})["opened"] = time.time()
        self.save()

    def checked(self, key: str, total: int, status: str, chapters: list[str]) -> int:
        """Record a background check of the site; returns how many chapters are new."""
        entry = self.data[key]
        known = set(entry.get("known", []))
        new = len([c for c in chapters if c not in known]) if known else 0
        entry.update(total_chapters=total, status=status, new_chapters=new, last_check=time.time())
        self.save()
        return new

    def prune_missing(self) -> None:
        """Forget downloads whose files were deleted or moved, so they can be downloaded again."""
        changed = False
        for entry in self.data.values():
            gone = [c for c, f in entry.get("downloaded", {}).items() if not Path(f).exists()]
            for f in sorted({entry["downloaded"][c] for c in gone}):
                log.warning("%s: forgetting %s, the file is gone (deleted or moved)", entry.get("title"), f)
            for c in gone:
                del entry["downloaded"][c]
            changed |= bool(gone)
            stale = [f for f in entry.get("reads", {}) if not Path(f).exists()]
            for f in stale:
                del entry["reads"][f]
            changed |= bool(stale)
        if changed:
            self.save()

    @staticmethod
    def folder(entry: dict) -> Path | None:
        """The folder holding most of a manga's downloaded files that still exist."""
        counts: dict[Path, int] = {}
        for f in entry.get("downloaded", {}).values():
            if Path(f).exists():
                counts[Path(f).parent] = counts.get(Path(f).parent, 0) + 1
        return max(counts, key=counts.get) if counts else None

    def forget(self, key: str) -> None:
        """Take a manga off the library. Its files stay, and so does the record of them, so opening
        it again still shows what is downloaded."""
        if self.files(key):
            self.data[key]["in_library"] = False
        else:
            self.data.pop(key, None)
            self.cover_path(key).unlink(missing_ok=True)
        self.save()

    def delete_files(self, key: str) -> int:
        """Delete a manga's downloaded files (only those, then its folder if that leaves it empty)
        and forget it completely. Returns how many files were deleted."""
        files = self.files(key)
        for f in files:
            f.unlink(missing_ok=True)
        for folder in {f.parent for f in files}:
            try:
                folder.rmdir()  # only succeeds when empty
            except OSError:
                pass
        self.data.pop(key, None)
        self.cover_path(key).unlink(missing_ok=True)
        self.save()
        return len(files)


def ago(timestamp: float | None) -> str:
    if not timestamp:
        return "never"
    seconds = time.time() - timestamp
    for size, unit in ((86400 * 365, "year"), (86400 * 30, "month"), (86400 * 7, "week"),
                       (86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"
