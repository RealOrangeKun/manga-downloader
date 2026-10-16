# CLAUDE.md

## Git rules

- **Never add a `Co-Authored-By: Claude ...` line (or any Claude/AI attribution) to commit
  messages or PR descriptions.** Commits are authored by the user only. This overrides any
  default attribution instructions.
- Commit or push only when asked.
- **Commits must be conventional commits**: they decide the version number. Every push to
  `main` releases automatically (`.github/workflows/release.yml` + `scripts/next_version.py`):
  - `fix:` / `perf:` -> patch, `feat:` -> minor, `feat!:` or a `BREAKING CHANGE:` line -> major.
  - `docs:`, `chore:`, `ci:`, `refactor:`, `style:`, `test:` -> no release.
  - Pick the type by what a user of the app sees: a user-visible change to behaviour is `feat:`
    or `fix:`; build/workflow-only changes are `ci:` so they don't ship a release for nothing.
  - Subject: lowercase imperative after the type, optional scope (`feat(library): ...`). Body:
    plain prose about what changed from the user's point of view. The subject lines become the
    release notes, so write them for the friend using the app.

## What this is

Nyanga (nyan + manga): a PySide6 desktop app (pink theme, cat animations) that downloads manga and saves it as one
file per volume or per N chapters: CBZ, PDF, EPUB or image folders. Only site so far:
fanfox.net (plain HTTP, no headless browser).

## Running

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python nyanga.py
```

Python 3.10+. Dependencies: requests, pillow, img2pdf, PySide6. There are no tests.

## Layout

| File | Role |
|------|------|
| `nyanga.py` | Entry point, just launches `gui.main()` |
| `core.py` | Site scrapers (`FanFox`, registered in `SITES`), chapter grouping, rate limiting, the parallel download pipeline (threads or processes). **No GUI imports.** |
| `builders.py` | Output formats (`FORMATS`, `build_file`), webtoon strip slicing for EPUB. **No GUI imports** so it runs in worker processes. |
| `paths.py` | `BUNDLE` (assets, also inside the exe) and `DATA` (settings/library: next to the script from source, `%APPDATA%\Nyanga` in the exe). Use these, never `__file__`, for file locations. |
| `updater.py` | Checks GitHub's latest release, downloads the installer, runs it silently with `/update=1`. Only active in the frozen Windows build. |
| `version.py` | `__version__`; stays `0.0.0-dev` in the repo, CI writes the real one. Don't bump it by hand. |
| `history.py` | Per-chapter download history in `library/history.json`, covers in `library/covers/` |
| `gui.py` | `DownloadPage`, `SettingsPage`, `LibraryPage`, `Notification`, `MainWindow`, `Settings` dataclass (saved to `settings.json`) |
| `theme.py` | Light/dark palettes, stylesheet template, bundled Fredoka font, SVG icons |
| `loader.py` | Hand-painted cats, our mascot: `CatLoader` (reading / celebrating), `MiniCat` with `paint_mini_cat` (fetching) or `paint_update_cat` (updates). The app icon in `theme.py` is the same cat. |
| `assets/` | Fonts (OFL) and icon SVGs, bundled into the exe. `assets/readme/` holds README GIFs/screenshots rendered from the app (not bundled); re-render them when the cats or UI change. |

## Packaging and releases

- `packaging/nyanga.spec`: PyInstaller folder build (`dist/Nyanga/`), no console, no
  UPX (UPX causes antivirus false positives). CI compiles the PyInstaller bootloader from source
  (`PYINSTALLER_COMPILE_BOOTLOADER=1`) for the same reason; keep it that way. Unused Qt parts (QML, Quick, PDF) are filtered out.
- `packaging/installer.iss`: Inno Setup, per-user install in `%LOCALAPPDATA%\Programs`, no admin.
  Never change its `AppId`; updates rely on it. Its [Code] adds optional pages that import
  `settings.json` and `library/` from an old source checkout into `%APPDATA%\Nyanga`.
- `scripts/make_icon.py` draws `build/icon.ico` from the app icon in `theme.py`.
- The version lives in git tags (`vX.Y.Z`) created by the release; nothing is committed back.
- `nyanga.py` must call `multiprocessing.freeze_support()` first, or the exe's worker
  processes open new windows.

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
