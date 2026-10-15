# manga-downloader

A small pink desktop app that downloads a manga and saves it as one file per volume
(CBZ, PDF, EPUB or plain image folders).

## Supported sites

- fanfox.net (`https://fanfox.net/manga/<title>/`)

## Quick start

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

**Settings page** (saved to `settings.json` next to `manga_dl.py`; it is git-ignored)

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

## Notes

- Webtoons (long vertical strips) are cut into screen-sized pages in EPUB. CBZ and PDF keep
  the original strips; use a reader with a continuous-scroll mode for those.
- Code layout: `core.py` (sites, rate limiting, download pipeline), `builders.py` (output
  formats), `gui.py` (the window). To add a site, write a class like `FanFox` in `core.py`
  with `url_re`, `info()`, `page_urls()` and `image()`, and add it to `SITES`.
- The interface uses the bundled [Fredoka](https://github.com/hafontia/Fredoka-One) font
  (`assets/fonts`, SIL Open Font License, see `assets/fonts/OFL.txt`). The icons and the
  little book mascot in `theme.py` and `assets/icons` were drawn for this project.
