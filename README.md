# manga-downloader

Interactive script that downloads a manga and writes one file per volume
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

## What it asks

1. The manga URL (it lists the supported sites first).
2. The download folder (default `./downloads`).
3. The output format: CBZ, PDF, EPUB or images.
4. How many chapters per file, if the site has no volume numbers for the title.
5. Which files to download: all, the first N, or rows from the table like `1-5,8`.
6. The temp folder for page images, and whether to keep it afterwards.

If a run is interrupted, run it again with the same answers and it resumes from the
chapters already downloaded. Files that already exist are skipped, so delete a file to
rebuild it.

## Notes

- Files follow the site's volume numbers. Chapters without one are split into files of a
  fixed number of chapters.
- Webtoons (long vertical strips) are cut into screen-sized pages in EPUB. CBZ and PDF keep
  the original strips; use a reader with a continuous-scroll mode for those.
- Requests are spaced one second apart (`REQUEST_DELAY` in `manga_dl.py`) so the script
  goes no faster than a person browsing. A long series takes a while.
- To add a site, write a class like `FanFox` with `url_re`, `title()`, `chapters()`,
  `page_urls()` and `image()`, and add it to `SITES`.
