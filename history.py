"""Download history: which chapters of which manga are downloaded, failed or still waiting.

Stored as JSON in library/history.json next to the script (git-ignored), with covers in
library/covers/. History is kept per chapter, so it stays right if the number of chapters
per file changes between downloads.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import paths

LIBRARY = paths.DATA / "library"


def chapter_key(number: float) -> str:
    return f"{number:g}"


class History:
    def __init__(self, folder: Path = LIBRARY):
        self.folder = folder
        self.path = folder / "history.json"
        try:
            self.data: dict[str, dict] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)  # never leave a half-written file behind

    # ---- reading

    def entries(self) -> list[tuple[str, dict]]:
        """Most recently used first."""
        return sorted(self.data.items(), key=lambda kv: kv[1].get("last_used", 0), reverse=True)

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def cover_path(self, key: str) -> Path:
        return self.folder / "covers" / (re.sub(r"[^a-z0-9_.-]+", "_", key.lower()) + ".img")

    @staticmethod
    def percent(entry: dict) -> float:
        total = entry.get("total_chapters") or 0
        return min(1.0, len(entry.get("downloaded", {})) / total) if total else 0.0

    # ---- writing

    def remember(self, key: str, url: str, title: str, total: int, status: str, cover: bytes | None) -> dict:
        """Create or refresh a manga's entry after it is looked up."""
        entry = self.data.setdefault(key, {"downloaded": {}, "failed": [], "pending": [], "known": []})
        entry.update(url=url, title=title, total_chapters=total, status=status, last_used=time.time())
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
        self.save()

    def file_failed(self, key: str, chapters: list[str]) -> None:
        entry = self.data[key]
        bad = set(chapters)
        entry["pending"] = [c for c in entry["pending"] if c not in bad]
        entry["failed"] = sorted(set(entry["failed"]) | bad, key=float)
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
            for c in gone:
                del entry["downloaded"][c]
            changed |= bool(gone)
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
        """Remove a manga from the library. Its downloaded files are left alone."""
        self.data.pop(key, None)
        self.cover_path(key).unlink(missing_ok=True)
        self.save()


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
