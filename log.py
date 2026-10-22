"""Debug logging: off unless Nyanga starts with --debug (or NYANGA_DEBUG=1), then everything goes to a file.

Modules log through `logging.getLogger(__name__)` as usual; without --debug only warnings and errors
are kept, and only on the console when there is one.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
from pathlib import Path

import paths

FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(threadName)-12s %(name)s: %(message)s"


def wanted(argv: list[str]) -> bool:
    return "--debug" in argv or os.environ.get("NYANGA_DEBUG", "") not in ("", "0")


def file_path() -> Path:
    return paths.DATA / "logs" / "nyanga-debug.log"


def setup(debug: bool) -> Path | None:
    """Turn logging on; returns the log file when debugging."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.WARNING)
    if sys.stderr:  # None in the Windows exe, which has no console
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))
        root.addHandler(console)
    for noisy in ("urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.INFO)
    if not debug:
        return None
    path = file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)

    def crashed(kind, value, tb) -> None:
        logging.getLogger("crash").critical("Uncaught error", exc_info=(kind, value, tb))
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = crashed
    threading.excepthook = lambda a: logging.getLogger("crash").critical(
        "Uncaught error in thread %s", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    from version import __version__
    info = logging.getLogger("nyanga")
    info.info("---- Nyanga %s starting (debug log)", __version__)
    info.info("system: %s, Python %s, %s", platform.platform(), platform.python_version(),
              "built app" if getattr(sys, "frozen", False) else "from source")
    info.info("argv: %s", sys.argv)
    info.info("data: %s, config: %s, bundle: %s", paths.DATA, paths.CONFIG, paths.BUNDLE)
    return path


def qt_messages() -> None:
    """Send Qt's own warnings into the log too."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    qt = logging.getLogger("qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    qInstallMessageHandler(lambda kind, context, text: qt.log(levels.get(kind, logging.WARNING), "%s", text))
