#!/usr/bin/env python3
"""Draws the app icon into build/icon.ico for the exe and the installer."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import theme  # noqa: E402  (needs the path above)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841  (pixmaps need one)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    theme.app_pixmap(256).save(buffer, "PNG")
    image = Image.open(io.BytesIO(bytes(buffer.data())))
    out = ROOT / "build" / "icon.ico"
    out.parent.mkdir(exist_ok=True)
    image.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)


if __name__ == "__main__":
    main()
