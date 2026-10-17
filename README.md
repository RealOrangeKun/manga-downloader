<p align="center">
  <img src="assets/readme/icon.png" width="96" alt="The Nyanga cat">
</p>

<h1 align="center">Nyanga</h1>

<p align="center">
  <b>a cute &amp; cozy pink app that downloads manga for you ✧</b><br>
  <i>nyan + manga: the cat fetches your chapters</i><br>
  one file per volume: CBZ, PDF, EPUB or plain image folders
</p>

<p align="center">
  <a href="https://github.com/RealOrangeKun/nyanga/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/RealOrangeKun/nyanga?style=for-the-badge&color=ff5c9a&label=latest"></a>
  <a href="https://github.com/RealOrangeKun/nyanga/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/RealOrangeKun/nyanga/total?style=for-the-badge&color=ff9cc6"></a>
  <img alt="Windows" src="https://img.shields.io/badge/windows-installer-ffb3cf?style=for-the-badge">
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/cat-happy-dark.gif">
    <img src="assets/readme/cat-happy-light.gif" width="240" alt="The mascot cat hopping happily over a book while hearts float up">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/RealOrangeKun/nyanga/releases/latest"><b>⬇ Download for Windows</b></a>
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

- 🔎 **Search by name**: type a title, pick it from the results, and its cover, genres and every
  chapter show up, with the size of each file.
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

1. Open the [latest release](https://github.com/RealOrangeKun/nyanga/releases/latest) and
   download **Nyanga-Setup-x.y.z.exe**.
2. Run it. Windows may say "Windows protected your PC" because the app isn't signed: click
   **More info**, then **Run anyway**. No admin rights are needed.
3. Used it with Python before? On the **Bring your old settings** page, tick the import and pick
   the folder that has `nyanga.py` in it. Its `settings.json` and `library` folder (history
   and covers) are copied into the installed app.
4. Open **Nyanga** from the Start menu.

That's the only time you install it ✧

### 🎁 Updates

When a new version is out, a card pops up with **Update now**. It downloads the new version,
installs it and reopens by itself. Your settings and library are kept (they live in
`%APPDATA%\Nyanga`). Curious what changed? Click the version at the bottom left for that
version's notes, or see the whole [changelog](CHANGELOG.md).

Pressed **Later**? A button waits at the top right. While an update downloads with the card
closed, that spot shows the delivery cat and how far along it is:

<p align="center">
  <img src="assets/readme/update-pill.png" width="380" alt="The top-right button: Updating… 38% · 14.0 MB of 36.7 MB">
</p>

## 📖 Using it

**Download page**

1. Pick a source, type the manga's name and press **Search**. Click the right one in the
   results; its cover, title, genres and chapter count appear. **Back to results** lets you
   pick another. Pasting a title link instead of a name works too.
2. Pick the format, the folder to save to and, if the site has no volume numbers for the
   title, how many chapters go in each file.
3. Tap the paws of the files you want. Shift-click a paw to tick everything since the last one
   you tapped, or drag across paws to tick (or untick) a run of them. Under the table:
   - **Select all / none**, and **Select page** for just the files on screen.
   - **New ✧**, **Not downloaded** and **Failed** pick files from your download history.
   - **Chapters … to …** ticks every file with chapters in that range.

   Long series are split into pages (20 files each, changeable in Settings); use ‹ › to flip.
   Tap a column title to sort by it: once for up, twice for down, a third time (or a
   right-click) to go back to normal.
4. Press **Download**. Each file gets its own progress bar; **Cancel** stops after the
   current page, and **Open folder** shows the results when it's done.

Running it again with the same choices resumes where it stopped. Files that already exist
are skipped, so delete a file to rebuild it.

Webtoons (long vertical strips) are cut into screen-sized pages in EPUB. CBZ and PDF keep
the original strips; use a reader with a continuous-scroll mode for those.

**Library page**

Every manga you've downloaded gets a card with its cover, how much of the series you have
(chapters downloaded out of all chapters on the site), and what failed or is still waiting.

- **Continue** picks up chapters from a download that was cancelled or interrupted.
- **Retry failed** downloads the chapters that failed again.
- **Folder** opens the folder with that manga's downloaded files.
- **Open** loads the manga on the Download page with what you already have marked, so you can
  pick more.
- Opening the page checks each manga for new chapters (at most once every 5 minutes) and shows
  a "new" badge.
- If you delete or move a downloaded file, it no longer counts as downloaded and can be
  downloaded again. The × on a card removes it from the library; your files stay.

**Settings page**

- Theme: light, dark, or match your system (the moon/sun button in the sidebar switches too).
- Default source: the site the Download page searches unless you pick another.
- Default download folder and temp folder, and whether to keep temp files.
- Default format and chapters per file.
- Files per page: how many files the Download page lists at once.
- Change something and **Save** or **Undo** it before leaving the page. Saving new defaults
  also updates a manga that's open on the Download page, except for the fields you changed
  there yourself.
- **Files at once**: how many files are made in parallel. `1` does one at a time.
- **Run downloads on**: threads (recommended) or separate processes. Downloading mostly waits
  on the network, so processes rarely help; building files uses separate cores either way.
- **Delay between requests**: shared by all workers, so more workers never means more
  requests per second. Sites ask for human browsing speed; going too low can get you blocked.

Settings and history are saved in `%APPDATA%\Nyanga` in the installed app, or next to
`nyanga.py` (`settings.json` and `library/`, both git-ignored) when running from source.

## 🛠️ Run from source

Needs Python 3.10 or newer. Run these from the project folder.

Linux / macOS:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python nyanga.py
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python nyanga.py
```

After the first time, only the last line is needed.

## 🔏 Before sharing it more widely

The installer isn't code-signed, so Windows SmartScreen shows "Windows protected your PC" with
an unknown publisher the first time someone runs it from a browser download. The installed app
and its automatic updates aren't flagged: only files downloaded through a browser are checked.
That's fine for a few friends, but to hand it out to more people, sign the exe and installer in
the release workflow:

If there's a new version, it builds the exe with PyInstaller ([packaging/nyanga.spec](packaging/nyanga.spec)),
wraps it in an Inno Setup installer ([packaging/installer.iss](packaging/installer.iss)), and publishes a
GitHub Release tagged `vX.Y.Z` with the installer and notes made from the commits. The same
notes go into [CHANGELOG.md](CHANGELOG.md), which the workflow commits back as a `docs:` commit.
The tag is the source of the version; `version.py` says `0.0.0-dev` in the repo and gets the
real number during the build.

Even when signed, SmartScreen may warn for a while until the signature builds a reputation.

## 🧶 Contributing

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
