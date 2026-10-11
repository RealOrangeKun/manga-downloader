#!/usr/bin/env python3
"""Download a manga and save it as one file per volume (CBZ / PDF / EPUB / images)."""

from __future__ import annotations

import html
import re
import shutil
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

import img2pdf
import questionary
import requests
from PIL import Image
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

NO_VOLUME = 0
# The sites ask that automated clients go no faster than a person browsing would.
REQUEST_DELAY = 0.2  # seconds between requests
FORMATS = {
    "CBZ  (comic archive, best for comic readers)": "cbz",
    "PDF": "pdf",
    "EPUB (fixed layout, for e-readers)": "epub",
    "Images only (one folder per file)": "images",
}

console = Console()


class SiteError(RuntimeError):
    pass


@dataclass
class Chapter:
    number: float
    volume: int  # NO_VOLUME when the site does not say
    url: str


@dataclass
class Group:
    """The chapters that end up in one output file."""
    label: str
    chapters: list[Chapter]


# --------------------------------------------------------------------------- sites


class FanFox:
    name = "fanfox.net"
    example = "https://fanfox.net/manga/<title>/"
    url_re = re.compile(r"(?:fanfox\.net|mangafox\.\w+)/manga/([a-z0-9_]+)", re.I)
    _title_re = re.compile(r'class="detail-info-right-title-font">([^<]+)<')
    _image_re = re.compile(r'data-original="([^"]+)"')

    def __init__(self, url: str):
        self.slug = self.url_re.search(url).group(1).lower()
        # Only this title's own links; the page also links to chapters of other manga.
        self._chapter_re = re.compile(
            rf'href="(/manga/{re.escape(self.slug)}/(?:v([^/"]+)/)?c([\d.]+)/1\.html)"', re.I)
        self.http = requests.Session()
        self.http.headers["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0 Mobile Safari/537.36")
        self.http.cookies.set("isAdult", "1", domain=".fanfox.net")
        self._page = self._get(f"https://fanfox.net/manga/{self.slug}/").text

    def _get(self, url: str, referer: str = "https://fanfox.net/", retries: int = 3) -> requests.Response:
        last = "unknown error"
        for attempt in range(retries):
            time.sleep(REQUEST_DELAY * (attempt + 1))
            try:
                resp = self.http.get(url, headers={"Referer": referer}, timeout=30)
                if resp.status_code == 200:
                    return resp
                last = f"HTTP {resp.status_code}"
                if resp.status_code in (403, 404):
                    break
            except requests.RequestException as e:
                last = type(e).__name__
        raise SiteError(f"Could not fetch {url}: {last}")

    def title(self) -> str:
        m = self._title_re.search(self._page)
        return html.unescape(m.group(1)).strip() if m else self.slug.replace("_", " ").title()

    def chapters(self) -> list[Chapter]:
        found = {}
        for path, vol, num in self._chapter_re.findall(self._page):
            found[path] = Chapter(float(num), int(vol) if vol.isdigit() else NO_VOLUME, path)
        return sorted(found.values(), key=lambda c: (c.number, c.url))

    def page_urls(self, chapter: Chapter) -> list[str]:
        # The mobile "roll" reader lists every page of a chapter in one document.
        roll = "https://m.fanfox.net" + chapter.url.replace("/manga/", "/roll_manga/", 1)
        urls = [html.unescape(u) for u in self._image_re.findall(self._get(roll).text)]
        if not urls:
            raise SiteError(f"No pages found for chapter {fmt_num(chapter.number)}")
        return ["https:" + u if u.startswith("//") else u for u in urls]

    def image(self, url: str) -> bytes:
        resp = self._get(url, referer="https://m.fanfox.net/")
        if not resp.headers.get("content-type", "").startswith("image/"):
            raise SiteError(f"Not an image: {url}")
        return resp.content


SITES = [FanFox]


def site_for(url: str):
    return next((s for s in SITES if s.url_re.search(url)), None)


# --------------------------------------------------------------------------- planning


def fmt_num(n: float) -> str:
    return f"{n:g}"


def chapter_span(chapters: list[Chapter]) -> str:
    first, last = chapters[0].number, chapters[-1].number
    return fmt_num(first) if first == last else f"{fmt_num(first)}-{fmt_num(last)}"


def make_groups(chapters: list[Chapter], per_file: int) -> list[Group]:
    """One group per volume; chapters without a volume are split into files of per_file chapters."""
    by_volume: dict[int, list[Chapter]] = {}
    for ch in chapters:
        by_volume.setdefault(ch.volume, []).append(ch)
    loose = by_volume.pop(NO_VOLUME, [])
    groups = [Group(f"Vol. {vol:02d}", chs) for vol, chs in sorted(by_volume.items())]
    for i in range(0, len(loose), per_file):
        part = loose[i:i + per_file]
        groups.append(Group(f"Ch. {chapter_span(part)}", part))
    return groups


def parse_selection(text: str, count: int) -> list[int]:
    """Parse '1-3,7' into zero-based row indexes, ignoring rows that do not exist."""
    wanted: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        wanted.update(range(int(lo), int(hi or lo) + 1))
    return [i - 1 for i in sorted(wanted) if 1 <= i <= count]


def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "manga"


# --------------------------------------------------------------------------- download

EXT_BY_MAGIC = [(b"\xff\xd8", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif"), (b"RIFF", ".webp")]


def image_ext(data: bytes) -> str:
    for magic, ext in EXT_BY_MAGIC:
        if data.startswith(magic):
            return ext
    return ".avif" if data[4:12] in (b"ftypavif", b"ftypavis") else ".jpg"


def download_group(site, group: Group, group_dir: Path, progress: Progress) -> list[Path]:
    """Download every page of a group into group_dir; already-downloaded chapters are skipped."""
    for ch in group.chapters:
        ch_dir = group_dir / f"ch_{ch.number:08.2f}"
        if (ch_dir / ".done").exists():
            continue
        ch_dir.mkdir(parents=True, exist_ok=True)
        urls = site.page_urls(ch)
        task = progress.add_task(f"  Chapter {fmt_num(ch.number)}", total=len(urls))
        for i, url in enumerate(urls, 1):
            if not list(ch_dir.glob(f"{i:04d}.*")):
                data = site.image(url)
                (ch_dir / f"{i:04d}{image_ext(data)}").write_bytes(data)
            progress.advance(task)
        (ch_dir / ".done").touch()
        progress.remove_task(task)
    return sorted(p for p in group_dir.glob("ch_*/*") if p.name != ".done" and ".conv." not in p.name)


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


def is_strip(images: list[Path]) -> bool:
    """True for webtoons, where each image is one long vertical strip rather than a page."""
    ratios = []
    for img in images:
        with Image.open(img) as im:
            ratios.append(im.height / im.width)
    return sorted(ratios)[len(ratios) // 2] > 3


def cut_points(im: Image.Image, page_height: int) -> list[int]:
    """Where to cut a strip into pages, preferring blank rows between panels."""
    # Squash to 8 columns; a row whose columns all match is a gap between panels.
    rows = im.convert("L").resize((8, im.height), Image.BOX)
    data = rows.tobytes()
    blank = [max(data[y * 8:y * 8 + 8]) - min(data[y * 8:y * 8 + 8]) < 8 for y in range(im.height)]
    cuts, pos = [], 0
    while im.height - pos > page_height * 1.3:
        target = pos + page_height
        window = range(pos + int(page_height * 0.6), pos + int(page_height * 1.25))
        candidates = [y for y in window if blank[y]]
        pos = min(candidates, key=lambda y: abs(y - target)) if candidates else target
        cuts.append(pos)
    return cuts


def slice_strip(path: Path) -> list[Path]:
    """Cut a long strip into page-sized images next to it; normal pages are returned as they are."""
    with Image.open(path) as im:
        if im.height <= im.width * 2:
            return [path]
        edges = [0, *cut_points(im, int(im.width * 1.4)), im.height]
        parts = []
        for n, (top, bottom) in enumerate(zip(edges, edges[1:]), 1):
            part = path.with_suffix(f".conv.s{n:02d}.jpg")
            if not part.exists():
                im.crop((0, top, im.width, bottom)).convert("RGB").save(part, "JPEG", quality=95)
            parts.append(part)
        return parts


def build_epub(images: list[Path], out: Path, title: str) -> None:
    strip = is_strip(images)
    images = [as_jpeg_or_png(p) for p in images]
    if strip:
        # A whole strip squeezed onto one fixed page is unreadable, so cut it into pages.
        images = [part for p in images for part in slice_strip(p)]
    spread, direction = ("none", "ltr") if strip else ("landscape", "rtl")
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
            f'<meta property="rendition:spread">{spread}</meta></metadata><manifest>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            f'{"".join(manifest)}</manifest><spine page-progression-direction="{direction}">{"".join(spine)}</spine></package>',
        )


BUILDERS = {"cbz": build_cbz, "pdf": build_pdf, "epub": build_epub, "images": build_images}


# --------------------------------------------------------------------------- prompts


def ask(question):
    answer = question.ask()
    if answer is None:  # Ctrl+C
        console.print("[yellow]Cancelled.[/]")
        sys.exit(1)
    return answer


def ask_int(message: str, default: int, low: int, high: int) -> int:
    return int(ask(questionary.text(
        message, default=str(default),
        validate=lambda t: (t.strip().isdigit() and low <= int(t) <= high) or f"Enter a number from {low} to {high}")))


def print_overview(title: str, groups: list[Group]) -> None:
    table = Table(title=title, title_style="bold", show_footer=True)
    table.add_column("#", justify="right", footer="")
    table.add_column("File", footer=f"{len(groups)} files")
    table.add_column("Chapters", footer="")
    table.add_column("Count", justify="right", footer=str(sum(len(g.chapters) for g in groups)))
    for i, g in enumerate(groups, 1):
        table.add_row(str(i), g.label, chapter_span(g.chapters), str(len(g.chapters)))
    console.print(table)


def ask_groups(groups: list[Group]) -> list[Group]:
    """Ask which files to download until the user confirms a non-empty choice."""
    total = sum(len(g.chapters) for g in groups)
    everything = f"All of it ({len(groups)} files, {total} chapters)"
    first_n, specific = "The first N files", "Specific rows from the table (e.g. 1-5,8)"
    while True:
        mode = ask(questionary.select("What do you want to download?", choices=[everything, first_n, specific]))
        if mode == everything:
            picked = groups
        elif mode == first_n:
            picked = groups[:ask_int(f"How many (1-{len(groups)}):", 1, 1, len(groups))]
        else:
            text = ask(questionary.text(
                "Rows:", validate=lambda t: bool(re.fullmatch(r"\s*\d+(-\d+)?(\s*,\s*\d+(-\d+)?)*\s*", t))
                or "Use numbers and ranges like 1-5,8"))
            picked = [groups[i] for i in parse_selection(text, len(groups))]
        if not picked:
            console.print("[red]None of those rows exist.[/]")
            continue
        console.print(f"Selected [bold]{len(picked)}[/] files, "
                      f"[bold]{sum(len(g.chapters) for g in picked)}[/] chapters: "
                      + ", ".join(g.label for g in picked))
        if ask(questionary.confirm("Download these?", default=True)):
            return picked


def main() -> None:
    console.print("[bold cyan]Manga downloader[/]")
    console.print("Supported sites:")
    for s in SITES:
        console.print(f"  - {s.name}  [dim]{s.example}[/]")
    console.print()

    url = ask(questionary.text(
        "Paste the manga URL:",
        validate=lambda t: site_for(t) is not None or "That is not a title URL from a supported site"))
    out_dir = Path(ask(questionary.path("Download folder:", default="./downloads", only_directories=True))).expanduser()
    fmt = FORMATS[ask(questionary.select("Output format:", choices=list(FORMATS)))]

    console.print("\nReading the chapter list...")
    try:
        site = site_for(url)(url)
        title, chapters = site.title(), site.chapters()
    except SiteError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)
    if not chapters:
        console.print("[red]No chapters found on that page.[/]")
        sys.exit(1)

    loose = sum(1 for c in chapters if c.volume == NO_VOLUME)
    per_file = 10
    if loose:
        console.print(f"[yellow]{loose} of {len(chapters)} chapters have no volume number on this site, "
                      "so they are split into files by chapter count instead.[/]")
        per_file = ask_int("Chapters per file:", 10, 1, loose)
    groups = make_groups(chapters, per_file)

    console.print()
    print_overview(title, groups)
    picked = ask_groups(groups)

    tmp_dir = Path(ask(questionary.path(
        "Temp folder for pages while downloading:", default=str(out_dir / ".manga-tmp"),
        only_directories=True))).expanduser()
    keep_tmp = ask(questionary.confirm("Keep the temp files afterwards?", default=False))

    book_dir = out_dir / safe_name(title)
    book_dir.mkdir(parents=True, exist_ok=True)
    work_dir = tmp_dir / safe_name(title)
    failed = []

    columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn())
    with Progress(*columns, console=console) as progress:
        overall = progress.add_task("[bold]Files", total=len(picked))
        for group in picked:
            name = safe_name(f"{title} - {group.label}")
            target = book_dir / (name if fmt == "images" else f"{name}.{fmt}")
            progress.console.print(f"[cyan]{group.label}[/]")
            try:
                if target.exists():
                    progress.console.print("  already exists, skipping")
                else:
                    group_dir = work_dir / safe_name(group.label)
                    images = download_group(site, group, group_dir, progress)
                    BUILDERS[fmt](images, target, f"{title} - {group.label}")
                    progress.console.print(f"  [green]saved[/] {target}")
                    if not keep_tmp:
                        shutil.rmtree(group_dir, ignore_errors=True)
            except (SiteError, OSError, ValueError) as e:
                failed.append(group.label)
                progress.console.print(f"  [red]failed:[/] {e}")
            progress.advance(overall)

    if not keep_tmp and not failed:
        shutil.rmtree(work_dir, ignore_errors=True)
        if tmp_dir.exists() and not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()
    if failed:
        console.print(f"\n[yellow]Failed: {', '.join(failed)}. Downloaded pages were kept in {work_dir}; "
                      "run again with the same folders and chapters-per-file to resume.[/]")
        sys.exit(1)
    console.print(f"\n[bold green]Done.[/] Files are in {book_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/]")
        sys.exit(1)
