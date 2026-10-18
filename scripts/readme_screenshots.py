#!/usr/bin/env python3
"""Renders assets/readme/screenshot-{light,dark}.png: the Download page with Onepunch-Man looked up.

    .venv/bin/python scripts/readme_screenshots.py

Runs the real app offscreen (needs the network for fanfox.net) against a throwaway data folder,
so your own settings.json and library stay untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://fanfox.net/manga/onepunch_man/"
SIZE = (1385, 980)


def render(mode: str, out: Path, data: Path) -> None:
    sys.path.insert(0, str(ROOT))
    (data / "settings.json").write_text(json.dumps({"download_dir": r"C:\Users\you\Downloads\Manga", "theme": mode}))

    import paths
    paths.DATA = paths.CONFIG = data

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QPushButton

    import gui
    import theme

    app = QApplication(["nyanga"])
    app.setFont(theme.load_font())
    window = gui.MainWindow()
    window.findChild(QPushButton, "version").hide()  # it would go out of date
    window.resize(*SIZE)
    window.show()
    page = window.download
    page._fetch(URL)
    start = time.time()

    def poll() -> None:
        if page.info is not None and page.groups and not page.estimating:
            QTimer.singleShot(1500, snap)  # let the cover and table settle
        elif time.time() - start > 90:
            print("timed out waiting for fanfox.net", file=sys.stderr)
            app.exit(1)
        else:
            QTimer.singleShot(300, poll)

    def snap() -> None:
        window.grab().toImage().convertToFormat(QImage.Format_RGB32).save(str(out))  # no alpha, like before
        print("saved", out.relative_to(ROOT))
        app.quit()

    QTimer.singleShot(300, poll)
    sys.exit(app.exec())


def main() -> None:
    if len(sys.argv) == 4:  # one mode, in its own process so the theme starts clean
        render(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
        return
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for mode in ("light", "dark"):
        with tempfile.TemporaryDirectory() as data:
            out = ROOT / "assets" / "readme" / f"screenshot-{mode}.png"
            subprocess.run([sys.executable, __file__, mode, str(out), data], env=env, check=True)


if __name__ == "__main__":
    main()
