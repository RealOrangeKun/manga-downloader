#!/usr/bin/env python3
"""Packs the app folder for updates that only download what changed.

    pack_update.py dist/Nyanga dist/Nyanga-update-linux-x86_64

writes <name>.zip (every file compressed on its own) and <name>.json, the manifest: each file's
size, hash and where its compressed bytes sit in the zip, so the updater can fetch just the files
it doesn't have yet with byte-range requests. Symlinks are listed in the manifest, not the zip.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    folder, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    archive = out.with_name(out.name + ".zip")
    items = sorted(p for p in folder.rglob("*") if p.is_symlink() or p.is_file())
    files, links = [], []
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in items:
            name = path.relative_to(folder).as_posix()
            if path.is_symlink():
                links.append({"path": name, "target": str(path.readlink())})
                continue
            zf.write(path, name)
            files.append({"path": name, "size": path.stat().st_size, "sha256": sha256(path),
                          "mode": path.stat().st_mode & 0o777})
    # Where each file's deflated bytes start: after its local header, whose length the zip only
    # records in the header itself.
    with zipfile.ZipFile(archive) as zf, archive.open("rb") as raw:
        for entry, info in zip(files, zf.infolist()):
            raw.seek(info.header_offset + 26)
            name_len, extra_len = struct.unpack("<HH", raw.read(4))
            entry["offset"] = info.header_offset + 30 + name_len + extra_len
            entry["length"] = info.compress_size
            entry["method"] = info.compress_type
    out.with_name(out.name + ".json").write_text(json.dumps({"files": files, "links": links}))
    print(f"{archive}: {len(files)} files, {len(links)} links, {archive.stat().st_size >> 20} MB")


if __name__ == "__main__":
    main()
