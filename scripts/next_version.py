#!/usr/bin/env python3
"""Works out the next version from the conventional commits since the last v* tag.

fix:/perf: -> patch, feat: -> minor, a ! after the type or BREAKING CHANGE in the body -> major.
Other types (docs:, chore:, ci:, refactor:, ...) don't make a release. The first release is 1.0.0.

    python scripts/next_version.py [--notes FILE] [--write-version]

Prints the version (or nothing), writes release=true/false and version=X.Y.Z to $GITHUB_OUTPUT
when it's set, the release notes to FILE, and with --write-version the number into version.py.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)$")
COMMIT_RE = re.compile(r"(?P<type>\w+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<subject>.+)")
SECTIONS = [("breaking", "Breaking changes"), ("feat", "New"), ("fix", "Fixes"), ("perf", "Faster")]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def last_tag() -> tuple[str, tuple[int, int, int]] | None:
    for tag in git("tag", "--list", "v*", "--sort=-v:refname").split():
        if m := TAG_RE.match(tag):
            return tag, (int(m[1]), int(m[2]), int(m[3]))
    return None


def commits(since: str | None) -> list[tuple[str, str]]:
    """(subject, body) of each commit after `since`, oldest first."""
    out = git("log", "--reverse", "--format=%s%x1f%b%x1e", f"{since}..HEAD" if since else "HEAD")
    return [tuple(entry.strip("\n").split("\x1f", 1)) for entry in out.split("\x1e") if entry.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--write-version", action="store_true")
    args = parser.parse_args()

    found = last_tag()
    bump = 0  # 0 none, 1 patch, 2 minor, 3 major
    notes: dict[str, list[str]] = {key: [] for key, _ in SECTIONS}
    for subject, body in commits(found[0] if found else None):
        m = COMMIT_RE.match(subject)
        if not m:
            continue
        kind = m["type"].lower()
        text = f"{m['scope']}: {m['subject']}" if m["scope"] else m["subject"]
        if m["bang"] or "BREAKING CHANGE" in body:
            bump = max(bump, 3)
            notes["breaking"].append(text)
        elif kind == "feat":
            bump = max(bump, 2)
            notes["feat"].append(text)
        elif kind in ("fix", "perf"):
            bump = max(bump, 1)
            notes[kind].append(text)

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
        for key, heading in SECTIONS:
            if notes[key]:
                parts.append(f"### {heading}\n" + "".join(f"- {line}\n" for line in notes[key]))
        parts.append("Download **Nyanga-Setup-{0}.exe** below and run it. Already installed? "
                     "The app updates itself.\n".format(version))
        args.notes.write_text("\n".join(parts), encoding="utf-8")
    if args.write_version:
        (ROOT / "version.py").write_text(
            '"""The app\'s version. The release workflow writes the real number here before building."""\n\n'
            f'__version__ = "{version}"\n', encoding="utf-8")


if __name__ == "__main__":
    main()
