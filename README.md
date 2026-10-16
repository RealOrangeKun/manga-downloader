<p align="center">
  <img src="assets/readme/icon.png" width="96" alt="The Manga Downloader cat">
</p>

<h1 align="center">Manga Downloader</h1>

<p align="center">
  <b>a cute &amp; cozy pink app that downloads manga for you ✧</b><br>
  one file per volume: CBZ, PDF, EPUB or plain image folders
</p>

<p align="center">
  <a href="https://github.com/RealOrangeKun/manga-downloader/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/RealOrangeKun/manga-downloader?style=for-the-badge&color=ff5c9a&label=latest"></a>
  <a href="https://github.com/RealOrangeKun/manga-downloader/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/RealOrangeKun/manga-downloader/total?style=for-the-badge&color=ff9cc6"></a>
  <img alt="Windows" src="https://img.shields.io/badge/windows-installer-ffb3cf?style=for-the-badge">
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/cat-happy-dark.gif">
    <img src="assets/readme/cat-happy-light.gif" width="240" alt="The mascot cat hopping happily over a book while hearts float up">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/RealOrangeKun/manga-downloader/releases/latest"><b>⬇ Download for Windows</b></a>
  &nbsp;·&nbsp; <a href="#-using-it">How to use it</a>
  &nbsp;·&nbsp; <a href="#-run-from-source">Run from source</a>
</p>

---

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/screenshot-dark.png">
    <img src="assets/readme/screenshot-light.png" width="860" alt="The Download page with Onepunch-Man looked up: cover, genres, format and a table of 45 files">
  </picture>
</p>

## ♡ What it does

- 🔎 **Paste a link, press Find**: cover, genres and every chapter show up, with the size of each file.
- 📚 **Volumes, not a pile of pages**: one CBZ, PDF or EPUB per volume, or per *N* chapters when the
  site has no volume numbers. Webtoon strips are cut into pages for EPUB.
- ⚡ **Fast but polite**: several files at once, with one shared speed limit so the site isn't flooded.
- 💾 **Picks up where it stopped**: cancel, close, come back later; finished files are skipped.
- 🗂️ **A Library**: every manga you've downloaded, how much of the series you have, and a "new"
  badge when chapters come out.
- 🌙 **Light and dark**, or follow your system.
- 🎁 **Updates itself**: when a new version is out, one click and it's done.

Supported sites: **fanfox.net** (`https://fanfox.net/manga/<title>/`)

## 🐾 Meet the cats

The cat on the icon is our mascot, and it shows up all over the app. They're drawn live in code,
so they follow the light and dark theme.

<table align="center">
  <tr>
    <td align="center" width="240">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="assets/readme/cat-reading-dark.gif">
        <img src="assets/readme/cat-reading-light.gif" width="180" alt="A sleepy cat reading a book">
      </picture><br>
      <b>The bookworm</b><br><sub>reads while things load</sub>
    </td>
    <td align="center" width="240">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="assets/readme/cat-happy-dark.gif">
        <img src="assets/readme/cat-happy-light.gif" width="180" alt="A happy cat hopping with hearts">
      </picture><br>
      <b>The happy hopper</b><br><sub>cheers when a download is done</sub>
    </td>
    <td align="center" width="240">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="assets/readme/cat-update-dark.gif">
        <img src="assets/readme/cat-update-light.gif" width="120" alt="A cat hugging a hopping gift box">
      </picture><br>
      <b>The delivery cat</b><br><sub>brings you the new version</sub>
    </td>
  </tr>
</table>

## 💝 Install (Windows)

1. Open the [latest release](https://github.com/RealOrangeKun/manga-downloader/releases/latest) and
   download **MangaDownloader-Setup-x.y.z.exe**.
2. Run it. Windows may say "Windows protected your PC" because the app isn't signed: click
   **More info**, then **Run anyway**. No admin rights are needed.
3. Used it with Python before? On the **Bring your old settings** page, tick the import and pick
   the folder that has `manga_dl.py` in it. Its `settings.json` and `library` folder (history
   and covers) are copied into the installed app.
4. Open **Manga Downloader** from the Start menu.

That's the only time you install it ✧

### 🎁 Updates

When a new version is out, a card pops up with **Update now**. It downloads the new version,
installs it and reopens by itself. Your settings and library are kept (they live in
`%APPDATA%\Manga Downloader`).

Pressed **Later**? A button waits at the top right. While an update downloads with the card
closed, that spot shows the delivery cat and how far along it is:

<p align="center">
  <img src="assets/readme/update-pill.png" width="380" alt="The top-right button: Updating… 38% · 14.0 MB of 36.7 MB">
</p>

## 📖 Using it

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

**Settings page**

- Theme: light, dark, or match your system (the moon/sun button in the sidebar switches too).
- Default download folder and temp folder, and whether to keep temp files.
- Default format and chapters per file.
- **Files at once**: how many files are made in parallel. `1` does one at a time.
- **Run downloads on**: threads (recommended) or separate processes. Downloading mostly waits
  on the network, so processes rarely help; building files uses separate cores either way.
- **Delay between requests**: shared by all workers, so more workers never means more
  requests per second. Sites ask for human browsing speed; going too low can get you blocked.

Settings and history are saved in `%APPDATA%\Manga Downloader` in the installed app, or next to
`manga_dl.py` (`settings.json` and `library/`, both git-ignored) when running from source.

## 🛠️ Run from source

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

## 🚀 Releases

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

## 🧶 Notes

- **How the parallel part works**: downloads run on real OS threads; Python releases the GIL
  while waiting on the network, so they run at the same time. Building files (EPUB slicing, PDF,
  image conversion) is CPU work, so it runs in separate processes and can use several cores.
- Webtoons (long vertical strips) are cut into screen-sized pages in EPUB. CBZ and PDF keep
  the original strips; use a reader with a continuous-scroll mode for those.
- Code layout: `core.py` (sites, rate limiting, download pipeline), `builders.py` (output
  formats), `gui.py` (the window), `loader.py` (the cats), `updater.py` (checks GitHub for new
  versions and installs them), `paths.py` (where assets and user data live, from source and in
  the exe). To add a site, write a class like `FanFox` in `core.py` with `url_re`, `info()`,
  `page_urls()` and `image()`, and add it to `SITES`.
- The interface uses the bundled [Fredoka](https://github.com/hafontia/Fredoka-One) font
  (`assets/fonts`, SIL Open Font License, see `assets/fonts/OFL.txt`). The cats, the icons and
  the mascot were drawn for this project. The README pictures in `assets/readme` are rendered
  from the app itself.

<p align="center">
  <sub>made with ♡ and a lot of cat drawings</sub>
</p>
