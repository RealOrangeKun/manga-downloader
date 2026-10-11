# comix-manga-downloader

Interactive script that downloads a manga from comix.to and writes one file per volume
(CBZ, PDF, EPUB or plain image folders).

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

## Usage

```sh
.venv/bin/python comix_dl.py
```

The script asks for the title URL, the download folder, the output format, the language,
which volumes to fetch, and where to keep temporary page images. If a run is interrupted,
run it again with the same folders and it resumes from the chapters already downloaded.

## How it works

The site's API needs a request token and returns encrypted responses, both produced by its
own JavaScript. The script opens the title page in headless Chromium and calls the site's
own API client from inside the page, so nothing has to be reimplemented.

When a chapter number has several uploads, the one with a volume number is preferred, then
official releases, then the most voted. Chapters with no volume number go into a single
"No Volume" file.
