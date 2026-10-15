"""Output formats. Kept free of GUI imports so builds can run in worker processes."""

from __future__ import annotations

import html
import shutil
import time
import uuid
import zipfile
from pathlib import Path

import img2pdf
from PIL import Image

FORMATS = {
    "cbz": "CBZ (comic readers)",
    "pdf": "PDF",
    "epub": "EPUB (e-readers)",
    "images": "Images only",
}


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


def build_file(fmt: str, images: list[Path], out: Path, title: str) -> Path:
    BUILDERS[fmt](images, out, title)
    return out
