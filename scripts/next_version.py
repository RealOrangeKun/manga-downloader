#!/usr/bin/env python3
"""Works out the next version from the conventional commits since the last v* tag.

fix:/perf: -> patch, feat: -> minor, a ! after the type or BREAKING CHANGE in the body -> major.
Other types (docs:, chore:, ci:, refactor:, ...) don't make a release. The first release is 1.0.0.

    python scripts/next_version.py [--notes FILE] [--changelog FILE] [--whats-new FILE] [--write-version]

Prints the version (or nothing), writes release=true/false and version=X.Y.Z to $GITHUB_OUTPUT
when it's set, the release notes to FILE, the whole changelog (every v* tag plus the new version)
to the --changelog FILE, the same as JSON for the app's What's new screen to the --whats-new FILE
(with each commit's body as the explanation), and with --write-version the number into version.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)$")
COMMIT_RE = re.compile(r"(?P<type>\w+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<subject>.+)")
REPO = "https://github.com/nyanga-app/nyanga-app"
SECTIONS = [("breaking", "Breaking changes"), ("feat", "New"), ("fix", "Fixes"), ("perf", "Faster")]
TRAILER_RE = re.compile(r"^(co-authored-by|signed-off-by|refs?|closes|fixes):", re.I)


class Change:
    def __init__(self, scope: str | None, subject: str, body: str):
        self.scope, self.subject, self.body = scope, subject, body

    def __str__(self) -> str:
        return f"{self.scope}: {self.subject}" if self.scope else self.subject

    def friendly(self, kind: str) -> dict:
        """The change as the app shows it: a sentence-case title, its area and the body as one paragraph."""
        lines = [line.strip() for line in self.body.splitlines() if not TRAILER_RE.match(line.strip())]
        detail = " ".join(line.removeprefix("BREAKING CHANGE:").strip() for line in lines if line)
        return {"kind": kind, "area": (self.scope or "").capitalize(),
                "title": self.subject[:1].upper() + self.subject[1:], "detail": detail}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def tags() -> list[tuple[str, tuple[int, int, int]]]:
    """Every vX.Y.Z tag, oldest first."""
    found = [(tag, TAG_RE.match(tag)) for tag in git("tag", "--list", "v*", "--sort=v:refname").split()]
    return [(tag, (int(m[1]), int(m[2]), int(m[3]))) for tag, m in found if m]


def commits(since: str | None, until: str = "HEAD") -> list[tuple[str, str]]:
    """(subject, body) of each commit after `since` up to `until`, oldest first."""
    out = git("log", "--reverse", "--format=%s%x1f%b%x1e", f"{since}..{until}" if since else until)
    return [tuple(entry.strip("\n").split("\x1f", 1)) for entry in out.split("\x1e") if entry.strip()]


def classify(entries: list[tuple[str, str]]) -> tuple[int, dict[str, list[Change]]]:
    """The bump (0 none, 1 patch, 2 minor, 3 major) and the changes per section."""
    bump = 0
    notes: dict[str, list[Change]] = {key: [] for key, _ in SECTIONS}
    for subject, body in entries:
        m = COMMIT_RE.match(subject)
        if not m:
            continue
        kind = m["type"].lower()
        text = Change(m["scope"], m["subject"], body.strip())
        if m["bang"] or "BREAKING CHANGE" in body:
            bump = max(bump, 3)
            notes["breaking"].append(text)
        elif kind == "feat":
            bump = max(bump, 2)
            notes["feat"].append(text)
        elif kind in ("fix", "perf"):
            bump = max(bump, 1)
            notes[kind].append(text)
    return bump, notes


def sections(notes: dict[str, list[Change]]) -> list[str]:
    return [f"### {heading}\n" + "".join(f"- {line}\n" for line in notes[key])
            for key, heading in SECTIONS if notes[key]]


def releases(pending: str) -> list[tuple[str, dict[str, list[Change]], str]]:
    """(version, changes, date) for every tag, newest first, with `pending` (not tagged yet) on top."""
    found, prev = [], None
    for tag, _ in tags():
        found.append((tag[1:], classify(commits(prev, tag))[1], git("log", "-1", "--format=%cs", tag).strip()))
        prev = tag
    if pending:
        found.append((pending, classify(commits(prev))[1], date.today().isoformat()))
    return found[::-1]


def whats_new(pending: str) -> str:
    """Every release's changes as JSON, newest first, for the app's What's new screen."""
    return json.dumps([{"version": version, "date": day,
                        "items": [c.friendly(key) for key, _ in SECTIONS for c in notes[key]]}
                       for version, notes, day in releases(pending)], indent=1, ensure_ascii=False)


def changelog(pending: str) -> str:
    """CHANGELOG.md rebuilt from every tag, newest first, with `pending` (not tagged yet) on top."""
    parts = ["# Changelog\n\nWritten by the release workflow from the commit messages. "
             "Each version is a [GitHub Release](" + REPO + "/releases) with its installer.\n"]
    for version, notes, day in releases(pending):
        parts.append(f"## [{version}]({REPO}/releases/tag/v{version}) ({day})\n")
        parts.extend(sections(notes) or ["Small changes behind the scenes.\n"])
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--changelog", type=Path)
    parser.add_argument("--whats-new", type=Path)
    parser.add_argument("--write-version", action="store_true")
    args = parser.parse_args()

    found = (tags() or [None])[-1]
    bump, notes = classify(commits(found[0] if found else None))
    if found is None:
        version = "1.0.0"
    elif bump:
        major, minor, patch = found[1]
        version = {3: f"{major + 1}.0.0", 2: f"{major}.{minor + 1}.0", 1: f"{major}.{minor}.{patch + 1}"}[bump]
    else:
        version = ""

    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a") as f:
            f.write(f"release={'true' if version else 'false'}\nversion={version}\n")
    if not version:
        return
    print(version)

    if args.notes:
        parts = ["The first release 🎉\n"] if found is None else []
        parts.extend(sections(notes))
        parts.append(f"Windows: download **Nyanga-Setup-{version}.exe** below and run it. "
                     "Linux: download **Nyanga-x86_64.AppImage**, make it executable and open it."
                     + (" Already installed? The app updates itself.\n" if found else "\n"))
        args.notes.write_text("\n".join(parts), encoding="utf-8")
    if args.changelog:
        args.changelog.write_text(changelog(version), encoding="utf-8")
    if args.whats_new:
        args.whats_new.write_text(whats_new(version), encoding="utf-8")
    if args.write_version:
        (ROOT / "version.py").write_text(
            '"""The app\'s version. The release workflow writes the real number here before building."""\n\n'
            f'__version__ = "{version}"\n', encoding="utf-8")


if __name__ == "__main__":
    main()
