# manga-downloader

A small pink desktop app that downloads a manga and saves it as one file per volume
(CBZ, PDF, EPUB or plain image folders).

## Supported sites

- fanfox.net (`https://fanfox.net/manga/<title>/`)

## Install (Windows)

1. Open the [latest release](https://github.com/RealOrangeKun/manga-downloader/releases/latest) and
   download **MangaDownloader-Setup-x.y.z.exe**.
2. Run it. Windows may say "Windows protected your PC" because the app isn't signed: click
   **More info**, then **Run anyway**. No admin rights are needed.
3. Used it with Python before? On the **Bring your old settings** page, tick the import and pick
   the folder that has `manga_dl.py` in it. Its `settings.json` and `library` folder (history
   and covers) are copied into the installed app.
4. Open **Manga Downloader** from the Start menu.

That's the only time you install it. When a new version is out, the app shows a card with an
**Update now** button; it downloads the new version, installs it and reopens by itself. Your
settings and library are kept (they live in `%APPDATA%\Manga Downloader`).

## Run from source

Needs Python 3.10 or newer. Run these from the project folder.

Linux / macOS:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manga_dl.py
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manga_dl.py
```

After the first time, only the last line is needed.

## Using it

**Download page**

1. Paste a title link and press **Find**. The cover, title, genres and chapter count appear.
2. Pick the format, the folder to save to and, if the site has no volume numbers for the
   title, how many chapters go in each file.
3. Tick the files you want in the table (or use Select all / none / first N).
4. Press **Download**. Each file gets its own progress bar; **Cancel** stops after the
   current page, and **Open folder** shows the results when it's done.

Running it again with the same choices resumes where it stopped. Files that already exist
are skipped, so delete a file to rebuild it.

**Library page**

Every manga you've downloaded gets a card with its cover, how much of the series you have
(chapters downloaded out of all chapters on the site), and what failed or is still waiting.

- **Continue** picks up chapters from a download that was cancelled or interrupted.
- **Retry failed** downloads the chapters that failed again.
- **Open** loads the manga on the Download page with what you already have marked, so you can
  pick more.
- Opening the page checks each manga for new chapters (at most once every 5 minutes) and shows
  a "new" badge.
- If you delete or move a downloaded file, it no longer counts as downloaded and can be
  downloaded again. The × on a card removes it from the library; your files stay.

History lives in `library/` next to `manga_dl.py` (git-ignored), or in `%APPDATA%\Manga Downloader`
in the installed app.

**Settings page** (saved to `settings.json` next to `manga_dl.py`, git-ignored; in the installed app
`%APPDATA%\Manga Downloader`)

- Theme: light, dark, or match your system (the moon/sun button in the sidebar switches too).
- Default download folder and temp folder, and whether to keep temp files.
- Default format and chapters per file.
- **Files at once**: how many files are made in parallel. `1` does one at a time.
- **Run downloads on**: threads (recommended) or separate processes. Downloading mostly waits
  on the network, so processes rarely help; building files uses separate cores either way.
- **Delay between requests**: shared by all workers, so more workers never means more
  requests per second. Sites ask for human browsing speed; going too low can get you blocked.

## How the parallel part works

Downloads run on real OS threads; Python releases the GIL while waiting on the network, so
they run at the same time. Building files (EPUB slicing, PDF, image conversion) is CPU work,
so it runs in separate processes and can use several cores at once.

## Releases

Every push to `main` runs [the release workflow](.github/workflows/release.yml). It reads the
commit messages since the last release ([conventional commits](https://www.conventionalcommits.org)):

| Commit starts with | Example | New version |
|---|---|---|
| `fix:` or `perf:` | `fix: retry images that time out` | 1.0.0 → 1.0.1 |
| `feat:` | `feat(library): sort by last read` | 1.0.1 → 1.1.0 |
| `feat!:` or a `BREAKING CHANGE:` line | `feat!: new settings format` | 1.1.0 → 2.0.0 |
| `docs:`, `chore:`, `ci:`, `refactor:`, `style:`, `test:` | `docs: fix typo` | no release |

If there's a new version, it builds the exe with PyInstaller ([packaging/manga_dl.spec](packaging/manga_dl.spec)),
wraps it in an Inno Setup installer ([packaging/installer.iss](packaging/installer.iss)), and publishes a
GitHub Release tagged `vX.Y.Z` with the installer and notes made from the commits. The tag is
the source of the version; `version.py` says `0.0.0-dev` in the repo and gets the real number
during the build.

To build locally on Windows: `pip install pyinstaller`, `python scripts/make_icon.py`,
`pyinstaller packaging/manga_dl.spec --noconfirm`, then `ISCC.exe /DAppVersion=1.2.3 packaging\installer.iss`.

## Notes

- Webtoons (long vertical strips) are cut into screen-sized pages in EPUB. CBZ and PDF keep
  the original strips; use a reader with a continuous-scroll mode for those.
- Code layout: `core.py` (sites, rate limiting, download pipeline), `builders.py` (output
  formats), `gui.py` (the window), `updater.py` (checks GitHub for new versions and installs them),
  `paths.py` (where assets and user data live, from source and in the exe). To add a site, write a class like `FanFox` in `core.py`
  with `url_re`, `info()`, `page_urls()` and `image()`, and add it to `SITES`.
- The interface uses the bundled [Fredoka](https://github.com/hafontia/Fredoka-One) font
  (`assets/fonts`, SIL Open Font License, see `assets/fonts/OFL.txt`). The icons and the
  little book mascot in `theme.py` and `assets/icons` were drawn for this project.
