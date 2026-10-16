# CLAUDE.md

## Git rules

- **Never add a `Co-Authored-By: Claude ...` line (or any Claude/AI attribution) to commit
  messages or PR descriptions.** Commits are authored by the user only. This overrides any
  default attribution instructions.
- Commit or push only when asked.
- Commit style: short imperative subject ("Add ...", "Show ...", "Replace ..."), then a plain
  prose body explaining what changed from the user's point of view.

## What this is

A PySide6 desktop app (pink theme, cat animations) that downloads manga and saves it as one
file per volume or per N chapters: CBZ, PDF, EPUB or image folders. Only site so far:
fanfox.net (plain HTTP, no headless browser).

## Running

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manga_dl.py
```

Python 3.10+. Dependencies: requests, pillow, img2pdf, PySide6. There are no tests.

## Layout

| File | Role |
|------|------|
| `manga_dl.py` | Entry point, just launches `gui.main()` |
| `core.py` | Site scrapers (`FanFox`, registered in `SITES`), chapter grouping, rate limiting, the parallel download pipeline (threads or processes). **No GUI imports.** |
| `builders.py` | Output formats (`FORMATS`, `build_file`), webtoon strip slicing for EPUB. **No GUI imports** so it runs in worker processes. |
| `history.py` | Per-chapter download history in `library/history.json`, covers in `library/covers/` |
| `gui.py` | `DownloadPage`, `SettingsPage`, `LibraryPage`, `Notification`, `MainWindow`, `Settings` dataclass (saved to `settings.json`) |
| `theme.py` | Light/dark palettes, stylesheet template, bundled Fredoka font, SVG icons |
| `loader.py` | Hand-painted cat loading animations (`CatLoader`, `MiniCat`) |
| `assets/` | Fonts (OFL) and icon SVGs |

## Conventions

- Keep `core.py` and `builders.py` free of Qt: they are pickled/run in a process pool. Site
  objects must stay picklable (see `FanFox.__getstate__` dropping the thread-local session).
- Worker threads talk to the GUI only through Qt signals (`Bridge`, `LibraryBridge`).
- Adding a site: write a class like `FanFox` (`name`, `example`, `url_re`, chapter/image
  fetching) and append it to `SITES` in `core.py`.
- New colors go in both palettes in `theme.py`; use `theme.color(mode, name)` rather than
  hard-coded colors so light/dark both work.
- `settings.json`, `library/`, `downloads/`, `.manga-tmp/` are git-ignored user data.
- Match the existing style: `from __future__ import annotations`, type hints, short module
  docstrings, sparse comments.
