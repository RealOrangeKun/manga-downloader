#!/usr/bin/env python3
"""Download a manga from comix.to, one file per volume (CBZ / PDF / EPUB / images)."""

from __future__ import annotations

import html
import re
import shutil
import sys
import time
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path

import img2pdf
import questionary
from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn

BASE = "https://comix.to"
TITLE_RE = re.compile(r"comix\.to/title/([a-z0-9]+)(?:-[^/?#]*)?", re.I)
NO_VOLUME = 0
REQUEST_DELAY = 0.4  # seconds between requests, to stay gentle on the site
FORMATS = {
    "CBZ  (comic archive, best for comic readers)": "cbz",
    "PDF": "pdf",
    "EPUB (fixed layout, for e-readers)": "epub",
    "Images only (one folder per volume)": "images",
}

console = Console()

# The API needs a request token and returns encrypted bodies, both handled by the
# site's own JS. Rather than reimplement that, find the site's HTTP client among the
# loaded modules (an object of five functions: get/post/put/patch/delete) and reuse it.
FIND_CLIENT_JS = r"""
async () => {
  const urls = [...new Set(performance.getEntriesByType('resource').map(e => e.name)
    .filter(n => /\/assets\/.*\.js(\?|$)/.test(n)))];
  for (const u of urls) {
    let m; try { m = await import(u); } catch (e) { continue; }
    for (const k of Object.keys(m)) {
      const v = m[k];
      if (!v || typeof v !== 'object') continue;
      const fns = Object.values(v);
      if (fns.length !== 5 || !fns.every(f => typeof f === 'function')) continue;
      const get = fns.find(f => /\.get\(/.test(f.toString()));
      if (get) { window.__comixGet = get; return true; }
    }
  }
  return false;
}
"""
API_GET_JS = """([path, params]) => window.__comixGet(path, {params}).then(
  r => ({ok: r}), e => ({err: String(e), status: e?.response?.status ?? null}))"""
LOAD_IMG_JS = "u => { const i = new Image(); i.src = u; }"


class SiteError(RuntimeError):
    pass


class Comix:
    """A headless browser session on comix.to."""

    def __init__(self, title_url: str):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self.page = self._browser.new_page()
        resp = self.page.goto(title_url, wait_until="networkidle", timeout=60_000)
        if resp is None or resp.status != 200:
            status = resp.status if resp else "no response"
            hint = " (Cloudflare is blocking this connection; try again later)" if status == 403 else ""
            raise SiteError(f"Could not open {title_url}: HTTP {status}{hint}")
        if not self.page.evaluate(FIND_CLIENT_JS):
            raise SiteError("Could not find the site's API client; the site has probably changed.")

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()

    def api(self, path: str, params: dict | None = None) -> dict:
        time.sleep(REQUEST_DELAY)
        res = self.page.evaluate(API_GET_JS, [path, params or {}])
        if "err" in res:
            raise SiteError(f"API request {path} failed: {res['err']} (HTTP {res['status']})")
        return res["ok"]

    def manga(self, hid: str) -> dict:
        return self.api(f"/manga/{hid}")

    def chapters(self, hid: str) -> list[dict]:
        items, page = [], 1
        while True:
            data = self.api(f"/manga/{hid}/chapters", {"page": page, "limit": 100, "order[number]": "asc"})
            items += data["items"]
            if not data["meta"]["hasNext"]:
                return items
            page += 1

    def page_urls(self, chapter_id: int) -> list[str]:
        pages = self.api(f"/chapters/{chapter_id}")["pages"]
        if isinstance(pages, list):
            pages = {"items": pages}
        base = pages.get("baseUrl") or ""
        return [base + p["url"] for p in pages.get("items", [])]

    def image(self, url: str, retries: int = 3) -> bytes:
        """Fetch an image the way the reader does: through an <img> in the page."""
        last = "unknown error"
        for attempt in range(retries):
            time.sleep(REQUEST_DELAY * (attempt + 1))
            try:
                with self.page.expect_response(lambda r: r.url == url, timeout=30_000) as info:
                    self.page.evaluate(LOAD_IMG_JS, url)
                resp = info.value
                if resp.status == 200 and resp.headers.get("content-type", "").startswith("image/"):
                    return resp.body()
                last = f"HTTP {resp.status}"
            except PlaywrightError as e:
                last = str(e).splitlines()[0]
        raise SiteError(f"Could not download image {url}: {last}")


# --------------------------------------------------------------------------- planning


def pick_chapters(chapters: list[dict], language: str) -> dict[int, list[dict]]:
    """Keep one upload per chapter number and group them by volume."""
    by_number: dict[float, list[dict]] = defaultdict(list)
    for ch in chapters:
        if ch["language"] == language:
            by_number[ch["number"]].append(ch)
    volumes: dict[int, list[dict]] = defaultdict(list)
    for number in sorted(by_number):
        # Prefer uploads that say which volume they belong to, then official, then most voted.
        best = max(by_number[number], key=lambda c: (bool(c["volume"]), c["isOfficial"], c["votes"], c["id"]))
        volumes[int(best["volume"] or NO_VOLUME)].append(best)
    return dict(sorted(volumes.items(), key=lambda kv: (kv[0] == NO_VOLUME, kv[0])))


def parse_selection(text: str, available: list[int]) -> list[int]:
    """Parse '1-3,7' into volume numbers; 'all' or empty means everything."""
    text = text.strip().lower()
    if text in ("", "all"):
        return available
    wanted: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        wanted.update(range(int(lo), int(hi or lo) + 1))
    return [v for v in available if v in wanted]


def fmt_num(n: float) -> str:
    return f"{n:g}"


def volume_label(vol: int, chapters: list[dict]) -> str:
    if vol != NO_VOLUME:
        return f"Vol. {vol:02d}"
    first, last = chapters[0]["number"], chapters[-1]["number"]
    span = fmt_num(first) if first == last else f"{fmt_num(first)}-{fmt_num(last)}"
    return f"No Volume (Ch. {span})"


def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "manga"


# --------------------------------------------------------------------------- download

EXT_BY_MAGIC = [(b"\xff\xd8", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif"), (b"RIFF", ".webp")]


def image_ext(data: bytes) -> str:
    for magic, ext in EXT_BY_MAGIC:
        if data.startswith(magic):
            return ext
    return ".avif" if data[4:12] in (b"ftypavif", b"ftypavis") else ".jpg"


def download_volume(site: Comix, chapters: list[dict], vol_dir: Path, progress: Progress) -> list[Path]:
    """Download every page of a volume into vol_dir; already-downloaded chapters are skipped."""
    for ch in chapters:
        ch_dir = vol_dir / f"ch_{ch['number']:08.2f}"
        if (ch_dir / ".done").exists():
            continue
        ch_dir.mkdir(parents=True, exist_ok=True)
        urls = site.page_urls(ch["id"])
        task = progress.add_task(f"  Chapter {fmt_num(ch['number'])}", total=len(urls))
        for i, url in enumerate(urls, 1):
            if not list(ch_dir.glob(f"{i:04d}.*")):
                data = site.image(url)
                (ch_dir / f"{i:04d}{image_ext(data)}").write_bytes(data)
            progress.advance(task)
        (ch_dir / ".done").touch()
        progress.remove_task(task)
    return sorted(p for p in vol_dir.glob("ch_*/*") if p.name != ".done")


# --------------------------------------------------------------------------- output formats


def as_jpeg_or_png(path: Path) -> Path:
    """PDF and EPUB only take JPEG/PNG reliably; convert anything else to JPEG next to it."""
    if path.suffix in (".jpg", ".png"):
        return path
    out = path.with_suffix(".conv.jpg")
    if not out.exists():
        Image.open(path).convert("RGB").save(out, "JPEG", quality=92)
    return out


def build_cbz(images: list[Path], out: Path, title: str) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for i, img in enumerate(images, 1):
            z.write(img, f"{i:05d}{img.suffix}")


def build_pdf(images: list[Path], out: Path, title: str) -> None:
    out.write_bytes(img2pdf.convert([str(as_jpeg_or_png(p)) for p in images], title=title))


def build_images(images: list[Path], out: Path, title: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(images, 1):
        shutil.copyfile(img, out / f"{i:05d}{img.suffix}")


def build_epub(images: list[Path], out: Path, title: str) -> None:
    images = [as_jpeg_or_png(p) for p in images]
    esc = html.escape(title)
    manifest, spine = [], []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        for i, img in enumerate(images, 1):
            with Image.open(img) as im:
                w, h = im.size
            name = f"{i:05d}{img.suffix}"
            mime = "image/png" if img.suffix == ".png" else "image/jpeg"
            z.write(img, f"OEBPS/images/{name}", zipfile.ZIP_STORED)
            z.writestr(
                f"OEBPS/p{i:05d}.xhtml",
                '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f'<title>{esc}</title><meta name="viewport" content="width={w}, height={h}"/>'
                "<style>html,body{margin:0;padding:0}img{display:block;width:100%;height:100%}</style></head>"
                f'<body><img src="images/{name}" alt="Page {i}"/></body></html>',
            )
            props = ' properties="cover-image"' if i == 1 else ""
            manifest.append(f'<item id="i{i}" href="images/{name}" media-type="{mime}"{props}/>')
            manifest.append(f'<item id="p{i}" href="p{i:05d}.xhtml" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="p{i}"/>')
        z.writestr(
            "OEBPS/nav.xhtml",
            '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>{esc}</title></head><body>'
            f'<nav epub:type="toc"><ol><li><a href="p00001.xhtml">{esc}</a></li></ol></nav></body></html>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="uid" prefix="rendition: http://www.idpf.org/vocab/rendition/#">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:identifier id="uid">urn:uuid:{uuid.uuid4()}</dc:identifier><dc:title>{esc}</dc:title>'
            "<dc:language>en</dc:language>"
            f'<meta property="dcterms:modified">{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta>'
            '<meta property="rendition:layout">pre-paginated</meta>'
            '<meta property="rendition:spread">landscape</meta></metadata><manifest>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            f'{"".join(manifest)}</manifest><spine page-progression-direction="rtl">{"".join(spine)}</spine></package>',
        )


BUILDERS = {"cbz": build_cbz, "pdf": build_pdf, "epub": build_epub, "images": build_images}


# --------------------------------------------------------------------------- prompts


def ask(question):
    answer = question.ask()
    if answer is None:  # Ctrl+C
        console.print("[yellow]Cancelled.[/]")
        sys.exit(1)
    return answer


def main() -> None:
    console.print("[bold cyan]comix.to manga downloader[/]\n")

    url = ask(questionary.text(
        "Manga URL:", validate=lambda t: bool(TITLE_RE.search(t)) or "Expected a https://comix.to/title/... link"))
    hid = TITLE_RE.search(url).group(1)
    out_dir = Path(ask(questionary.path("Download folder:", default="./downloads", only_directories=True))).expanduser()
    fmt = FORMATS[ask(questionary.select("Output format:", choices=list(FORMATS)))]
    language = ask(questionary.text("Language code:", default="en")).strip().lower()

    console.print("\nOpening the site and reading the chapter list...")
    try:
        site = Comix(url if url.startswith("http") else "https://" + url)
    except SiteError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    try:
        title = site.manga(hid).get("title") or hid
        volumes = pick_chapters(site.chapters(hid), language)
        if not volumes:
            console.print(f"[red]No chapters found for language '{language}'.[/]")
            sys.exit(1)

        console.print(f"\n[bold]{title}[/]")
        for vol, chs in volumes.items():
            console.print(f"  {volume_label(vol, chs):<28} {len(chs):>3} chapters")
        if NO_VOLUME in volumes:
            console.print("[dim]  Chapters the site has not assigned to a volume go in one 'No Volume' file "
                          "(select it with 0).[/]")

        selected = ask(questionary.text(
            "Volumes to download (e.g. 1-5,8 or all):", default="all",
            validate=lambda t: bool(re.fullmatch(r"\s*(all|\d+(-\d+)?(\s*,\s*\d+(-\d+)?)*)?\s*", t, re.I))
            or "Use numbers and ranges like 1-5,8"))
        selected = parse_selection(selected, list(volumes))
        if not selected:
            console.print("[red]None of those volumes exist.[/]")
            sys.exit(1)

        default_tmp = out_dir / ".comix-tmp"
        tmp_dir = Path(ask(questionary.path(
            "Temp folder for pages while downloading:", default=str(default_tmp), only_directories=True))).expanduser()
        keep_tmp = ask(questionary.confirm("Keep the temp files afterwards?", default=False))

        book_dir = out_dir / safe_name(title)
        book_dir.mkdir(parents=True, exist_ok=True)
        work_dir = tmp_dir / safe_name(f"{title} [{hid}]")
        failed = []

        columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn())
        with Progress(*columns, console=console) as progress:
            overall = progress.add_task("[bold]Volumes", total=len(selected))
            for vol in selected:
                label = volume_label(vol, volumes[vol])
                name = safe_name(f"{title} - {label}")
                target = book_dir / (name if fmt == "images" else f"{name}.{fmt}")
                progress.console.print(f"[cyan]{label}[/]")
                try:
                    if target.exists():
                        progress.console.print("  already exists, skipping")
                    else:
                        vol_dir = work_dir / f"vol_{vol:03d}"
                        images = download_volume(site, volumes[vol], vol_dir, progress)
                        BUILDERS[fmt](images, target, f"{title} - {label}")
                        progress.console.print(f"  [green]saved[/] {target}")
                        if not keep_tmp:
                            shutil.rmtree(vol_dir, ignore_errors=True)
                except (SiteError, OSError, ValueError) as e:
                    failed.append(label)
                    progress.console.print(f"  [red]failed:[/] {e}")
                progress.advance(overall)

        if not keep_tmp and not failed:
            shutil.rmtree(work_dir, ignore_errors=True)
            if tmp_dir.exists() and not any(tmp_dir.iterdir()):
                tmp_dir.rmdir()
        if failed:
            console.print(f"\n[yellow]Failed: {', '.join(failed)}. Downloaded pages were kept in {work_dir}; "
                          "run again with the same folders to resume.[/]")
            sys.exit(1)
        console.print(f"\n[bold green]Done.[/] Files are in {book_dir}")
    finally:
        site.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/]")
        sys.exit(1)
