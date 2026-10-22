"""Pages out of a downloaded file for the in-app reader: CBZ and other zips, EPUB, PDF or an image folder."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument

IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PDF_LONG_SIDE = 2400  # pixels a PDF page is drawn at on its long side


def natural(name: str) -> list:
    """Sort key that puts page 2 before page 10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


class Book:
    """One file's pages, loaded one at a time."""

    def __init__(self, path: Path):
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        self.pdf: QPdfDocument | None = None
        self.names: list = []
        if path.is_dir():
            self.names = sorted((p for p in path.iterdir() if p.suffix.lower() in IMAGES), key=lambda p: natural(p.name))
        elif path.suffix.lower() == ".pdf":
            self.pdf = QPdfDocument()
            if self.pdf.load(str(path)) != QPdfDocument.Error.None_:
                raise OSError(f"Couldn't open {path.name}")
        else:
            self.zip = zipfile.ZipFile(path)  # CBZ, EPUB: both are zips of numbered pictures
            self.names = sorted((n for n in self.zip.namelist()
                                 if Path(n).suffix.lower() in IMAGES and not n.startswith("__MACOSX")), key=natural)

    def __len__(self) -> int:
        return self.pdf.pageCount() if self.pdf else len(self.names)

    def image(self, i: int) -> QImage:
        if self.pdf:
            size = self.pdf.pagePointSize(i)
            scale = PDF_LONG_SIDE / max(size.width(), size.height(), 1)
            return self.pdf.render(i, QSize(round(size.width() * scale), round(size.height() * scale)))
        data = self.zip.read(self.names[i]) if self.zip else self.names[i].read_bytes()
        return QImage.fromData(data)

    def close(self) -> None:
        if self.zip:
            self.zip.close()
        if self.pdf:
            self.pdf.close()
