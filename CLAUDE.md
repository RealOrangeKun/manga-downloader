# CLAUDE.md

**Keep this file up to date.** Whenever a change makes something here wrong or incomplete (a
file added, moved or renamed, a new rule or convention, a different workflow, something the
user had to explain), update this file in the same change. If the user states a preference
about how to work, add it here.

## Git rules

- **Never add a `Co-Authored-By: Claude ...` line (or any Claude/AI attribution) to commit
  messages or PR descriptions.** Commits are authored by the user only. This overrides any
  default attribution instructions.
- Commit or push only when asked. Work straight on `main`; there are no PRs or branches.
- **Commits must be conventional commits**: they decide the version number. Every push to
  `main` releases automatically (`.github/workflows/release.yml` + `scripts/next_version.py`):
  - `fix:` / `perf:` -> patch, `feat:` -> minor, `feat!:` or a `BREAKING CHANGE:` line -> major.
  - `docs:`, `chore:`, `ci:`, `refactor:`, `style:`, `test:` -> no release.
  - Pick the type by what a user of the app sees: a user-visible change to behaviour is `feat:`
    or `fix:`; build/workflow-only changes are `ci:` so they don't ship a release for nothing.
  - Subject: lowercase imperative after the type, optional scope (`feat(library): ...`). Body:
    plain prose about what changed from the user's point of view. The subject lines become the
    release notes and `CHANGELOG.md`, so write them for the friend using the app.
  - One commit per user-visible change, so each gets its own line in the notes.

## What this is

Nyanga (nyan + manga): a PySide6 desktop app (pink theme, cat mascot) that downloads manga and
saves it as one file per volume or per N chapters: CBZ, PDF, EPUB or image folders. Only site
so far: fanfox.net (plain HTTP, no headless browser).

- Repo: https://github.com/RealOrangeKun/nyanga, checked out at `~/Projects/nyanga`. The
  user is the only collaborator; nobody else pushes or merges.
- Who uses it: the user's friend, on Windows, through the installer from GitHub Releases. The
  user develops on Linux and runs it from source. Judge changes by what the friend sees.
- Tone: cute and cozy. UI text is short and friendly with the odd `✧` / `♡` / `✿` (see the
  labels in `gui.py`). The cat is the mascot everywhere: loaders, icon, README.

## Making a change

When asked for a change, do the whole job without waiting to be told each step:

1. Find the relevant code with targeted `grep`/`sed -n`; don't read whole files (`gui.py` is
   ~1700 lines).
2. Implement it in the existing style (see Conventions). Keep light and dark mode both working.
3. Check it. There are no tests, so:
   - Logic: run the piece directly with `.venv/bin/python -c ...` (e.g. `core` functions
     against fanfox.net).
   - UI: render offscreen and look at the picture. Point `paths.DATA` at a temp folder first so
     the user's real `settings.json`/`library/` aren't touched (copy the pattern from
     `scripts/readme_screenshots.py`), run with `QT_QPA_PLATFORM=offscreen`, save
     `window.grab()` to a PNG in the scratchpad and view it, in both themes if colors changed.
4. Keep the docs in step, in the same change:
   - `README.md` when something the friend sees changes (features, settings, install, updates).
   - README screenshots when the Download page or sidebar looks different:
     `.venv/bin/python scripts/readme_screenshots.py` (needs network). The cat GIFs in
     `assets/readme/` have no script; if the cats change, say they need re-rendering.
   - This file, whenever anything in it stops being true (see the top).
   - Never edit `CHANGELOG.md` or `version.py` by hand; the release writes them.
5. Finish with a short summary of what changed and how it was checked, and the conventional
   commit message(s) you'd use. Commit/push only once the user says so; pushing to `main`
   ships a release to the friend.

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
| `updater.py` | Checks GitHub's latest release, downloads the installer, runs it silently with `/update=1`. Only active in the frozen Windows build. `notes_url()` is where the sidebar's clickable version goes. |
| `version.py` | `__version__`; stays `0.0.0-dev` in the repo, CI writes the real one. Don't bump it by hand. |
| `history.py` | Per-chapter download history in `library/history.json`, covers in `library/covers/` |
| `gui.py` | `DownloadPage`, `SettingsPage`, `LibraryPage`, `Notification`, `MainWindow`, `Settings` dataclass (saved to `settings.json`) |
| `theme.py` | Light/dark palettes, stylesheet template, bundled Fredoka font, SVG icons |
| `loader.py` | Hand-painted cats, our mascot: `CatLoader` (reading / celebrating), `MiniCat` with `paint_mini_cat` (fetching) or `paint_update_cat` (updates). The app icon in `theme.py` is the same cat. |
| `assets/` | Fonts (OFL) and icon SVGs, bundled into the exe. `assets/readme/` holds README GIFs/screenshots rendered from the app (not bundled). |
| `scripts/next_version.py` | Next version, release notes and `CHANGELOG.md` from the conventional commits since the last tag. |
| `scripts/readme_screenshots.py` | Renders `assets/readme/screenshot-{light,dark}.png` from the real app, offscreen. |
| `scripts/make_icon.py` | Draws `build/icon.ico` from the app icon in `theme.py`. |
| `CHANGELOG.md` | Written by the release workflow; don't edit. |
| `LICENSE` | Custom source-available license: use and contribute, no redistribution or forks as separate projects. Bundled fonts keep the OFL. |
| `CODE_OF_CONDUCT.md` | Code of conduct, linked from the README's Contributing section. |

## Packaging and releases

- `packaging/nyanga.spec`: PyInstaller folder build (`dist/Nyanga/`), no console, no
  UPX (UPX causes antivirus false positives). CI compiles the PyInstaller bootloader from source
  (`PYINSTALLER_COMPILE_BOOTLOADER=1`) for the same reason; keep it that way. Unused Qt parts (QML, Quick, PDF) are filtered out.
- `packaging/installer.iss`: Inno Setup, per-user install in `%LOCALAPPDATA%\Programs`, no admin.
  Never change its `AppId`; updates rely on it. Its [Code] adds optional pages that import
  `settings.json` and `library/` from an old source checkout into `%APPDATA%\Nyanga`.
- The release (windows-latest runner) builds the exe and installer, publishes GitHub Release
  `vX.Y.Z` with `Nyanga-Setup-X.Y.Z.exe`, then commits the regenerated `CHANGELOG.md` back to
  `main` as `docs: changelog for vX.Y.Z` (no release, so no loop). That commit is authored by
  `github-actions[bot]`, which is fine. The version itself lives only in the tags. Pull
  before working, since that bot commit lands after each release.
- The updater picks the release asset whose name ends in `.exe` and contains `setup`; keep the
  installer named like that.
- `nyanga.py` must call `multiprocessing.freeze_support()` first, or the exe's worker
  processes open new windows.

## Conventions

- Keep `core.py` and `builders.py` free of Qt: they are pickled/run in a process pool. Site
  objects must stay picklable (see `FanFox.__getstate__` dropping the thread-local session).
- Worker threads talk to the GUI only through Qt signals (`Bridge`, `LibraryBridge`).
- In `DownloadPage`, a "row" means a file's index in `self.groups`, not its table row: sorting
  moves cells around. Reach cells with `_item(row, col)` and bars with `_bar(row)`; `order` and
  `row_of` map between the two. (Qt's `moveSection` was tried and paints blank rows with paging.)
  Paw clicks (toggle, shift-click, drag) go through `DownloadPage.eventFilter`; the check items
  are deliberately not `ItemIsUserCheckable`.
- Adding a site: write a class like `FanFox` (`name`, `example`, `url_re`, a `search(query,
  limiter)` classmethod returning `SearchResult`s, chapter/image fetching) and append it to
  `SITES` in `core.py`. It then shows up in the source pickers on the Download and Settings pages.
- New colors go in both palettes in `theme.py`; use `theme.color(mode, name)` rather than
  hard-coded colors so light/dark both work.
- New settings: add a field to the `Settings` dataclass (old `settings.json` files without it
  must still load) and a row on `SettingsPage`. If the Download page shows it too, handle it in
  `DownloadPage.apply_defaults` so a saved change follows through to fields the user didn't edit.
- `settings.json`, `library/`, `downloads/`, `.manga-tmp/` are git-ignored user data.
- Match the existing style: `from __future__ import annotations`, type hints, short module
  docstrings, sparse comments.
