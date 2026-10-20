"""The pink Qt window: Download, Library and Settings pages, and the update check."""

from __future__ import annotations

import getpass
import html
import json
import math
import os
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields, replace
from datetime import date, datetime
from pathlib import Path

import requests
from PySide6.QtCore import QBuffer, QCoreApplication, QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QApplication, QStyledItemDelegate, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QGridLayout, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import appmenu
import core
import paths
import theme
import updater
from history import History, ago, chapter_key
from loader import CatLoader, MiniCat, paint_mini_cat, paint_update_cat
from builders import FORMATS
from version import __version__

# The theme in use (theme.LIGHT or theme.DARK); helpers that paint read it.
CURRENT = {"mode": theme.LIGHT}
# Buttons with icons, recolored whenever the theme changes: (button, icon name, palette key or "white").
_ICON_BUTTONS: list[tuple[QPushButton, str, str]] = []


def set_icon(button: QPushButton, name: str, color_key: str = "accent_soft", size: int = 18) -> QPushButton:
    _ICON_BUTTONS.append((button, name, color_key))
    button.setIconSize(QSize(size, size))
    _paint_icon(button, name, color_key)
    return button


def swap_icon(button: QPushButton, name: str) -> None:
    """Give a button made with set_icon a different icon, keeping its color."""
    for i, (b, _, key) in enumerate(_ICON_BUTTONS):
        if b is button:
            _ICON_BUTTONS[i] = (b, name, key)
            _paint_icon(b, name, key)


def _paint_icon(button: QPushButton, name: str, color_key: str) -> None:
    color = "#ffffff" if color_key == "white" else theme.color(CURRENT["mode"], color_key)
    button.setIcon(theme.icon(name, color))


def greeted() -> bool:
    """The sidebar says hi only to the friend Nyanga was made for (their Windows user name)."""
    try:
        return getpass.getuser().casefold() == "thevi"
    except Exception:  # no user name to be found
        return False


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property used by it changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# --------------------------------------------------------------------------- settings


@dataclass
class Settings:
    download_dir: str = str(Path.home() / "Downloads" / "Manga")
    temp_dir: str = ""  # empty: a .manga-tmp folder inside the download folder
    workers: int = 1
    download_mode: str = core.THREADS
    request_delay: float = 0.2
    default_format: str = "cbz"
    chapters_per_file: int = 10
    keep_temp: bool = False
    theme: str = theme.SYSTEM
    default_source: str = core.SITES[0].name
    files_per_page: int = 20
    results_grid: bool = False  # search results as a grid of covers instead of a list
    results_size: int = 1  # index into ResultItem.SIZES
    seen_version: str = ""  # the version last opened, to show What's new once after an update

    @staticmethod
    def path() -> Path:
        return paths.CONFIG / "settings.json"  # next to the script (git-ignored), %APPDATA% or ~/.config when built

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(cls.path().read_text())
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        self.path().parent.mkdir(parents=True, exist_ok=True)
        self.path().write_text(json.dumps(asdict(self), indent=2))


# --------------------------------------------------------------------------- helpers


class Bridge(QObject):
    """Carries results from worker threads back to the GUI thread."""
    searched = Signal(int, object, str, int, list, int)  # search id, site class, query, page, SearchResults, pages
    search_failed = Signal(int, str)
    cover_ready = Signal(int, int, object)  # results-page token, result index, image bytes (or None)
    about_ready = Signal(int, int, list, str, float)  # results-page token, result index, genres, description, rating
    about_missed = Signal(int, int)  # results-page token, result index whose page couldn't be read
    fetched = Signal(object, object)  # site, MangaInfo
    fetch_failed = Signal(str)
    status = Signal(int, str, float, str)  # table row, state, fraction, message
    finished = Signal(list, bool)  # failed rows, cancelled
    estimated = Signal(object, object)  # MangaInfo, average bytes per chapter (or None)


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="card")
    shadow = QGraphicsDropShadowEffect(blurRadius=28, xOffset=0, yOffset=6)
    shadow.setColor(theme.color(CURRENT["mode"], "shadow"))
    frame.setGraphicsEffect(shadow)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return frame, layout


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def rounded_pixmap(data: bytes | None, w: int, h: int, radius: int = 16) -> QPixmap:
    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    src = QPixmap()
    if data and src.loadFromData(data):
        src = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap(0, 0, src.copy((src.width() - w) // 2, (src.height() - h) // 2, w, h))
    else:  # placeholder: pink card with a heart
        p.fillRect(0, 0, w, h, theme.color(CURRENT["mode"], "chip"))
        p.setPen(theme.color(CURRENT["mode"], "accent"))
        p.setFont(QFont(p.font().family(), min(40, max(14, w * 3 // 5))))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "♡")
    p.end()
    return out


def spin(cls=QSpinBox, **kw):
    box = cls(**kw)
    box.lineEdit().setTextMargins(6, 0, 0, 0)  # match the padding of the line edits
    box.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)  # too big becomes the biggest, not the old value
    range_tip(box)
    return box


def range_tip(box) -> None:
    """Tell what a number box accepts; call again after its range changes."""
    fmt = (lambda v: f"{v:g}") if isinstance(box, QDoubleSpinBox) else str
    box.setToolTip(f"{box.prefix()}{fmt(box.minimum())} to {fmt(box.maximum())}{box.suffix()}")


WINDOWS_BAD = set('<>"|?*')


def folder_problem(text: str) -> str | None:
    """Why a folder path can't be used, or None. Empty is fine: it means the default."""
    text = text.strip()
    if not text:
        return None
    path = Path(text).expanduser()
    example = r"C:\Users\you\Manga" if sys.platform == "win32" else str(Path.home() / "Manga")
    if not path.is_absolute():
        return f"Use the full folder path, like {example}"
    if sys.platform == "win32":
        rest = str(path)[len(path.drive):]
        if WINDOWS_BAD & set(rest) or ":" in rest:
            return 'Folder names can\'t have any of these: < > : " | ? *'
        if len(str(path)) > 200:
            return "That path is too long for Windows; pick a shorter one"
    if path.exists() and not path.is_dir():
        return "That's a file, not a folder"
    return None


def watch_folder(edit: QLineEdit) -> None:
    """Outline a folder field in red while its path can't be used, with the reason as its tooltip."""
    def check() -> None:
        problem = folder_problem(edit.text())
        edit.setProperty("error", bool(problem))
        edit.setToolTip(problem or "")
        repolish(edit)

    edit.textChanged.connect(check)
    check()


def combo_box() -> QComboBox:
    """A combo box whose popup is a rounded list (styled in theme.py) instead of the platform menu."""
    box = QComboBox()
    box.setView(QListView())  # lets the stylesheet style each item
    popup = box.view().window()
    popup.setWindowFlags(popup.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    popup.setAttribute(Qt.WA_TranslucentBackground)  # so the rounded corners show
    return box


def form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return form


def with_hint(field, text: str) -> QWidget:
    """A form field with a small explanation right under it."""
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(5)
    if isinstance(field, QWidget):
        col.addWidget(field)
    else:
        col.addLayout(field)
    col.addWidget(label(text, "hint", wrap=True))
    return box


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"


def fmt_duration(seconds: float, about: bool = True) -> str:
    seconds = max(0, round(seconds))
    if about and seconds < 45:
        return "less than a minute"
    if seconds < 60:
        return f"{seconds} s"
    minutes = round(seconds / 60) if about else seconds // 60
    if minutes < 60:
        text = f"{minutes} min" if about else f"{minutes} min {seconds % 60} s"
    else:
        text = f"{minutes // 60} h {minutes % 60} min"
    return f"about {text}" if about else text


def folder_row(edit: QLineEdit, title: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(edit, 1)
    browse = set_icon(QPushButton(" Browse"), "folder")

    def pick() -> None:
        chosen = QFileDialog.getExistingDirectory(edit.window(), title, edit.text() or str(Path.home()))
        if chosen:
            edit.setText(chosen)

    browse.clicked.connect(pick)
    row.addWidget(browse)
    return row


# --------------------------------------------------------------------------- download page


HEADERS = ["", "File", "Chapters", "Count", "Size", "Progress"]
LOADING = Qt.UserRole + 1  # item flag: draw the little cat instead of text


class CatDelegate(QStyledItemDelegate):
    """Draws a tiny animated cat in cells that are still loading; normal text otherwise."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.data(LOADING):
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            r = QRectF(option.rect)
            area = QRectF(r.right() - 54, r.center().y() - 13, 46, 26)  # right-aligned like the sizes
            paint_mini_cat(painter, area, time.monotonic(), CURRENT["mode"])
            painter.restore()


class ResultItem(QFrame):
    """One search result: cover, title and a line about it. Click to open it."""
    clicked = Signal()

    SIZES = ["Small", "Medium", "Big", "Large", "Very large"]
    LIST_WIDTHS = [40, 54, 72, 96, 124]  # cover width per size; covers are 54:76
    GRID_WIDTHS = [84, 108, 136, 168, 208]

    def __init__(self, result: core.SearchResult, grid: bool = False, size: int = 1):
        super().__init__(objectName="result")
        self.result = result
        self.data: bytes | None = None
        self.grid = grid
        self.cover_w = (self.GRID_WIDTHS if grid else self.LIST_WIDTHS)[size]
        self.cover_h = round(self.cover_w * 76 / 54)
        self.setCursor(Qt.PointingHandCursor)
        self.cover = QLabel()
        self.cover.setFixedSize(self.cover_w, self.cover_h)
        self.set_cover(None)
        meta = "  ·  ".join(x for x in (result.status, result.latest) if x)
        self.tags = TagRow()  # filled in once the title's page has been read
        self.stars = label("", "stars")
        self.stars.hide()
        self.loading = QWidget()  # a little cat while the title's page is being read
        lrow = QHBoxLayout(self.loading)
        lrow.setContentsMargins(0, 0, 0, 0)
        lrow.setSpacing(4)
        self.loading_cat = MiniCat(lambda: CURRENT["mode"], (30, 18))
        lrow.addWidget(self.loading_cat)
        lrow.addWidget(label("reading its page ✧", "meta"))
        lrow.addStretch(1)
        self.loading.hide()
        if grid:  # a tile: cover on top, title underneath
            col = QVBoxLayout(self)
            col.setContentsMargins(10, 10, 10, 12)
            col.setSpacing(6)
            col.addWidget(self.cover, 0, Qt.AlignHCenter)
            title = label(result.title, "resultTitle", wrap=True)
            title.setAlignment(Qt.AlignHCenter)
            col.addWidget(title)
            self.stars.setAlignment(Qt.AlignHCenter)
            col.addWidget(self.stars)
            lrow.insertStretch(0, 1)  # centered under the title
            col.addWidget(self.loading)
            if meta:
                info = label(meta, "meta", wrap=True)
                info.setAlignment(Qt.AlignHCenter)
                col.addWidget(info)
            col.addStretch(1)
            self.set_about(result.genres, result.description, result.rating)
            return
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 14, 10)
        row.setSpacing(14)
        row.addWidget(self.cover, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(result.title, "resultTitle", wrap=True))
        text.addWidget(self.stars)
        text.addWidget(self.loading)
        if meta:
            text.addWidget(label(meta, "meta", wrap=True))
        if result.author:
            text.addWidget(label(f"by {result.author}", "hint", wrap=True))
        text.addWidget(self.tags)
        text.addStretch(1)
        row.addLayout(text, 1)
        self.set_about(result.genres, result.description, result.rating)

    def set_about(self, genres: list[str] | None, description: str, rating: float = 0.0) -> None:
        """Show the title's rating, its genres (as tags in the list) and its description when hovered."""
        if genres is None:
            return
        self.stop_loading()
        self.stars.setText(stars_text(rating))
        self.stars.setProperty("unrated", rating <= 0)
        repolish(self.stars)
        self.stars.show()
        tip = f"<b>{html.escape(self.result.title)}</b><br>{stars_text(rating)}"
        if genres:
            tip += f"<br><span>{html.escape('  ·  '.join(genres))}</span>"
        if description:
            short = description if len(description) <= 420 else description[:420].rsplit(" ", 1)[0] + "…"
            tip += "<br><br>" + html.escape(short).replace("\n", "<br>")
        self.setToolTip(f"<qt>{tip}</qt>")
        if not self.grid:
            self.tags.set_tags(genres)

    def start_loading(self) -> None:
        self.loading.show()
        self.loading_cat.start()

    def stop_loading(self) -> None:
        self.loading_cat.stop()
        self.loading.hide()

    def min_width(self) -> int:
        """How narrow this card can get and still look right, for working out the columns."""
        return self.cover_w + 44 if self.grid else self.cover_w + 280

    def set_cover(self, data: bytes | None) -> None:
        self.data = data
        self.cover.setPixmap(rounded_pixmap(data, self.cover_w, self.cover_h, max(8, self.cover_w // 6)))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


def stars_text(rating: float) -> str:
    """A rating out of 5 as stars, like ★★★★☆ 4.5 (0 means nobody has rated it)."""
    if rating <= 0:
        return "☆ No ratings yet"
    full = round(rating)
    return f"{'★' * full}{'☆' * (5 - full)}  {rating:.1f}"


class TagRow(QWidget):
    """A line of genre chips that shows as many as fit and a "+N" chip for the rest."""

    SPACING = 5

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chips: list[QLabel] = []
        self.more = label("", "chip")
        self.more.setParent(self)
        self.more.hide()

    def set_tags(self, tags: list[str]) -> None:
        for chip in self.chips:
            chip.deleteLater()
        self.chips = []
        for tag in tags:
            chip = label(tag, "chip")
            chip.setParent(self)
            self.chips.append(chip)
        self.updateGeometry()
        self._lay_out()

    def sizeHint(self) -> QSize:
        return QSize(0, self.more.sizeHint().height() + 2 if self.chips else 0)

    def resizeEvent(self, event) -> None:
        self._lay_out()

    def _lay_out(self) -> None:
        widths = [c.sizeHint().width() for c in self.chips]
        shown = len(widths)
        while shown:
            hidden = len(widths) - shown
            self.more.setText(f"+{hidden}")
            used = sum(widths[:shown]) + self.SPACING * (shown - 1)
            if hidden:
                used += self.SPACING + self.more.sizeHint().width()
            if used <= self.width():
                break
            shown -= 1
        x = 0
        for i, chip in enumerate(self.chips):
            chip.setVisible(i < shown)
            if i < shown:
                chip.setGeometry(x, 2, widths[i], chip.sizeHint().height())
                x += widths[i] + self.SPACING
        hidden = len(self.chips) - shown
        self.more.setVisible(bool(hidden))
        if hidden:
            self.more.setText(f"+{hidden}")
            self.more.setGeometry(x, 2, self.more.sizeHint().width(), self.more.sizeHint().height())


class FilterPanel(QFrame):
    """Search filters: genres to want or leave out, kind, status and rating, for sites that have them."""
    changed = Signal()

    STATES = ["", "in", "out"]  # a genre tap cycles through these
    RATINGS = [("Any rating", 0), ("2 stars or more", 2), ("3 stars or more", 3), ("4 stars or more", 4)]

    def __init__(self):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 6, 0, 0)
        col.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.kind, self.status, self.rating = combo_box(), combo_box(), combo_box()
        self.kind.setToolTip("Where it's from")
        for text, value in (("Ongoing or finished", ""), ("Still ongoing", core.ONGOING), ("Finished", core.COMPLETED)):
            self.status.addItem(text, value)
        for text, value in self.RATINGS:
            self.rating.addItem(text, value)
        for box in (self.kind, self.status, self.rating):
            box.currentIndexChanged.connect(lambda *_: self.changed.emit())
            row.addWidget(box)
        row.addStretch(1)
        self.clear_btn = QPushButton("Clear filters", objectName="link")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear)
        row.addWidget(self.clear_btn)
        col.addLayout(row)
        col.addWidget(label("Genres: tap once for ones you want, twice to leave them out ✿", "hint", wrap=True))
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        col.addLayout(self.grid)
        self.genres: dict[str, QPushButton] = {}
        self.set_site(core.SITES[0])

    def set_site(self, site_cls) -> None:
        """Offer what this site can filter by; filters it doesn't have are dropped."""
        self.blockSignals(True)
        self.kind.clear()
        self.kind.addItem("Any kind", "")
        for k in getattr(site_cls, "kinds", []):
            self.kind.addItem(k, k)
        for btn in self.genres.values():
            btn.deleteLater()
        self.genres = {}
        for i, g in enumerate(getattr(site_cls, "genres", [])):
            btn = QPushButton(g, objectName="genre")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("state", "")
            btn.clicked.connect(lambda _=False, b=btn: self._cycle(b))
            self.genres[g] = btn
            self.grid.addWidget(btn, i // 6, i % 6)
        self.blockSignals(False)
        self.changed.emit()

    @staticmethod
    def supports(site_cls) -> bool:
        return bool(getattr(site_cls, "genres", None))

    def _cycle(self, btn: QPushButton) -> None:
        state = self.STATES[(self.STATES.index(btn.property("state")) + 1) % len(self.STATES)]
        btn.setProperty("state", state)
        btn.setToolTip({"in": "Only titles with this", "out": "No titles with this"}.get(state, ""))
        repolish(btn)
        self.changed.emit()

    def clear(self) -> None:
        self.blockSignals(True)
        for box in (self.kind, self.status, self.rating):
            box.setCurrentIndex(0)
        for btn in self.genres.values():
            btn.setProperty("state", "")
            btn.setToolTip("")
            repolish(btn)
        self.blockSignals(False)
        self.changed.emit()

    def filters(self) -> core.SearchFilters:
        picked = lambda state: [g for g, b in self.genres.items() if b.property("state") == state]
        return core.SearchFilters(genres=picked("in"), without=picked("out"), kind=self.kind.currentData() or "",
                                  status=self.status.currentData() or "", rating=self.rating.currentData() or 0)

    def count(self) -> int:
        f = self.filters()
        return len(f.genres) + len(f.without) + sum(1 for x in (f.kind, f.status, f.rating) if x)


class SortHeader(QHeaderView):
    """Column titles with room for a small sort arrow next to each, so sorting never shifts the text."""
    ARROW = 16  # room kept in every column

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.sort: tuple[int, bool] | None = None  # (column, descending)

    def sectionSizeFromContents(self, index: int) -> QSize:
        size = super().sectionSizeFromContents(index)
        size.setWidth(size.width() + self.ARROW)
        return size

    def paintSection(self, painter, rect, index) -> None:
        painter.save()
        super().paintSection(painter, rect, index)
        painter.restore()
        if not self.sort or self.sort[0] != index:
            return
        item = self.model().headerData(index, Qt.Horizontal, Qt.TextAlignmentRole)
        align = Qt.AlignmentFlag(int(item)) if item is not None else Qt.AlignCenter
        text = self.model().headerData(index, Qt.Horizontal) or ""
        # The style's own measure of the title (with the real font, unlike self.font() under a
        # stylesheet), minus the section padding from theme.py: 10 left, 9 right.
        width = super().sectionSizeFromContents(index).width() - 19 if text else 0
        if align & Qt.AlignRight:
            x = rect.right() - 9 - width - 12  # before the text
        elif align & Qt.AlignLeft:
            x = rect.left() + 10 + width + 4  # after the text
        else:
            x = rect.center().x() + width / 2 + 4 if text else rect.center().x() - 4
        y = rect.center().y()
        arrow = QPainterPath()
        if self.sort[1]:  # descending: pointing down
            arrow.moveTo(x, y - 2.5); arrow.lineTo(x + 8, y - 2.5); arrow.lineTo(x + 4, y + 3)
        else:
            arrow.moveTo(x, y + 2.5); arrow.lineTo(x + 8, y + 2.5); arrow.lineTo(x + 4, y - 3)
        arrow.closeSubpath()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.color(CURRENT["mode"], "accent"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(theme.color(CURRENT["mode"], "accent"))
        painter.drawPath(arrow)
        painter.restore()


def remove_from_library(parent: QWidget, history: History, key: str, busy: bool = False) -> bool:
    """Take a manga off the library, asking what to do with its downloaded files if it has any."""
    entry = history.get(key) or {}
    title = entry.get("title", "this manga")
    if busy:
        QMessageBox.information(parent, "Still downloading", f"{title} is downloading right now. "
                                "Remove it once that's done ✧")
        return False
    files = history.files(key)
    if not files:
        history.forget(key)
        return True
    folder = files[0].parent
    box = QMessageBox(QMessageBox.Question, "Remove from library", f"Remove {title} from your library?", parent=parent)
    box.setIconPixmap(theme.app_pixmap(96).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    box.setInformativeText(f"You have {len(files)} downloaded {'file' if len(files) == 1 else 'files'} in {folder}.\n"
                           "If you keep them, opening this manga again later still shows what you have.")
    keep = box.addButton("Remove, keep files", QMessageBox.AcceptRole)
    delete = box.addButton("Remove and delete files", QMessageBox.DestructiveRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(keep)
    box.exec()
    if box.clickedButton() is keep:
        history.forget(key)
        return True
    if box.clickedButton() is delete:
        history.delete_files(key)
        return True
    return False


def bar_holder(bar: QProgressBar) -> QWidget:
    """A progress bar with some room around it, for the table's last column."""
    holder = QWidget()
    hl = QHBoxLayout(holder)
    hl.setContentsMargins(6, 0, 10, 0)
    hl.addWidget(bar)
    return holder


def group_keys(group: core.Group) -> list[str]:
    return [chapter_key(c.number) for c in group.chapters]


class DownloadPage(QWidget):
    completed = Signal(str, int, str)  # title, number of files, folder
    COVER_WIDTHS = (150, 280)  # the open title's cover grows with the window between these

    def __init__(self, settings: Settings, history: History):
        super().__init__(objectName="page")
        self.settings = settings
        self.history = history
        self.key = ""  # history key of the loaded title
        self.new_keys: set[str] = set()  # chapters that appeared since the title was last opened
        self._after_fetch = None  # what to do once a title opened from the library has loaded
        self.bridge = Bridge()
        self.bridge.searched.connect(self._on_searched)
        self.bridge.search_failed.connect(self._on_search_failed)
        self.bridge.cover_ready.connect(self._on_cover)
        self.bridge.about_ready.connect(self._on_about)
        self.bridge.about_missed.connect(self._on_about_missed)
        self.search_id = 0  # results of older searches are ignored
        self.results: list[ResultItem] = []  # shown right now
        self.search_site = None
        self.search_query = ""
        self.search_filters = core.SearchFilters()
        self.search_sort = ""  # one of the site's `sorts`, "" for its own order
        self.search_resort: str | None = None  # the order showing while another one is fetched
        self.search_pages: dict[int, list] = {}  # results page -> SearchResults, fetched so far
        self.search_page = 1
        self.search_total = 1
        self.search_loading = 0  # results page being fetched, or 0
        self.cover_token = 0  # covers for an older page are ignored
        self.cover_cache: dict[str, bytes | None] = {}
        self.about_cache: dict[str, tuple[list[str], str, float]] = {}  # title url -> genres, description, rating
        self.bridge.fetched.connect(self._on_fetched)
        self.bridge.fetch_failed.connect(self._on_fetch_failed)
        self.bridge.status.connect(self._on_status)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.estimated.connect(self._on_estimated)
        self.bytes_per_chapter: float | None = None
        self.estimating = False
        self.states: dict[int, str] = {}
        self.run_t0 = 0.0
        self.samples: list[tuple[float, float]] = []  # (time, overall progress) for the time-left estimate
        self.tick = QTimer(self, interval=1000)
        self.tick.timeout.connect(self._refresh_run_status)
        self.site = None
        self.info: core.MangaInfo | None = None
        self.groups: list[core.Group] = []
        self.bars: list[QProgressBar] = []  # one per file, in self.groups order
        self.order: list[int] = []  # file shown in each table row
        self.row_of: list[int] = []  # table row of each file
        self.cancel = threading.Event()
        self.running = False
        self.fractions: dict[int, float] = {}
        self.book_dir: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(32, 28, 32, 16)
        col.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        col.addWidget(label("Download a manga ✧", "h1"))

        # find
        find, fl = card()
        row = QHBoxLayout()
        self.source = combo_box()
        for site in core.SITES:
            self.source.addItem(site.name, site.name)
        self.source.setCurrentIndex(max(0, self.source.findData(settings.default_source)))
        self.source.setToolTip("Where to search")
        self.source.currentIndexChanged.connect(self._source_changed)
        self.query = QLineEdit(placeholderText="Type a manga name, like One Piece ✧", maxLength=200)
        self.query.returnPressed.connect(self._find)
        self.fetch_btn = set_icon(QPushButton(" Search", objectName="primary"), "search", "white")
        self.fetch_btn.clicked.connect(self._find)
        self.filter_btn = set_icon(QPushButton(" Filters", checkable=True), "filter")
        self.filter_btn.setToolTip("Narrow the search down by genre, kind, status or rating")
        row.addWidget(self.source)
        row.addWidget(self.query, 1)
        row.addWidget(self.filter_btn)
        row.addWidget(self.fetch_btn)
        fl.addLayout(row)
        self.filters = FilterPanel()
        self.filters.hide()
        self.filters.changed.connect(self._filters_changed)
        self.filter_btn.toggled.connect(self.filters.setVisible)
        fl.addWidget(self.filters)
        hint_row = QHBoxLayout()
        self.back_btn = set_icon(QPushButton(" Back to results"), "list")
        self.back_btn.clicked.connect(self._show_results)
        self.back_btn.hide()
        hint_row.addWidget(self.back_btn)
        self.find_hint = label(self._idle_hint(), "hint", wrap=True)
        hint_row.addWidget(self.find_hint, 1)
        fl.addLayout(hint_row)
        col.addWidget(find)
        self._source_changed()

        # search results
        self.results_card, rl = card()
        rhead = QHBoxLayout()
        rhead.addWidget(label("Pick one ✧", "h2"))
        rhead.addSpacing(10)
        self.view_btns = QButtonGroup(self)
        for grid, icon, tip in ((False, "list", "Show as a list"), (True, "grid", "Show as a grid of covers")):
            btn = set_icon(QPushButton(objectName="viewToggle", checkable=True), icon)
            btn.setToolTip(tip)
            btn.setChecked(grid == settings.results_grid)
            btn.clicked.connect(lambda _=False, g=grid: self._set_results_look(grid=g))
            self.view_btns.addButton(btn)
            rhead.addWidget(btn)
        self.size_box = combo_box()
        self.size_box.addItems(ResultItem.SIZES)
        self.size_box.setCurrentIndex(min(max(settings.results_size, 0), len(ResultItem.SIZES) - 1))
        self.size_box.setToolTip("How big the covers are")
        self.size_box.currentIndexChanged.connect(lambda i: self._set_results_look(size=i))
        rhead.addWidget(self.size_box)
        self.sort_box = combo_box()
        self.sort_box.setToolTip("Sort by")
        self.sort_box.currentIndexChanged.connect(self._resort)
        rhead.addWidget(self.sort_box)
        rhead.addStretch(1)
        self.results_dots = MiniCat(lambda: CURRENT["mode"])
        rhead.addWidget(self.results_dots)
        self.results_wait = label("fetching more ✧", "meta")
        self.results_wait.hide()
        rhead.addWidget(self.results_wait)
        self.results_count = label("", "meta")
        rhead.addWidget(self.results_count)
        rl.addLayout(rhead)
        self.results_grid = QGridLayout()
        self.results_grid.setHorizontalSpacing(12)
        self.results_grid.setVerticalSpacing(12)
        self.results_cols = 0
        rl.addLayout(self.results_grid)
        self.results_card.installEventFilter(self)  # re-flow the columns when the window resizes
        rpager = QHBoxLayout()
        rpager.addStretch(1)
        self.rprev_btn = QPushButton("‹", objectName="pager")
        self.rprev_btn.setToolTip("Previous results")
        self.rprev_btn.clicked.connect(lambda: self._goto_results(self.search_page - 1))
        self.rpage_lbl = label("", "meta")
        self.rnext_btn = QPushButton("›", objectName="pager")
        self.rnext_btn.setToolTip("More results")
        self.rnext_btn.clicked.connect(lambda: self._goto_results(self.search_page + 1))
        for w in (self.rprev_btn, self.rpage_lbl, self.rnext_btn):
            rpager.addWidget(w)
        rpager.addStretch(1)
        rl.addLayout(rpager)
        self.results_card.hide()
        col.addWidget(self.results_card)

        # shown while a title is being looked up
        self.lookup_card, lk = card()
        lrow = QHBoxLayout()
        lrow.addStretch(1)
        self.lookup_cat = CatLoader(lambda: CURRENT["mode"], (150, 120))
        lrow.addWidget(self.lookup_cat)
        ltext = QVBoxLayout()
        ltext.addStretch(1)
        self.lookup_title = label("", "h2")
        self.lookup_text = label("", "hint")
        ltext.addWidget(self.lookup_title)
        ltext.addWidget(self.lookup_text)
        ltext.addStretch(1)
        lrow.addLayout(ltext)
        lrow.addStretch(1)
        lk.addLayout(lrow)
        self.lookup_card.hide()
        col.addWidget(self.lookup_card)

        # manga details and options
        self.manga_card, ml = card()
        top = QHBoxLayout()
        top.setSpacing(22)
        self.cover = QLabel()
        self.cover.setFixedSize(self._cover_size())
        top.addWidget(self.cover, 0, Qt.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(8)
        self.title_lbl = label("", "mangaTitle", wrap=True)
        self.meta_lbl = label("", "meta", wrap=True)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.addWidget(self.title_lbl, 1)
        self.lib_btn = set_icon(QPushButton(" Add to library"), "library")
        self.lib_btn.clicked.connect(self._toggle_library)
        title_row.addWidget(self.lib_btn, 0, Qt.AlignTop)
        right.addLayout(title_row)
        right.addWidget(self.meta_lbl)
        right.addLayout(self.chips)
        self.about_lbl = label("", "about", wrap=True)
        self.about_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.about_more = QPushButton("Read more ✧", objectName="link")
        self.about_more.setCursor(Qt.PointingHandCursor)
        self.about_more.clicked.connect(lambda: self._show_about(not self.about_open))
        self.about_open = False
        right.addWidget(self.about_lbl)
        right.addWidget(self.about_more, 0, Qt.AlignLeft)
        right.addSpacing(6)
        form = form_layout()
        self.fmt = combo_box()
        for key, name in FORMATS.items():
            self.fmt.addItem(name, key)
        form.addRow("Format", self.fmt)
        self.per_file = spin(minimum=1, maximum=999)
        self.per_file.valueChanged.connect(self._regroup)
        self.per_file_lbl = QLabel("Chapters per file")
        form.addRow(self.per_file_lbl, self.per_file)
        self.save_to = QLineEdit()
        watch_folder(self.save_to)
        form.addRow("Save to", folder_row(self.save_to, "Download folder"))
        right.addLayout(form)
        self.loose_note = label("", "hint", wrap=True)
        right.addWidget(self.loose_note)
        right.addStretch(1)
        top.addLayout(right, 1)
        ml.addLayout(top)
        self.manga_card.hide()
        self.manga_card.installEventFilter(self)  # the cover grows with the card
        col.addWidget(self.manga_card)

        # files table
        self.files_card, tl = card()
        head = QHBoxLayout()
        head.addWidget(label("Files", "h2"))
        head.addStretch(1)
        self.summary = label("", "meta")
        head.addWidget(self.summary)
        self.summary_dots = MiniCat(lambda: CURRENT["mode"])
        head.addWidget(self.summary_dots)
        self.summary_wait = label("weighing pages ✧", "meta")
        self.summary_wait.hide()
        head.addWidget(self.summary_wait)
        tl.addLayout(head)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeader(SortHeader())
        self.table.setHorizontalHeaderLabels(HEADERS)
        for c, side in ((1, Qt.AlignLeft), (2, Qt.AlignLeft), (3, Qt.AlignRight), (4, Qt.AlignRight), (5, Qt.AlignCenter)):
            self.table.horizontalHeaderItem(c).setTextAlignment(side | Qt.AlignVCenter)  # line up with the cells
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = self.table.horizontalHeader()
        # Tap a column to sort by it: ascending, descending, then back to normal. Right-click clears it.
        self.sort: tuple[int, bool] | None = None  # (column, descending)
        hh.setSectionsClickable(True)
        hh.setCursor(Qt.PointingHandCursor)
        hh.setToolTip("Tap to sort ✧ right-click to unsort")
        hh.sectionClicked.connect(self._sort_clicked)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(lambda *_: self._set_sort(None))
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setItemDelegateForColumn(4, CatDelegate(self.table))
        hh.setSectionResizeMode(4, QHeaderView.Fixed)  # stays wide enough for the cat while loading
        self.table.setColumnWidth(4, 100)
        self.size_anim = QTimer(self, interval=40)
        self.size_anim.timeout.connect(lambda: self.table.viewport().update())
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.itemChanged.connect(self._update_summary)
        tl.addWidget(self.table)
        self.anchor: int | None = None  # file of the last paw clicked, for shift-click
        self.drag_state: bool | None = None  # ticking or unticking while dragging across paws
        self.table.viewport().installEventFilter(self)
        self.page = 0
        self.prev_btn = QPushButton("‹", objectName="pager")
        self.prev_btn.setToolTip("Previous page")
        self.prev_btn.clicked.connect(lambda: self._show_page(self.page - 1))
        self.page_lbl = label("", "meta")
        self.next_btn = QPushButton("›", objectName="pager")
        self.next_btn.setToolTip("Next page")
        self.next_btn.clicked.connect(lambda: self._show_page(self.page + 1))
        pager = QHBoxLayout()
        pager.addStretch(1)
        for w in (self.prev_btn, self.page_lbl, self.next_btn):
            pager.addWidget(w)
        pager.addStretch(1)
        tl.addLayout(pager)

        picks = QHBoxLayout()
        self.select_btn = set_icon(QPushButton(" Select all"), "paw_outline")
        self.select_btn.clicked.connect(self._toggle_all)
        self.page_btn = set_icon(QPushButton(" Select page"), "list")
        self.page_btn.setToolTip("Tick or untick just the files on this page")
        self.page_btn.clicked.connect(self._toggle_page)
        # Quick picks from the download history; each replaces the current selection.
        self.smart: dict[str, list[int]] = {"new": [], "missing": [], "failed": []}
        self.smart_btns = {}
        for kind, icon, tip in (("new", "cat", "Files with chapters that came out since you last looked"),
                                ("missing", "download", "Files you don't have yet (or only partly)"),
                                ("failed", "refresh", "Files that failed last time")):
            b = set_icon(QPushButton(), icon)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, kind=kind: self._check(lambda i, kind=kind: i in self.smart[kind]))
            self.smart_btns[kind] = b
        picks.addWidget(self.select_btn)
        picks.addWidget(self.page_btn)
        picks.addSpacing(12)
        for b in self.smart_btns.values():
            picks.addWidget(b)
        picks.addStretch(1)
        tl.addLayout(picks)

        ranges = QHBoxLayout()
        self.range_unit = combo_box()  # only when the title has both volumes and loose chapters
        self.range_unit.addItem("Volumes", "volume")
        self.range_unit.addItem("Chapters", "chapter")
        self.range_unit.currentIndexChanged.connect(lambda *_: self._range_bounds())
        self.range_unit.hide()
        ranges.addWidget(self.range_unit)
        self.range_lbl = label("Chapters", "meta")
        ranges.addWidget(self.range_lbl)
        self.range_key = ""  # title the unit was last picked for
        self.range_from = spin(minimum=0, maximum=0)
        ranges.addWidget(self.range_from)
        ranges.addWidget(label("to", "meta"))
        self.range_to = spin(minimum=0, maximum=0)
        ranges.addWidget(self.range_to)
        self.range_btn = set_icon(QPushButton(" Select"), "check")
        self.range_btn.clicked.connect(self._select_range)
        ranges.addWidget(self.range_btn)
        ranges.addSpacing(12)
        ranges.addWidget(label("Shift-click a paw to tick everything in between, or drag across them ✧",
                               "hint", wrap=True), 1)
        tl.addLayout(ranges)
        self.files_card.hide()
        col.addWidget(self.files_card)
        col.addStretch(1)

        # bottom bar
        bar = QFrame(objectName="card")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(22, 14, 22, 14)
        bl.setSpacing(14)
        self.bar_cat = CatLoader(lambda: CURRENT["mode"], (62, 50))
        bl.addWidget(self.bar_cat)
        info = QVBoxLayout()
        self.status_lbl = label("Search for a manga to get started ♡", "meta")
        self.overall = QProgressBar(maximum=1000, textVisible=False)
        self.overall.setFixedHeight(12)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.addWidget(self.status_lbl)
        self.status_dots = MiniCat(lambda: CURRENT["mode"])
        status_row.addWidget(self.status_dots)
        self.status_wait = label("weighing pages ✧", "meta")
        self.status_wait.hide()
        status_row.addWidget(self.status_wait)
        status_row.addStretch(1)
        info.addLayout(status_row)
        info.addWidget(self.overall)
        bl.addLayout(info, 1)
        self.open_btn = set_icon(QPushButton(" Open folder"), "folder")
        self.open_btn.clicked.connect(self._open_folder)
        self.open_btn.hide()
        self.cancel_btn = set_icon(QPushButton(" Cancel"), "close")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        self.start_btn = set_icon(QPushButton(" Download", objectName="primary"), "download", "white", 20)
        self.start_btn.clicked.connect(self._start)
        self.start_btn.setEnabled(False)
        for w in (self.open_btn, self.cancel_btn, self.start_btn):
            bl.addWidget(w)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(32, 4, 32, 22)
        wl.addWidget(bar)
        outer.addWidget(wrap)

    # ---- fetching

    def _idle_hint(self) -> str:
        return "Pasting a link to a title works too ✧"

    def _start_lookup(self, title: str, text: str) -> None:
        self.lookup_title.setText(title)
        self.lookup_text.setText(text)
        self.fetch_btn.setEnabled(False)
        self.results_card.hide()
        self.back_btn.hide()
        self.lookup_card.show()
        self.lookup_cat.start()

    def _source_changed(self) -> None:
        site_cls = core.site_named(self.source.currentData())
        self.filters.set_site(site_cls)
        self.filter_btn.setVisible(FilterPanel.supports(site_cls))
        if not FilterPanel.supports(site_cls):
            self.filter_btn.setChecked(False)
        self._hint(self._idle_hint())

    def _filters_changed(self) -> None:
        n = self.filters.count()
        self.filter_btn.setText(f" Filters ({n})" if n else " Filters")
        self.filters.clear_btn.setVisible(bool(n))
        self.query.setPlaceholderText("Type a manga name, or leave it empty to browse ✧" if n
                                      else "Type a manga name, like One Piece ✧")

    def _find(self) -> None:
        text = self.query.text().strip()
        site_cls = core.site_named(self.source.currentData())
        filters = self.filters.filters() if FilterPanel.supports(site_cls) else core.SearchFilters()
        if not text and not filters:
            self._hint("Type a manga name first, or pick some filters ✧", error=True)
            return
        if core.site_for(text):
            self._fetch(text)
            return
        if text and len(text) < 2:
            self._hint("Type at least 2 letters of the name", error=True)
            return
        if len(text) > 100:
            self._hint("That's a very long name; try just the main part of the title", error=True)
            return
        if re.match(r"https?://", text):
            self._hint("That isn't a title link from a supported site: "
                       + ", ".join(s.example for s in core.SITES), error=True)
            return
        self.search_id += 1
        self.search_site, self.search_query, self.search_filters = site_cls, text, filters
        self._sort_options(site_cls)
        self.search_pages, self.search_page, self.search_total, self.search_loading = {}, 1, 1, 0
        self.search_resort = None
        self._hint(f"Searching {site_cls.name}…")
        self._start_lookup("Searching…" if text else "Browsing…", f"Asking {site_cls.name} for matches ✧")
        self._search_page(1)

    def _search_page(self, page: int) -> None:
        sid, site_cls, query, filters = self.search_id, self.search_site, self.search_query, self.search_filters
        extra = {"sort": self.search_sort} if self.search_sort else {}
        limiter = core.RateLimiter(self.settings.request_delay)

        def work() -> None:
            try:
                results, pages = site_cls.search(query, limiter, page, filters, **extra) if filters \
                    else site_cls.search(query, limiter, page, **extra)
                self.bridge.searched.emit(sid, site_cls, query, page, results, pages)
            except Exception as e:
                self.bridge.search_failed.emit(sid, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _sort_options(self, site_cls) -> None:
        """Offer the site's sort orders, keeping the chosen one if it has it too."""
        sorts = getattr(site_cls, "sorts", [])
        self.sort_box.blockSignals(True)
        self.sort_box.clear()
        self.sort_box.addItems(sorts)
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findText(self.search_sort)))
        self.sort_box.blockSignals(False)
        self.sort_box.setVisible(bool(sorts))
        self.search_sort = self.sort_box.currentText() if self.sort_box.currentIndex() > 0 else ""

    def _resort(self, index: int) -> None:
        """Search again in the new order, from page 1, keeping these results up until the new ones come."""
        sort = self.sort_box.itemText(index) if index > 0 else ""
        if sort == self.search_sort or not self.search_pages:
            return
        self.search_id += 1
        self.search_sort, self.search_resort = sort, self.search_sort
        self.search_loading = 1
        self._results_waiting(True)
        self.results_wait.setText("sorting ✧")
        self._search_page(1)

    def _goto_results(self, page: int) -> None:
        if not 1 <= page <= self.search_total or self.search_loading:
            return
        if page in self.search_pages:
            self._show_results_page(page)
            return
        self.search_loading = page  # fetch it from the site first
        self._results_waiting(True)
        self.results_wait.setText("fetching more ✧")
        self._search_page(page)

    def _results_waiting(self, on: bool) -> None:
        self.results_dots.start() if on else self.results_dots.stop()
        self.results_wait.setVisible(on)
        self.results_count.setVisible(not on)
        self.rprev_btn.setEnabled(not on and self.search_page > 1)
        self.rnext_btn.setEnabled(not on and self.search_page < self.search_total)

    def _on_search_failed(self, sid: int, message: str) -> None:
        if sid != self.search_id:
            return
        if self.search_loading:  # a later page or another order; keep showing this one
            self.search_loading = 0
            self._results_waiting(False)
            if self.search_resort is not None:  # put the sort back to what's showing
                self.search_sort, self.search_resort = self.search_resort, None
                self.sort_box.blockSignals(True)
                self.sort_box.setCurrentIndex(max(0, self.sort_box.findText(self.search_sort)))
                self.sort_box.blockSignals(False)
            self._hint(f"Couldn't get more results: {message}", error=True)
        else:
            self._on_fetch_failed(message)

    def _on_searched(self, sid: int, site_cls, query: str, page: int, results: list, pages: int) -> None:
        if sid != self.search_id:
            return
        if self.search_resort is not None:  # a new order: start the pages over
            self.search_resort = None
            self.search_pages, self.search_page = {}, 1
            if not results:
                self.search_loading = 0
                self._results_waiting(False)
                self._clear_results()
                self.results_card.hide()
                self._hint(f"{site_cls.name} didn't send anything back in that order. Try another ✧", error=True)
                return
        fresh = not self.search_pages
        if fresh:
            self._end_lookup()
            self.fetch_btn.setEnabled(True)
            if not results:
                self._clear_results()
                if self.search_filters:
                    self._hint(f"Nothing on {site_cls.name} fits those filters. Try loosening them a little ✧",
                               error=True)
                else:
                    self._hint(f"Nothing called “{query}” on {site_cls.name}. Try another spelling ✧", error=True)
                return
            many = f"{pages} pages of matches" if pages > 1 else f"{len(results)} {'match' if len(results) == 1 else 'matches'}"
            self._hint(f"Found {many} on {site_cls.name}. Pick the one you want ♡")
        self.search_loading = 0
        self._results_waiting(False)
        self.search_total = max(pages, page)
        if results:
            self.search_pages[page] = results
            self._show_results_page(page)
        else:  # the site ran out sooner than its page links said
            self.search_total = self.search_page
            self._results_waiting(False)
            self._show_results_page(self.search_page)
        if fresh:
            self.manga_card.hide()
            self.files_card.hide()
            self.results_card.show()

    def _clear_results(self) -> None:
        for item in self.results:
            self.results_grid.removeWidget(item)  # now, not when deleteLater gets round to it
            item.hide()
            item.deleteLater()
        self.results = []

    def _fill_results(self, results: list[core.SearchResult]) -> None:
        self._clear_results()
        grid, size = self.settings.results_grid, self.size_box.currentIndex()
        for result in results:
            item = ResultItem(result, grid, size)
            item.clicked.connect(lambda r=result: self._pick(r))
            if result.cover_url in self.cover_cache:
                item.set_cover(self.cover_cache[result.cover_url])
            if result.url in self.about_cache:
                item.set_about(*self.about_cache[result.url])
            elif hasattr(self.search_site, "about"):
                item.start_loading()
            self.results.append(item)
        self.results_cols = 0
        self._place_results()

    def _place_results(self) -> None:
        """Lay the cards out in as many columns as fit (lists stop at 3, so rows stay readable)."""
        if not self.results:
            return
        spacing = self.results_grid.horizontalSpacing()
        m = self.results_card.layout().contentsMargins()
        room = self.results_card.width() - m.left() - m.right()
        cols = max(1, (room + spacing) // (self.results[0].min_width() + spacing))
        if not self.settings.results_grid:
            cols = min(cols, 3)
        if cols == self.results_cols:
            return
        for c in range(max(cols, self.results_grid.columnCount())):
            self.results_grid.setColumnStretch(c, 1 if c < cols else 0)
        self.results_cols = cols
        for i, item in enumerate(self.results):
            self.results_grid.removeWidget(item)
            self.results_grid.addWidget(item, i // cols, i % cols)  # fills its cell, so a row's cards match

    def _set_results_look(self, grid: bool | None = None, size: int | None = None) -> None:
        if grid is not None:
            self.settings.results_grid = grid
        if size is not None:
            self.settings.results_size = size
        self.settings.save()
        if self.results and self.search_page in self.search_pages:
            self._fill_results(self.search_pages[self.search_page])

    def _show_results_page(self, page: int) -> None:
        results = self.search_pages[page]
        self.search_page = page
        self._fill_results(results)
        self.results_count.setText(f"page {page} of {self.search_total}")
        self.rpage_lbl.setText(f"Page {page} of {self.search_total}")
        for w in (self.rprev_btn, self.rpage_lbl, self.rnext_btn):
            w.setVisible(self.search_total > 1)
        self._results_waiting(False)
        if page > 1 or self.search_total > 1:
            bar = self.findChild(QScrollArea).verticalScrollBar()
            bar.setValue(min(bar.value(), self.results_card.y()))  # back to the top of the results
        self.cover_token += 1
        token, site_cls = self.cover_token, self.search_site
        missing = [(i, r.cover_url) for i, r in enumerate(results) if r.cover_url and r.cover_url not in self.cover_cache]
        unknown = [(i, r.url) for i, r in enumerate(results) if r.url not in self.about_cache]
        limiter = core.RateLimiter(self.settings.request_delay)

        def covers() -> None:
            site = site_cls("", limiter)
            for i, url in missing:
                if token != self.cover_token:
                    return  # another page is showing now
                self.bridge.cover_ready.emit(token, i, site.cover(url))
            if not hasattr(site, "about"):
                return
            for i, url in unknown:  # then the genres and descriptions, which need each title's page
                if token != self.cover_token:
                    return
                try:
                    genres, description, rating = site.about(url)
                except core.SiteError:
                    self.bridge.about_missed.emit(token, i)  # the card just stays without tags
                    continue
                self.bridge.about_ready.emit(token, i, genres, description, rating)

        if missing or unknown:
            threading.Thread(target=covers, daemon=True).start()

    def _on_cover(self, token: int, index: int, data) -> None:
        if token == self.cover_token and index < len(self.results):
            self.cover_cache[self.results[index].result.cover_url] = data
            self.results[index].set_cover(data)

    def _on_about(self, token: int, index: int, genres: list, description: str, rating: float) -> None:
        if token == self.cover_token and index < len(self.results):
            self.about_cache[self.results[index].result.url] = (genres, description, rating)
            self.results[index].set_about(genres, description, rating)

    def _on_about_missed(self, token: int, index: int) -> None:
        if token == self.cover_token and index < len(self.results):
            self.results[index].stop_loading()

    def _pick(self, result: core.SearchResult) -> None:
        if not self.running:
            self._fetch(result.url)

    def _show_results(self) -> None:
        self.back_btn.hide()
        self.results_card.show()

    def _fetch(self, url: str) -> None:
        site_cls = core.site_for(url)
        self._hint("Looking it up…")
        self.manga_card.hide()
        self.files_card.hide()
        self._start_lookup("Looking it up…", "Reading the chapter list and cover ✧")
        limiter = core.RateLimiter(self.settings.request_delay)

        def work() -> None:
            try:
                site = site_cls(url, limiter)
                self.bridge.fetched.emit(site, site.info())
            except Exception as e:
                self.bridge.fetch_failed.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def _hint(self, text: str, error: bool = False) -> None:
        self.find_hint.setText(text)
        self.find_hint.setProperty("error", error)
        repolish(self.find_hint)

    def _end_lookup(self) -> None:
        self.lookup_cat.stop()
        self.lookup_card.hide()

    def _on_fetch_failed(self, message: str) -> None:
        self._end_lookup()
        self.fetch_btn.setEnabled(True)
        self._hint(message, error=True)
        if self.results:
            self.results_card.show()  # pick another one instead

    def _on_fetched(self, site, info: core.MangaInfo) -> None:
        self._end_lookup()
        self.fetch_btn.setEnabled(True)
        self._hint(self._idle_hint())
        if not info.chapters:
            self._on_fetch_failed("No chapters found on that page.")
            return
        self.site, self.info = site, info
        self.key = site.key
        self.history.prune_missing()
        self.new_keys = set()
        if self.history.in_library(self.key):  # only titles in the library are kept up to date there
            known = set(self.history.get(self.key).get("known", []))
            self.new_keys = {chapter_key(c.number) for c in info.chapters} - known if known else set()
            self._add_to_library()
        self.sync_library_btn()
        self.refresh_cover()
        self.title_lbl.setText(info.title)
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for g in info.genres[:6]:
            self.chips.addWidget(label(g, "chip"))
        self.chips.addStretch(1)
        self._show_about(False)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(self.settings.default_format)))
        self.save_to.setText(self.settings.download_dir)

        loose = sum(1 for c in info.chapters if c.volume == core.NO_VOLUME)
        self.per_file.blockSignals(True)
        self.per_file.setMaximum(max(1, loose))
        range_tip(self.per_file)
        self.per_file.setValue(min(self.settings.chapters_per_file, max(1, loose)))
        self.per_file.blockSignals(False)
        self.per_file.setVisible(bool(loose))
        self.per_file_lbl.setVisible(bool(loose))
        self.loose_note.setVisible(bool(loose))
        self.loose_note.setText(f"{loose} of {len(info.chapters)} chapters have no volume number on this site, "
                                "so they are grouped into files by chapter count.")
        self.manga_card.show()
        self.files_card.show()
        self.back_btn.setVisible(bool(self.results))
        self.open_btn.hide()
        self.bytes_per_chapter = None
        self.estimating = True
        self._regroup()

        def estimate() -> None:
            try:
                value = core.estimate_chapter_bytes(site, info.chapters)
            except Exception:
                value = None
            self.bridge.estimated.emit(info, value)

        threading.Thread(target=estimate, daemon=True).start()
        if self._after_fetch:
            action, self._after_fetch = self._after_fetch, None
            action()

    # ---- library

    def _add_to_library(self) -> None:
        """Save the open title to the library (or refresh it there), with its cover and chapter list."""
        if not self.info or not self.site:
            return
        info = self.info
        self.history.remember(self.key, self.site.title_url, info.title, len(info.chapters), info.status, info.cover)
        self.history.mark_seen(self.key, [chapter_key(c.number) for c in info.chapters])
        self.sync_library_btn()

    def _toggle_library(self) -> None:
        if self.running:
            return  # the running download is being recorded there
        if self.history.in_library(self.key):
            if remove_from_library(self, self.history, self.key, busy=self.running):
                self.sync_library_btn()
                if not self.history.get(self.key):
                    self._regroup()  # its files were deleted: start the table over
        else:
            self._add_to_library()

    def sync_library_btn(self) -> None:
        inside = bool(self.key) and self.history.in_library(self.key)
        self.lib_btn.setText(" Remove from library" if inside else " Add to library")
        swap_icon(self.lib_btn, "close" if inside else "library")
        self.lib_btn.setEnabled(not self.running)
        self.lib_btn.setToolTip("Take it off the Library page; your downloaded files stay where they are"
                                if inside else "Keep it on the Library page; downloading adds it too")

    # ---- opening from the library

    def open_manga(self, url: str, action: str = "open") -> None:
        """Load a title; with action "continue" or "retry", also start downloading what's left or what failed."""
        if action != "open":
            self._after_fetch = lambda: self._resume(action == "retry")
        self._fetch(url)

    def apply_defaults(self, old: Settings) -> None:
        """After the settings were saved: fields still on the old default follow the new one, edited ones stay."""
        s = self.settings
        if self.source.currentData() == old.default_source:
            self.source.setCurrentIndex(max(0, self.source.findData(s.default_source)))
        if s.files_per_page != old.files_per_page:  # stay on the page with the file that was at the top
            self._show_page(self.page * old.files_per_page // s.files_per_page)
        if not self.info or self.running:
            return
        if self.fmt.currentData() == old.default_format:
            self.fmt.setCurrentIndex(max(0, self.fmt.findData(s.default_format)))
        if self.save_to.text().strip() == old.download_dir:
            self.save_to.setText(s.download_dir)
        top = self.per_file.maximum()
        if self.per_file.value() == min(old.chapters_per_file, top):
            self.per_file.setValue(min(s.chapters_per_file, top))

    def _resume(self, only_failed: bool) -> None:
        entry = self.history.get(self.key) or {}
        run = entry.get("last_run", {})
        if run.get("format"):
            self.fmt.setCurrentIndex(max(0, self.fmt.findData(run["format"])))
        if run.get("per_file") and self.per_file.isVisible():
            self.per_file.setValue(run["per_file"])
        if run.get("save_to"):
            self.save_to.setText(run["save_to"])
        wanted = set(entry.get("failed" if only_failed else "pending", []))
        self._check(lambda i: bool(wanted & set(group_keys(self.groups[i]))))
        if self._checked_rows():
            self._start()
        else:
            self._status("Nothing left to download ♡")

    ABOUT_SHORT = 320  # characters of the description shown before "Read more"

    def _show_about(self, full: bool) -> None:
        text = self.info.description if self.info else ""
        long = len(text) > self.ABOUT_SHORT
        self.about_open = full and long
        if long and not full:
            text = text[:self.ABOUT_SHORT].rsplit(" ", 1)[0].rstrip(".,;: ") + "…"
        self.about_lbl.setText(text)
        self.about_lbl.setVisible(bool(text))
        self.about_more.setText("Show less" if self.about_open else "Read more ✧")
        self.about_more.setVisible(long)

    def _cover_size(self) -> QSize:
        """About a fifth of the details card's width, in the 54:76 shape of manga covers."""
        low, high = self.COVER_WIDTHS
        w = min(max(round(self.manga_card.width() * 0.2), low), high) if hasattr(self, "manga_card") else low
        return QSize(w, round(w * 76 / 54))

    def refresh_cover(self) -> None:
        if self.info:
            size = self.cover.size()
            self.cover.setPixmap(rounded_pixmap(self.info.cover, size.width(), size.height(), radius=18))
        for item in self.results:
            item.set_cover(item.data)  # the placeholder follows the theme

    # ---- file table

    def _regroup(self) -> None:
        if not self.info:
            return
        self.groups = core.make_groups(self.info.chapters, self.per_file.value())
        vols = sum(1 for c in self.info.chapters if c.volume != core.NO_VOLUME)
        status = f"{self.info.status}  ·  " if self.info.status else ""
        status += f"{stars_text(self.info.rating)}  ·  "
        self.meta_lbl.setText(f"{status}{len(self.info.chapters)} chapters  ·  "
                              f"{'volume numbers available' if vols else 'no volume numbers'}")
        self.table.blockSignals(True)
        self.table.setRowCount(0)  # fresh rows; the old progress bars go with them
        self.table.setRowCount(len(self.groups))
        self.bars = []
        for i, g in enumerate(self.groups):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled)  # clicks on paws are handled in eventFilter
            check.setCheckState(Qt.Checked)
            self.table.setItem(i, 0, check)
            self.table.setItem(i, 1, QTableWidgetItem(g.label))
            self.table.setItem(i, 2, QTableWidgetItem(core.chapter_span(g.chapters)))
            count = QTableWidgetItem(str(len(g.chapters)))
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 3, count)
            size = QTableWidgetItem()
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 4, size)
            bar = QProgressBar(maximum=1000, value=0, format="")
            bar.setFixedHeight(18)
            self.table.setCellWidget(i, 5, bar_holder(bar))
            self.bars.append(bar)
        self.table.blockSignals(False)
        self.order = list(range(len(self.groups)))
        self.row_of = list(self.order)
        self._apply_sort()
        self._show_page(0)
        self.anchor = None
        has_volumes = any(c.volume != core.NO_VOLUME for c in self.info.chapters)
        has_loose = any(c.volume == core.NO_VOLUME for c in self.info.chapters)
        self.range_unit.setVisible(has_volumes and has_loose)
        self.range_lbl.setVisible(not (has_volumes and has_loose))
        self.range_lbl.setText("Chapters" if has_loose else "Volumes")
        if self.range_key != self.key:  # a new title: volumes first when it has them
            self.range_key = self.key
            self.range_unit.blockSignals(True)
            self.range_unit.setCurrentIndex(0 if has_volumes else 1)
            self.range_unit.blockSignals(False)
        self._range_bounds()
        self._mark_history()
        self._update_smart()
        self._fill_sizes()
        self._update_summary()

    def _sort_clicked(self, column: int) -> None:
        if not self.sort or self.sort[0] != column:
            self._set_sort((column, False))
        elif not self.sort[1]:
            self._set_sort((column, True))
        else:
            self._set_sort(None)

    def _set_sort(self, sort: tuple[int, bool] | None) -> None:
        self.sort = sort
        self.table.horizontalHeader().sort = sort
        self.table.horizontalHeader().viewport().update()
        self._apply_sort()
        self._show_page(0)

    def _sort_key(self, column: int, row: int):
        group = self.groups[row]
        if column == 0:
            return self._item(row, 0).checkState() != Qt.Checked  # ticked first
        if column in (3, 4):
            return len(group.chapters)  # sizes are estimated from the chapter count
        if column == 5:
            bar = self._bar(row)
            return -1 if bar.property("state") == core.FAILED else bar.value()
        return row  # File and Chapters: the normal order

    def _apply_sort(self) -> None:
        """Move each file's cells to its sorted table row. Elsewhere a "row" is the file's index in
        self.groups, whatever its place on screen; self.order and self.row_of map between the two."""
        order = list(range(len(self.groups)))
        if self.sort:
            column, descending = self.sort
            order.sort(key=lambda g: self._sort_key(column, g), reverse=descending)
        if order == self.order:
            return
        cells = {g: [self.table.takeItem(r, c) for c in range(5)] for r, g in enumerate(self.order)}
        holders = [bar_holder(self.bars[g]) for g in order]  # takes the bars out of their old cells first
        self.table.blockSignals(True)
        for r, g in enumerate(order):
            for c, item in enumerate(cells[g]):
                self.table.setItem(r, c, item)
            self.table.setCellWidget(r, 5, holders[r])
        self.table.blockSignals(False)
        self.order = order
        self.row_of = [0] * len(order)
        for r, g in enumerate(order):
            self.row_of[g] = r

    def _item(self, row: int, column: int) -> QTableWidgetItem:
        """The cell of file `row` (an index into self.groups), wherever sorting put it."""
        return self.table.item(self.row_of[row], column)

    def _show_page(self, page: int) -> None:
        """Show one page of files; the rest stay in the table, just hidden."""
        size = self.settings.files_per_page
        pages = max(1, -(-self.table.rowCount() // size))
        self.page = min(max(0, page), pages - 1)
        first = self.page * size
        shown = range(first, min(first + size, self.table.rowCount()))
        for i in range(self.table.rowCount()):
            self.table.setRowHidden(i, i not in shown)
        last = first + len(shown)
        self.page_lbl.setText(f"Page {self.page + 1} of {pages}  ·  files {first + 1}–{last}")
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled(self.page < pages - 1)
        for w in (self.prev_btn, self.page_lbl, self.next_btn):
            w.setVisible(pages > 1)
        # Fit the shown rows exactly; the page itself scrolls, so the table never needs its own scrollbar.
        rows_h = sum(self.table.rowHeight(i) for i in shown)
        self.table.setFixedHeight(self.table.horizontalHeader().height() + rows_h + 4)
        if self.groups:
            self._update_summary()  # the Select page button follows the page

    def _toggle_all(self) -> None:
        everything = len(self._checked_rows()) == self.table.rowCount()
        self._check(lambda i: not everything)

    def _page_files(self) -> list[int]:
        return [self.order[r] for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]

    def _toggle_page(self) -> None:
        files = self._page_files()
        self._set_checks(files, not all(self._ticked(i) for i in files))

    def _by_volume(self) -> bool:
        if not self.info:
            return False
        if self.range_unit.isVisibleTo(self):
            return self.range_unit.currentData() == "volume"
        return all(c.volume != core.NO_VOLUME for c in self.info.chapters)

    def _loose_chapters(self) -> list[float]:
        """Chapters without a volume, from just after the last one that is in a volume. Sites
        also list a few early side chapters without a volume; those stay out of the range."""
        in_volumes = [c.number for c in self.info.chapters if c.volume != core.NO_VOLUME]
        loose = [c.number for c in self.info.chapters if c.volume == core.NO_VOLUME]
        later = [n for n in loose if n > max(in_volumes)] if in_volumes else loose
        return later or loose

    def _range_bounds(self) -> None:
        """Fit the range boxes to the first and last volume or chapter of the title."""
        if not self.info:
            return
        if self._by_volume():
            numbers = [c.volume for c in self.info.chapters if c.volume != core.NO_VOLUME]
        else:
            numbers = self._loose_chapters()
        for box in (self.range_from, self.range_to):
            box.setRange(int(min(numbers)), math.ceil(max(numbers)))
            range_tip(box)
        self.range_from.setValue(self.range_from.minimum())
        self.range_to.setValue(self.range_to.maximum())
        unit = "volumes" if self._by_volume() else "chapters"
        self.range_btn.setToolTip(f"Tick every file with {unit} in this range")

    def _select_range(self) -> None:
        low, high = sorted((self.range_from.value(), self.range_to.value()))
        if self._by_volume():
            self._check(lambda i: any(c.volume != core.NO_VOLUME and low <= c.volume <= high
                                      for c in self.groups[i].chapters))
        else:
            # Only chapters without a volume (those are picked by volume); high + 1 so "to 10"
            # includes 10.5; a file counts if any of its chapters is in the range.
            self._check(lambda i: any(c.volume == core.NO_VOLUME and low <= c.number < high + 1
                                      for c in self.groups[i].chapters))

    def _ticked(self, row: int) -> bool:
        return self._item(row, 0).checkState() == Qt.Checked

    def _set_checks(self, rows, ticked: bool) -> None:
        self.table.blockSignals(True)
        for i in rows:
            self._item(i, 0).setCheckState(Qt.Checked if ticked else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_summary()

    def eventFilter(self, obj, event) -> bool:
        """Paws: click to toggle, shift-click to set everything since the last click, drag to paint.
        Also re-flows the search results and resizes the cover when their cards change width."""
        if obj is getattr(self, "manga_card", None):  # the results card is resized before this exists
            if event.type() == QEvent.Resize and self.cover.size() != self._cover_size():
                self.cover.setFixedSize(self._cover_size())
                self.refresh_cover()
            return super().eventFilter(obj, event)
        if obj is self.results_card:
            if event.type() == QEvent.Resize:
                self._place_results()
            return super().eventFilter(obj, event)
        if obj is not self.table.viewport() or self.running or not self.groups:
            return super().eventFilter(obj, event)
        kind = event.type()
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            row = self.table.rowAt(pos.y())
            if row < 0 or self.table.columnAt(pos.x()) != 0:
                return super().eventFilter(obj, event)
            file = self.order[row]
            if event.modifiers() & Qt.ShiftModifier and self.anchor is not None:
                low, high = sorted((self.row_of[self.anchor], row))
                self._set_checks([self.order[r] for r in range(low, high + 1)], self._ticked(self.anchor))
            else:
                self.drag_state = not self._ticked(file)
                self.anchor = file
                self._set_checks([file], self.drag_state)
            return True
        if kind == QEvent.MouseMove and self.drag_state is not None:
            row = self.table.rowAt(event.position().toPoint().y())
            if row >= 0 and self._ticked(self.order[row]) != self.drag_state:
                self._set_checks([self.order[row]], self.drag_state)
            return True
        if kind == QEvent.MouseButtonRelease and self.drag_state is not None:
            self.drag_state = None
            return True
        return super().eventFilter(obj, event)

    def _update_smart(self) -> None:
        """Counts for the New / Not downloaded / Failed quick picks."""
        entry = self.history.get(self.key) or {}
        downloaded, failed = entry.get("downloaded", {}), set(entry.get("failed", []))
        self.smart = {"new": [], "missing": [], "failed": []}
        for i, g in enumerate(self.groups):
            keys = group_keys(g)
            if self.new_keys & set(keys):
                self.smart["new"].append(i)
            if not all(k in downloaded for k in keys):
                self.smart["missing"].append(i)
            if failed & set(keys):
                self.smart["failed"].append(i)
        for kind, name in (("new", "New ✧"), ("missing", "Not downloaded"), ("failed", "Failed")):
            self.smart_btns[kind].setText(f" {name} ({len(self.smart[kind])})")
            self.smart_btns[kind].setEnabled(bool(self.smart[kind]) and not self.running)

    def _mark_history(self) -> None:
        """Show what is already downloaded, failed last time or new, and untick finished files."""
        entry = self.history.get(self.key)
        if not entry:
            return
        downloaded, failed = entry.get("downloaded", {}), set(entry.get("failed", []))
        self.table.blockSignals(True)
        for i, g in enumerate(self.groups):
            keys = group_keys(g)
            have = sum(k in downloaded for k in keys)
            bar = self._bar(i)
            state = ""
            if have == len(keys):
                bar.setValue(1000)
                bar.setFormat("Downloaded ✓")
                state = core.DONE
                self._item(i, 0).setCheckState(Qt.Unchecked)
            elif have:
                bar.setValue(int(have / len(keys) * 1000))
                bar.setFormat(f"{have} of {len(keys)} chapters downloaded")
            elif failed & set(keys):
                bar.setFormat("Failed last time")
                state = core.FAILED
            elif self.new_keys & set(keys):
                bar.setFormat("New ✧")
            bar.setProperty("state", state)
            repolish(bar)
        self.table.blockSignals(False)

    def _bar(self, row: int) -> QProgressBar:
        return self.bars[row]

    def _checked_rows(self) -> list[int]:
        return [i for i in range(len(self.groups)) if self._item(i, 0).checkState() == Qt.Checked]

    def _check(self, rule) -> None:
        self.table.blockSignals(True)
        for i in range(len(self.groups)):
            self._item(i, 0).setCheckState(Qt.Checked if rule(i) else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_) -> None:
        rows = self._checked_rows()
        everything = bool(rows) and len(rows) == self.table.rowCount()
        self.select_btn.setText(" Select none" if everything else " Select all")
        swap_icon(self.select_btn, "paw" if everything else "paw_outline")
        page = self._page_files()
        self.page_btn.setText(" Unselect page" if page and all(self._ticked(i) for i in page) else " Select page")
        chapters = sum(len(self.groups[i].chapters) for i in rows)
        size = self._size_text(chapters)
        self.summary.setText(f"{len(rows)} of {len(self.groups)} files  ·  {chapters} chapters  ·  {size}".rstrip())
        waiting = self.estimating and bool(rows)
        # The bottom bar only shows them before a download; once running it shows progress instead.
        for dots, text, show in ((self.summary_dots, self.summary_wait, waiting),
                                 (self.status_dots, self.status_wait, waiting and not self.running)):
            dots.start() if show else dots.stop()
            text.setVisible(show)
        if not self.running:
            self.start_btn.setEnabled(bool(rows))
            if rows:
                self._status(f"Ready to download {len(rows)} {'file' if len(rows) == 1 else 'files'}",
                             f"{chapters} chapters  ·  {size}".rstrip())
            else:
                self._status("Pick at least one file")

    def _size_text(self, chapters: int) -> str:
        if self.estimating:
            return ""  # the little cat stands in for it
        if not self.bytes_per_chapter:
            return "size unknown"
        return f"about {fmt_size(self.bytes_per_chapter * chapters)}"

    def _fill_sizes(self) -> None:
        """Estimated download size of each file: the average chapter size times its chapters."""
        self.table.blockSignals(True)
        for i, g in enumerate(self.groups):
            item = self._item(i, 4)
            item.setData(LOADING, self.estimating)
            if self.estimating:
                text = ""
            elif self.bytes_per_chapter:
                text = f"~{fmt_size(self.bytes_per_chapter * len(g.chapters))}"
            else:
                text = "?"
            item.setText(text)
        self.table.blockSignals(False)
        if self.estimating:
            self.size_anim.start()
        else:
            self.size_anim.stop()

    def _on_estimated(self, info, value) -> None:
        if info is not self.info:  # a different title was looked up meanwhile
            return
        self.bytes_per_chapter = value
        self.estimating = False
        self._fill_sizes()
        self._update_summary()

    def _status(self, headline: str, detail: str = "") -> None:
        """Bottom bar text: a bold pink headline and quieter details after it."""
        accent = theme.color(CURRENT["mode"], "accent").name()
        text = f"<span style='font-size:15px; font-weight:600; color:{accent}'>{html.escape(headline)}</span>"
        if detail:
            text += f"&nbsp;&nbsp;&nbsp;{html.escape(detail)}"
        self.status_lbl.setText(text)

    # ---- downloading

    def _set_locked(self, locked: bool) -> None:
        for w in (self.source, self.query, self.fetch_btn, self.filter_btn, self.filters, self.fmt, self.per_file, self.save_to, self.select_btn,
                  self.page_btn, self.range_unit, self.range_from, self.range_to, self.range_btn, self.lib_btn):
            w.setEnabled(not locked)
        self.table.setEnabled(True)  # paws ignore clicks while running (see eventFilter)
        for b in self.smart_btns.values():
            b.setEnabled(not locked)
        if not locked:
            self._update_smart()

    def _start(self) -> None:
        rows = self._checked_rows()
        if not rows or not self.site:
            return
        problem = folder_problem(self.save_to.text())
        if problem:
            self._status("That download folder won't work", problem)
            self.save_to.setFocus()
            return
        save_to = Path(self.save_to.text().strip() or self.settings.download_dir).expanduser()
        temp_root = Path(self.settings.temp_dir).expanduser() if self.settings.temp_dir else save_to / ".manga-tmp"
        title = self.info.title
        self.book_dir = save_to / core.safe_name(title)
        work_dir = temp_root / core.safe_name(title)
        fmt = self.fmt.currentData()
        workers = self.settings.workers
        mode = self.settings.download_mode
        self.site.limiter.delay = self.settings.request_delay

        self.running = True
        self.cancel = threading.Event()
        self.fractions = {r: 0.0 for r in rows}
        self.states = {r: core.QUEUED for r in rows}
        self.run_t0 = time.monotonic()
        self.status_dots.stop()
        self.status_wait.hide()
        self.samples = []
        self.tick.start()
        self._set_locked(True)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText(" Cancel")
        self.cancel_btn.show()
        self.open_btn.hide()
        self.bar_cat.start()
        self.overall.setValue(0)
        for i in rows:  # other rows keep showing what is already downloaded
            bar = self._bar(i)
            bar.setValue(0)
            bar.setFormat(core.QUEUED)
            bar.setProperty("state", "")
            repolish(bar)
        if not self.history.in_library(self.key):
            self._add_to_library()  # downloads are tracked in the library
        self.history.start_run(self.key, [k for r in rows for k in group_keys(self.groups[r])],
                               fmt, self.per_file.value(), str(save_to))
        self._refresh_run_status()

        groups = [self.groups[r] for r in rows]
        rebuild = self._incomplete(groups, fmt)

        def on_status(index: int, state: str, frac: float, msg: str) -> None:
            self.bridge.status.emit(rows[index], state, frac, msg)

        def work() -> None:
            failed = core.run_jobs(self.site, title, groups, fmt, self.book_dir, work_dir,
                                   self.settings.keep_temp, workers, self.cancel, on_status, mode, rebuild)
            self.bridge.finished.emit([rows[i] for i in failed], self.cancel.is_set())

        threading.Thread(target=work, daemon=True).start()

    def _incomplete(self, groups: list[core.Group], fmt: str) -> frozenset[int]:
        """Groups whose file exists but holds only some of its chapters (the site added more since),
        so it gets made again. A file the history knows nothing about is left alone."""
        downloaded = (self.history.get(self.key) or {}).get("downloaded", {})
        found = set()
        for i, group in enumerate(groups):
            target = core.target_path(self.info.title, group, fmt, self.book_dir)
            if not target.exists():
                continue
            inside = [k for k in group_keys(group) if k in downloaded and Path(downloaded[k]) == target]
            if inside and len(inside) < len(group.chapters):
                found.add(i)
        return frozenset(found)

    def _on_status(self, row: int, state: str, frac: float, msg: str) -> None:
        bar = self._bar(row)
        bar.setValue(int(frac * 1000))
        if state == core.DOWNLOADING:
            bar.setFormat(f"{int(frac * 100)}%  ·  {msg}")
        elif state == core.BUILDING:
            bar.setFormat(msg + "…")
        else:
            bar.setFormat(state)
        bar.setToolTip(msg)
        if bar.property("state") != state:
            bar.setProperty("state", state)
            repolish(bar)
        if state == core.FAILED:
            bar.setValue(1000)
        self.fractions[row] = 1.0 if state in (core.DONE, core.SKIPPED, core.FAILED) else frac
        self.states[row] = state
        if state in (core.DONE, core.SKIPPED):
            self.history.file_done(self.key, group_keys(self.groups[row]), msg)
        elif state == core.FAILED:
            self.history.file_failed(self.key, group_keys(self.groups[row]))
        self.overall.setValue(int(self._overall() * 1000))

    def _overall(self) -> float:
        return sum(self.fractions.values()) / len(self.fractions) if self.fractions else 0.0

    def _refresh_run_status(self) -> None:
        """Percentage, files done and time left, refreshed every second while downloading."""
        if not self.running:
            return
        now, overall = time.monotonic(), self._overall()
        self.samples = [(t, v) for t, v in self.samples if now - t <= 30] + [(now, overall)]
        finished = sum(1 for st in self.states.values() if st in (core.DONE, core.SKIPPED, core.FAILED))
        detail = f"{finished} of {len(self.states)} files done  ·  {self._eta(now, overall)}"
        self._status(f"Downloading… {int(overall * 100)}%", detail)

    def _eta(self, now: float, overall: float) -> str:
        elapsed = now - self.run_t0
        if overall < 0.01 or elapsed < 4:
            return "working out the time left…"
        rate = overall / elapsed  # average since the start
        t_old, v_old = self.samples[0]
        if now - t_old >= 5 and overall > v_old:  # blend in the last 30 seconds, which reacts faster
            rate = (rate + (overall - v_old) / (now - t_old)) / 2
        return fmt_duration((1 - overall) / rate) + " left"

    def _on_finished(self, failed: list[int], cancelled: bool) -> None:
        self.running = False
        self.tick.stop()
        self.bar_cat.stop()
        self._set_locked(False)
        self.cancel_btn.hide()
        self.open_btn.show()
        self._update_summary()
        took = fmt_duration(time.monotonic() - self.run_t0, about=False)
        if cancelled:
            self._status("Cancelled", "Run it again with the same choices to resume")
        elif failed:
            self._status(f"{len(failed)} of {len(self.fractions)} files failed",
                         "Hover a bar for the reason, then run again to resume ✧")
        else:
            self.overall.setValue(1000)
            self._status("All done ♡", f"Took {took}  ·  {self.book_dir}")
            self.completed.emit(self.info.title, len(self.fractions), str(self.book_dir))

    def _cancel(self) -> None:
        self.cancel.set()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling…")

    def _open_folder(self) -> None:
        if self.book_dir and self.book_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.book_dir)))


# --------------------------------------------------------------------------- settings page


class SettingsPage(QWidget):
    changed = Signal(object)  # the settings as they were before saving

    def __init__(self, settings: Settings):
        super().__init__(objectName="page")
        self.settings = settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(32, 28, 32, 16)
        col.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        col.addWidget(label("Settings ✿", "h1"))

        look, ll = card()
        lform = form_layout()
        self.theme = combo_box()
        self.theme.addItem("Match my system", theme.SYSTEM)
        self.theme.addItem("Light", theme.LIGHT)
        self.theme.addItem("Dark", theme.DARK)
        lform.addRow("Theme", self.theme)
        ll.addLayout(lform)
        col.addWidget(look)

        box, bl = card()
        form = form_layout()
        self.source = combo_box()
        for site in core.SITES:
            self.source.addItem(site.name, site.name)
        form.addRow("Default source", with_hint(self.source, "Where the Download page searches first."))
        self.download_dir = QLineEdit()
        form.addRow("Default download folder", folder_row(self.download_dir, "Default download folder"))
        self.temp_dir = QLineEdit(placeholderText="Inside the download folder (.manga-tmp)")
        for edit in (self.download_dir, self.temp_dir):
            watch_folder(edit)
        form.addRow("Temp folder", with_hint(folder_row(self.temp_dir, "Temp folder"),
                                             "Pages are kept here while a file is being made."))
        self.keep_temp = QCheckBox("Keep temp files after a file is made")
        form.addRow("", self.keep_temp)
        self.fmt = combo_box()
        for key, name in FORMATS.items():
            self.fmt.addItem(name, key)
        form.addRow("Default format", self.fmt)
        self.per_file = spin(minimum=1, maximum=999)
        form.addRow("Chapters per file", with_hint(self.per_file, "Used when a site has no volume numbers for a title."))
        self.per_page = spin(minimum=5, maximum=500)
        form.addRow("Files per page", with_hint(self.per_page, "How many files the Download page lists at once."))
        bl.addLayout(form)
        col.addWidget(box)

        speed, sl = card()
        sl.addWidget(label("Speed", "h2"))
        sform = form_layout()
        self.workers = spin(minimum=1, maximum=os.cpu_count() or 1)
        sform.addRow("Files at once", with_hint(
            self.workers, "1 downloads one file at a time. More workers make several files in parallel: "
                          "downloads run on threads and building files uses separate CPU cores."))
        self.delay = spin(QDoubleSpinBox, minimum=0.1, maximum=5.0, singleStep=0.1, decimals=1, suffix=" s")
        self.mode = combo_box()
        self.mode.addItem("Threads (recommended)", core.THREADS)
        self.mode.addItem("Separate processes (CPU cores)", core.PROCESSES)
        sform.addRow("Run downloads on", with_hint(
            self.mode, "Downloading mostly waits on the network, which threads handle without the GIL "
                       "getting in the way, so processes rarely make it faster and start up slower. "
                       "Building files always uses separate cores either way."))
        sform.addRow("Delay between requests", with_hint(
            self.delay, "Shared by all workers, so adding workers never raises the request rate. "
                        "Sites ask for human browsing speed; going too low can get your IP blocked."))
        sl.addLayout(sform)
        col.addWidget(speed)

        where, wl = card()
        wl.addWidget(label("Settings file", "pathTitle"))
        prow = QHBoxLayout()
        path = label(str(Settings.path()), "pathChip")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        prow.addWidget(path, 1)
        show = set_icon(QPushButton(" Show in folder"), "folder")
        show.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Settings.path().parent))))
        prow.addWidget(show)
        wl.addLayout(prow)
        col.addWidget(where)

        if appmenu.available():  # only the Linux AppImage; Windows has its installer
            menu, ml = card()
            ml.addWidget(label("App menu", "pathTitle"))
            mrow = QHBoxLayout()
            self.menu_hint = label("", "hint", wrap=True)
            mrow.addWidget(self.menu_hint, 1)
            self.menu_btn = set_icon(QPushButton(), "heart")
            self.menu_btn.clicked.connect(self._toggle_menu)
            mrow.addWidget(self.menu_btn)
            ml.addLayout(mrow)
            col.addWidget(menu)
            self._sync_menu()

        row = QHBoxLayout()
        self.saved = QFrame(objectName="toast")
        tl = QHBoxLayout(self.saved)
        tl.setContentsMargins(12, 7, 16, 7)
        tl.setSpacing(8)
        self.toast_icon = QLabel()
        self.toast_text = label("", "toastText")
        tl.addWidget(self.toast_icon)
        tl.addWidget(self.toast_text)
        self.saved.hide()
        reset = set_icon(QPushButton(" Reset to defaults"), "refresh")
        reset.clicked.connect(lambda: self._show(Settings()))
        self.undo_btn = set_icon(QPushButton(" Undo"), "undo")
        self.undo_btn.setToolTip("Go back to the saved settings")
        self.undo_btn.clicked.connect(lambda: self._show(self.settings))
        self.save_btn = set_icon(QPushButton(" Save", objectName="primary"), "heart", "white")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.saved)
        row.addStretch(1)
        row.addWidget(reset)
        row.addWidget(self.undo_btn)
        row.addWidget(self.save_btn)
        col.addStretch(1)
        bottom = QWidget()
        bottom.setLayout(row)
        row.setContentsMargins(32, 4, 32, 22)  # stays in view while the page scrolls
        outer.addWidget(bottom)
        self._show(settings)
        # Save and Undo are only clickable while the form differs from what is saved.
        for w in (self.download_dir, self.temp_dir):
            w.textChanged.connect(self._update_dirty)
        for w in (self.theme, self.source, self.fmt, self.mode):
            w.currentIndexChanged.connect(self._update_dirty)
        for w in (self.per_file, self.per_page, self.workers, self.delay):
            w.valueChanged.connect(self._update_dirty)
        self.keep_temp.toggled.connect(self._update_dirty)
        self._update_dirty()

    def _sync_menu(self) -> None:
        state = appmenu.state()
        self.menu_btn.setEnabled(state != appmenu.THEIRS)
        if state == appmenu.OURS:
            swap_icon(self.menu_btn, "close")
            self.menu_btn.setText(" Remove Nyanga from your app menu")
            self.menu_hint.setText("Nyanga is in your app menu ✧")
        elif state == appmenu.THEIRS:
            swap_icon(self.menu_btn, "heart")
            self.menu_btn.setText(" Already in your app menu ✧")
            self.menu_hint.setText("Another app (like Gear Lever) added Nyanga to your menu, so it's all set.")
        else:
            swap_icon(self.menu_btn, "heart")
            self.menu_btn.setText(" Add Nyanga to your app menu")
            self.menu_hint.setText("Open Nyanga from your app menu like any other app, no need to find the file ♡")

    def _toggle_menu(self) -> None:
        try:
            if appmenu.state() == appmenu.OURS:
                appmenu.remove()
                self._toast("Taken out of your app menu")
            else:
                buffer = QBuffer()
                buffer.open(QBuffer.WriteOnly)
                theme.app_pixmap(256).save(buffer, "PNG")
                appmenu.add(bytes(buffer.data()))
                self._toast("Added to your app menu ✧")
        except OSError as e:
            self._toast(f"Could not change the app menu: {e}", error=True)
        self._sync_menu()

    def _show(self, s: Settings) -> None:
        self.download_dir.setText(s.download_dir)
        self.temp_dir.setText(s.temp_dir)
        self.keep_temp.setChecked(s.keep_temp)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(s.default_format)))
        self.per_file.setValue(s.chapters_per_file)
        self.per_page.setValue(s.files_per_page)
        self.workers.setValue(s.workers)
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.download_mode)))
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.source.setCurrentIndex(max(0, self.source.findData(s.default_source)))
        self.delay.setValue(s.request_delay)

    def _form(self) -> Settings:
        """The settings as currently entered in the form; the rest (like the results look) stay as saved."""
        return replace(
            self.settings,
            download_dir=self.download_dir.text().strip() or Settings().download_dir,
            temp_dir=self.temp_dir.text().strip(),
            workers=self.workers.value(),
            download_mode=self.mode.currentData(),
            request_delay=round(self.delay.value(), 1),
            default_format=self.fmt.currentData(),
            chapters_per_file=self.per_file.value(),
            files_per_page=self.per_page.value(),
            keep_temp=self.keep_temp.isChecked(),
            theme=self.theme.currentData(),
            default_source=self.source.currentData(),
        )

    def _toast(self, text: str, error: bool = False) -> None:
        self.toast_text.setText(text)
        color = theme.color(CURRENT["mode"], "error" if error else "accent_soft")
        self.toast_icon.setPixmap(theme.icon("cat", color).pixmap(22, 22))
        self.saved.setProperty("error", error)
        repolish(self.saved)
        self.saved.show()
        QTimer.singleShot(2500, self.saved.hide)

    def dirty(self) -> bool:
        return self._form() != self.settings

    def nag(self) -> None:
        self._toast("Save or undo your changes first ♡", error=True)

    def _update_dirty(self, *_) -> None:
        for b in (self.save_btn, self.undo_btn):
            b.setEnabled(self.dirty())

    def _save(self) -> None:
        for name, edit in (("Download folder", self.download_dir), ("Temp folder", self.temp_dir)):
            problem = folder_problem(edit.text())
            if problem:
                self._toast(f"{name}: {problem}", error=True)
                edit.setFocus()
                return
        old = Settings(**asdict(self.settings))
        # Update in place: the download page holds the same Settings object.
        for f in fields(Settings):
            setattr(self.settings, f.name, getattr(self._form(), f.name))
        try:
            self.settings.save()
            self._toast("Saved")
        except OSError as e:
            self._toast(f"Could not save: {e}", error=True)
        self._update_dirty()
        self.changed.emit(old)


# --------------------------------------------------------------------------- window


class LibraryBridge(QObject):
    checked = Signal(str, int, str, list)  # key, total chapters, status, chapter keys
    check_failed = Signal(str)
    checks_done = Signal()


class LibraryPage(QWidget):
    """Every manga downloaded so far, how complete it is, and buttons to carry on."""
    open_requested = Signal(str, str)  # url, action: "open", "continue" or "retry"

    def __init__(self, settings: Settings, history: History):
        super().__init__(objectName="page")
        self.settings = settings
        self.history = history
        self.busy = lambda key: False  # is this manga downloading right now? (set by MainWindow)
        self.cards: dict[str, dict] = {}
        self.checking = False
        self.bridge = LibraryBridge()
        self.bridge.checked.connect(self._on_checked)
        self.bridge.check_failed.connect(lambda key: self._set_checking(key, False))
        self.bridge.checks_done.connect(self._on_checks_done)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        body = QWidget()
        self.col = QVBoxLayout(body)
        self.col.setContentsMargins(32, 28, 32, 28)
        self.col.setSpacing(16)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self.head = head = QHBoxLayout()
        head.addWidget(label("Library ✧", "h1"))
        head.addStretch(1)
        self.check_cat = MiniCat(lambda: CURRENT["mode"])
        head.addWidget(self.check_cat)
        self.check_lbl = label("", "meta")
        head.addWidget(self.check_lbl)
        self.col.addLayout(head)

        self.empty, el = card()
        erow = QHBoxLayout()
        erow.addStretch(1)
        self.empty_cat = CatLoader(lambda: CURRENT["mode"], (140, 112))
        erow.addWidget(self.empty_cat)
        etext = QVBoxLayout()
        etext.addStretch(1)
        etext.addWidget(label("Nothing here yet", "h2"))
        etext.addWidget(label("Download a manga and it will show up here ✧", "hint"))
        etext.addStretch(1)
        erow.addLayout(etext)
        erow.addStretch(1)
        el.addLayout(erow)
        self.col.addWidget(self.empty)
        self.list = QVBoxLayout()
        self.list.setSpacing(16)
        self.col.addLayout(self.list)
        self.col.addStretch(1)

    def reserve_right(self, px: int) -> None:
        """Keeps the header clear of the update pill that floats over the top right."""
        self.head.setContentsMargins(0, 0, px, 0)

    def refresh(self) -> None:
        """Rebuild the cards from history, then look for new chapters in the background."""
        self.history.prune_missing()
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cards.clear()
        entries = self.history.entries()
        self.empty.setVisible(not entries)
        self.empty_cat.start() if not entries else self.empty_cat.stop()
        for key, entry in entries:
            self.list.addWidget(self._card(key, entry))
        self._check_for_new(entries)

    def _card(self, key: str, entry: dict) -> QFrame:
        frame, layout = card()
        row = QHBoxLayout()
        row.setSpacing(18)
        cover = QLabel()
        cover.setFixedSize(84, 120)
        path = self.history.cover_path(key)
        cover.setPixmap(rounded_pixmap(path.read_bytes() if path.exists() else None, 84, 120, 12))
        row.addWidget(cover, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(entry.get("title", key), "libTitle"))
        badge = label("", "newBadge")
        badge.hide()
        top.addWidget(badge)
        cat = MiniCat(lambda: CURRENT["mode"])
        top.addWidget(cat)
        top.addStretch(1)
        forget = set_icon(QPushButton(objectName="notifyClose"), "close", "muted", 14)
        forget.setToolTip("Remove from library (your downloaded files stay where they are)")
        forget.setCursor(Qt.PointingHandCursor)
        forget.clicked.connect(lambda: remove_from_library(self, self.history, key, self.busy(key)) and self.refresh())
        top.addWidget(forget)
        col.addLayout(top)

        bar = QProgressBar(objectName="libBar", maximum=1000)
        bar.setFixedHeight(18)
        col.addWidget(bar)
        meta = label("", "meta", wrap=True)
        col.addWidget(meta)
        when = label("", "hint")
        col.addWidget(when)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        pending, failed = entry.get("pending", []), entry.get("failed", [])
        url = entry.get("url", "")
        if pending:
            go = set_icon(QPushButton(" Continue", objectName="primary"), "download", "white")
            go.setToolTip(f"Download the {len(pending)} chapters that didn't finish last time")
            go.clicked.connect(lambda: self.open_requested.emit(url, "continue"))
            buttons.addWidget(go)
        if failed:
            retry = set_icon(QPushButton(" Retry failed"), "refresh")
            retry.setToolTip(f"Try the {len(failed)} chapters that failed again")
            retry.clicked.connect(lambda: self.open_requested.emit(url, "retry"))
            buttons.addWidget(retry)
        folder = self._folder(entry)
        folder_btn = set_icon(QPushButton(" Folder"), "folder")
        folder_btn.setEnabled(folder is not None)
        folder_btn.setToolTip(f"Show the files in {folder}" if folder else "Nothing downloaded yet ✧")
        folder_btn.clicked.connect(lambda: self._open_folder(key))
        buttons.addWidget(folder_btn)
        open_btn = set_icon(QPushButton(" Open"), "library")
        open_btn.setToolTip("Open it on the Download page to pick more chapters")
        open_btn.clicked.connect(lambda: self.open_requested.emit(url, "open"))
        buttons.addWidget(open_btn)
        col.addLayout(buttons)
        row.addLayout(col, 1)
        layout.addLayout(row)

        self.cards[key] = {"bar": bar, "meta": meta, "when": when, "badge": badge, "cat": cat}
        self._fill(key)
        return frame

    @staticmethod
    def _folder(entry: dict) -> Path | None:
        """Where this manga's files are: next to its downloaded files, else where the last download went."""
        folder = History.folder(entry)
        if folder is None and entry.get("last_run", {}).get("save_to"):
            folder = Path(entry["last_run"]["save_to"]).expanduser() / core.safe_name(entry.get("title", ""))
        return folder if folder and folder.is_dir() else None

    def _open_folder(self, key: str) -> None:
        folder = self._folder(self.history.get(key) or {})
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self.refresh()  # it was moved or deleted; the button turns grey

    def _fill(self, key: str) -> None:
        entry, w = self.history.get(key), self.cards.get(key)
        if not entry or not w:
            return
        pct = History.percent(entry)
        w["bar"].setValue(int(pct * 1000))
        w["bar"].setFormat(f"{pct * 100:.0f}%")
        parts = [f"{len(entry.get('downloaded', {}))} of {entry.get('total_chapters', '?')} chapters"]
        if entry.get("failed"):
            parts.append(f"{len(entry['failed'])} failed")
        if entry.get("pending"):
            parts.append(f"{len(entry['pending'])} waiting")
        if entry.get("status"):
            parts.append(entry["status"])
        w["meta"].setText("  ·  ".join(parts))
        w["when"].setText(f"Last download: {ago(entry.get('last_download'))}")
        new = entry.get("new_chapters", 0)
        w["badge"].setText(f"{new} new ✧")
        w["badge"].setVisible(bool(new))

    def _set_checking(self, key: str, on: bool) -> None:
        cat = self.cards.get(key, {}).get("cat")
        if cat:
            cat.start() if on else cat.stop()

    def _check_for_new(self, entries: list[tuple[str, dict]]) -> None:
        # Skip titles checked in the last few minutes, so flipping between pages doesn't hammer the site.
        due = [(k, e) for k, e in entries if time.time() - e.get("last_check", 0) > 300 and e.get("url")]
        if self.checking or not due:
            return
        self.checking = True
        for key, _ in due:
            self._set_checking(key, True)
        self.check_cat.start()
        self.check_lbl.setText("checking for new chapters…")
        limiter = core.RateLimiter(self.settings.request_delay)

        def work() -> None:
            for key, entry in due:
                site_cls = core.site_for(entry["url"])
                try:
                    info = site_cls(entry["url"], limiter).info(with_cover=False)
                    keys = [chapter_key(c.number) for c in info.chapters]
                    self.bridge.checked.emit(key, len(keys), info.status, keys)
                except Exception:
                    self.bridge.check_failed.emit(key)
            self.bridge.checks_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, key: str, total: int, status: str, keys: list) -> None:
        if self.history.get(key):
            self.history.checked(key, total, status, keys)
        self._set_checking(key, False)
        self._fill(key)

    def _on_checks_done(self) -> None:
        self.checking = False
        self.check_cat.stop()
        self.check_lbl.setText("")


class Notification(QWidget):
    """A card that fades in at the bottom right with a happy cat: a download is finished, or an update is out."""
    update_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.folder = ""
        self.sticky = False
        self.showing_update = False  # the update card is up (or fading in)
        self.fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)  # room for the shadow
        self.box = box = QFrame(objectName="notify")
        shadow = QGraphicsDropShadowEffect(blurRadius=34, xOffset=0, yOffset=8)
        shadow.setColor(QColor(255, 92, 154, 70))
        box.setGraphicsEffect(shadow)
        outer.addWidget(box)

        row = QHBoxLayout(box)
        row.setContentsMargins(16, 14, 12, 16)
        row.setSpacing(12)
        self.cat = CatLoader(lambda: CURRENT["mode"], (112, 90), celebrate=True)
        row.addWidget(self.cat, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(6)
        head = QHBoxLayout()
        self.title = label("", "notifyTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        close = set_icon(QPushButton(objectName="notifyClose"), "close", "muted", 14)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        head.addWidget(close)
        col.addLayout(head)
        self.body = label("", "notifyBody", wrap=True)
        self.body.setOpenExternalLinks(True)
        self.body.setAlignment(Qt.AlignLeft | Qt.AlignTop)  # spare height (the cat is taller) goes below
        col.addWidget(self.body)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_btn = set_icon(QPushButton(" Open folder"), "folder")
        self.open_btn.clicked.connect(self._open)
        buttons.addWidget(self.open_btn)
        self.later_btn = QPushButton("Later")
        self.later_btn.clicked.connect(self.dismiss)
        buttons.addWidget(self.later_btn)
        self.update_btn = set_icon(QPushButton(" Update now", objectName="primary"), "download", "white")
        self.update_btn.clicked.connect(self.update_requested)
        buttons.addWidget(self.update_btn)
        col.addSpacing(4)
        col.addLayout(buttons)
        col.addStretch(1)
        row.addLayout(col, 1)

        self.setFixedWidth(460)
        self.anim = QPropertyAnimation(self.fade, b"opacity", self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self._faded)
        self.timer = QTimer(self, singleShot=True, interval=10_000)
        self.timer.timeout.connect(self.dismiss)
        self.hide()

    def popup(self, title: str, files: int, folder: str) -> None:
        self.folder = folder
        self._show("Yay, it's ready!", f"<b>{html.escape(title)}</b> is all downloaded! "
                   f"{files} {'file is' if files == 1 else 'files are'} waiting for you. Happy reading ✧",
                   update=False)
        self.timer.start()

    def offer_update(self, version: str) -> None:
        """Stays until Later or Update now is pressed."""
        self._show("A new version is out!", f"Version <b>{html.escape(version)}</b> is ready (you have "
                   f"{html.escape(__version__)}). Updating takes a moment and keeps your settings and library ✧",
                   update=True)
        self.timer.stop()

    def update_status(self, text: str, busy: bool = True) -> None:
        """Works while the card is closed too, so it's right when it comes back."""
        self.body.setText(text)
        self.busy = busy
        if self.sticky:
            self.later_btn.setVisible(not busy)
            self.update_btn.setVisible(not busy)
        self._fit()

    def show_update(self) -> None:
        """Brings the update card back as it was, e.g. with the progress of a running update."""
        self._show(self.title.text() if self.sticky else "A new version is out!", None, update=True)
        self.later_btn.setVisible(not self.busy)
        self.update_btn.setVisible(not self.busy)
        self._fit()

    def _show(self, title: str, body: str | None, update: bool) -> None:
        self.sticky = update
        self.showing_update = update
        self.busy = False if body is not None else getattr(self, "busy", False)
        self.title.setText(title)
        if body is not None:
            self.body.setText(body)
        self.open_btn.setVisible(not update)
        self.later_btn.setVisible(update)
        self.update_btn.setVisible(update)
        was_visible = self.isVisible() and self.anim.endValue() == 1
        if not was_visible:
            self.fade.setOpacity(0.0)
        self.show()
        self._fit()  # after show(): a hidden card's label has no real width to wrap at
        self.raise_()
        self.cat.start()
        if not was_visible:
            self._fade(1.0)

    def _fit(self) -> None:
        """Exactly as tall as the wrapped text; Qt guesses a wrapped label's height at the wrong width."""
        self.body.setMinimumHeight(0)
        self.body.setMaximumHeight(16777215)
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)  # buttons just shown or hidden
        self.adjustSize()
        self.layout().activate()  # gives the body label its real width
        self.body.setFixedHeight(self.body.heightForWidth(self.body.width()))
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        self.resize(self.width(), self.sizeHint().height())
        self.reposition()

    def dismiss(self) -> None:
        self.timer.stop()
        self.showing_update = False
        self._fade(0.0)
        self.dismissed.emit()

    def _fade(self, to: float) -> None:
        self.anim.stop()
        self.anim.setDuration(350 if to else 250)
        self.anim.setStartValue(self.fade.opacity() if self.isVisible() and to == 0 else 0.0)
        self.anim.setEndValue(to)
        self.anim.start()

    def _faded(self) -> None:
        if self.anim.endValue() == 0:  # finished fading out
            self.cat.stop()
            self.hide()

    def _open(self) -> None:
        if self.folder and Path(self.folder).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))
        self.dismiss()

    def reposition(self) -> None:
        parent = self.parentWidget()
        self.move(parent.width() - self.width() - 12, parent.height() - self.height() - 96)

    # Hovering keeps it open; it goes away a few seconds after the mouse leaves.
    def enterEvent(self, event) -> None:
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self.isVisible() and not self.sticky:
            self.timer.start(4000)
        super().leaveEvent(event)


class WhatsNew(QDialog):
    """The changes in one or more releases, in plain words, grouped into new things, fixes and so on."""

    SECTIONS = {"breaking": "Heads up: this works a bit differently", "feat": "✧  New things",
                "fix": "♡  Fixed", "perf": "✿  Faster"}

    def __init__(self, parent: QWidget, releases: list[dict], subtitle: str):
        super().__init__(parent, objectName="whatsNew")
        self.setWindowTitle("What's new")
        self.setFixedWidth(580)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(6)
        self.cat = CatLoader(lambda: CURRENT["mode"], (100, 80), celebrate=True)
        outer.addWidget(self.cat, 0, Qt.AlignHCenter)
        self.cat.start()  # only once it's in the dialog, or it pops up as a window of its own
        outer.addWidget(label("What's new ✧", "h1"), 0, Qt.AlignHCenter)
        sub = label(subtitle, "hint", wrap=True)
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)
        outer.addSpacing(10)

        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(8)
        for release in releases:
            if len(releases) > 1:
                day = self._day(release)
                col.addSpacing(6)
                col.addWidget(label(f"Version {release['version']}  ·  {day:%B} {day.day}, {day.year}", "h2"))
            kind = None
            for item in release["items"]:
                if item["kind"] != kind:
                    kind = item["kind"]
                    col.addSpacing(4)
                    col.addWidget(label(self.SECTIONS.get(kind, "Other changes"), "noteSection"))
                col.addWidget(self._item(item))
        col.addStretch(1)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        outer.addSpacing(10)
        ok = QPushButton("Got it ♡", objectName="primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        outer.addWidget(ok, 0, Qt.AlignHCenter)
        # Work out the size once and lock it: with wrapped text the window's height depends on its
        # width, and on scaled Windows displays it kept resizing itself (see-through and jumpy)
        # before settling.
        self.ensurePolished()
        margins = outer.contentsMargins()
        room = self.width() - margins.left() - margins.right() - scroll.verticalScrollBar().sizeHint().width()
        fill = body.heightForWidth(room) if body.hasHeightForWidth() else body.sizeHint().height()
        rest = self.sizeHint().height() - scroll.sizeHint().height()  # cat, titles, button, spacing
        self.setFixedSize(self.width(), min(rest + fill, 680))

    @staticmethod
    def _day(release: dict) -> date:
        """The release's date where this computer is (`time` is UTC; older notes only have `date`)."""
        if "time" in release:
            return datetime.fromisoformat(release["time"].replace("Z", "+00:00")).astimezone().date()
        return date.fromisoformat(release["date"])

    @staticmethod
    def _item(item: dict) -> QFrame:
        frame = QFrame(objectName="noteItem")
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 10, 14, 11)
        box.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = label(item["title"], "noteTitle", wrap=True)
        top.addWidget(title, 1)
        if item["area"]:
            top.addWidget(label(item["area"], "chip"), 0, Qt.AlignTop)
        box.addLayout(top)
        detail = label(item["detail"], "noteDetail", wrap=True)
        box.addWidget(detail)
        detail.setVisible(bool(item["detail"]))  # after it's in the card, or it flashes up as its own window
        for w in (title, detail):
            w.setTextFormat(Qt.PlainText)  # commit text, not markup
        return frame


class MascotLogo(QWidget):
    """The sidebar cat. Click it and it hops, squishing a little when it takes off and lands."""
    clicked = Signal()
    SIZE = 48
    HOP = 10  # room above the cat for the hop

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.SIZE + 8, self.SIZE + self.HOP)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Boop ♡")
        self.pixmap = theme.app_pixmap(96)
        self.t = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=650)
        self.anim.valueChanged.connect(self._step)

    def _step(self, t: float) -> None:
        self.t = t
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.anim.stop()
            self.anim.start()
            self.clicked.emit()

    def paintEvent(self, event) -> None:
        t = self.t if self.anim.state() == QVariantAnimation.Running else 0.0
        lift = math.sin(math.pi * min(1.0, t / 0.8)) * self.HOP  # up and back down in the first 80%
        squish = 0.0
        if t < 0.15:  # crouch before jumping
            squish = math.sin(math.pi * t / 0.15) * 0.12
        elif t > 0.8:  # land
            squish = math.sin(math.pi * (t - 0.8) / 0.2) * 0.14
        wiggle = math.sin(2 * math.pi * t * 2) * 7 * (1 - t)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        base = QRectF(4, self.HOP, self.SIZE, self.SIZE)
        p.translate(base.center().x(), base.bottom() - lift)  # squish and tilt around the cat's feet
        p.rotate(wiggle)
        p.scale(1 + squish, 1 - squish)
        p.drawPixmap(QRectF(-self.SIZE / 2, -self.SIZE, self.SIZE, self.SIZE), self.pixmap, QRectF(self.pixmap.rect()))
        p.end()


class UpdatePill(QFrame):
    """Top right: an update that was put off (press to update), or one on its way while its card is closed."""
    clicked = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, objectName="updatePill")
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        shadow = QGraphicsDropShadowEffect(blurRadius=22, xOffset=0, yOffset=4)
        shadow.setColor(QColor(255, 92, 154, 70))
        self.setGraphicsEffect(shadow)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 2, 18, 2)
        row.setSpacing(6)
        self.icon = QLabel()
        row.addWidget(self.icon)
        self.cat = MiniCat(lambda: CURRENT["mode"], (40, 34), painter=paint_update_cat)
        row.addWidget(self.cat)
        self.text = label("", "updatePillText")
        row.addWidget(self.text)
        self.setFixedHeight(42)
        self.busy = False
        self.widest = ""
        self.hide()

    def set_state(self, text: str, busy: bool, widest: str = "") -> None:
        """`widest` is the longest text this state will show, so the pill doesn't wobble as numbers grow."""
        self.busy = busy
        self.widest = widest
        self.setProperty("busy", busy)
        repolish(self)
        repolish(self.text)
        self.text.setText(text)
        self.text.setMinimumWidth(self.text.fontMetrics().horizontalAdvance(widest) if widest else 0)
        self.icon.setVisible(not busy)
        if busy:
            self.cat.start()
        else:
            self.cat.stop()
        self.refresh_icon()
        self.adjustSize()

    def refresh_icon(self) -> None:
        self.icon.setPixmap(theme.icon("download", QColor("#ffffff")).pixmap(18, 18))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class UpdateBridge(QObject):
    """Carries update checks and the installer download back to the GUI thread."""
    found = Signal(object)  # updater.Release
    progress = Signal(int, int)  # bytes done, total
    ready = Signal(object)  # installer path
    failed = Signal(str)


class WheelGuard(QObject):
    """Scrolling over a dropdown or number box scrolls the page instead of changing the value."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            parent = obj.parentWidget()
            while parent and not isinstance(parent, QAbstractScrollArea):
                parent = parent.parentWidget()
            if parent:
                QApplication.sendEvent(parent.viewport(), event)
            return True
        return False


class RoundPopups(QObject):
    """Dropdown lists are drawn with rounded corners, but their popup window is square. On Windows
    its square shadow showed in the corners, and see-through windows need to be frameless there.
    So: no shadow, frameless and see-through, and cut to the same rounded shape."""
    RADIUS = 14  # the list's border-radius in theme.py

    def eventFilter(self, obj, event) -> bool:
        if not obj.isWidgetType() or not obj.inherits("QComboBoxPrivateContainer"):
            return False
        if event.type() == QEvent.Polish:  # before its window exists
            obj.setWindowFlags(obj.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            obj.setAttribute(Qt.WA_TranslucentBackground)
        elif event.type() in (QEvent.Show, QEvent.Resize):
            path = QPainterPath()
            path.addRoundedRect(QRectF(obj.rect()), self.RADIUS, self.RADIUS)
            obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
        return False


class MainWindow(QWidget):
    UPDATE_CHECK_MS = 6 * 60 * 60 * 1000

    def __init__(self):
        super().__init__(objectName="root")
        self.wheel_guard = WheelGuard(self)
        QApplication.instance().installEventFilter(self.wheel_guard)
        self.round_popups = RoundPopups(self)
        QApplication.instance().installEventFilter(self.round_popups)
        self.setWindowTitle("Nyanga")
        self.setWindowIcon(theme.app_icon())
        self.resize(1120, 840)
        had_data = Settings.path().exists() or (paths.DATA / "library").exists()  # before this run makes any
        self.settings = Settings.load()
        CURRENT["mode"] = self._resolve(self.settings.theme)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        side = QFrame(objectName="sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 26 - MascotLogo.HOP, 18, 18)  # the cat keeps room above it to hop into
        sl.setSpacing(6)
        brand = QHBoxLayout()
        brand.setSpacing(6)  # 10, less the room the cat keeps beside it to wiggle
        mascot = MascotLogo()
        mascot.clicked.connect(self._mascot_clicked)
        brand.addWidget(mascot, 0, Qt.AlignBottom)
        logo = label("Nyanga", "logo")
        logo.setFixedHeight(MascotLogo.SIZE)  # centred on the cat, not on the room it hops into
        brand.addWidget(logo, 0, Qt.AlignBottom)
        brand.addStretch(1)
        sl.addLayout(brand)
        sl.addSpacing(4)
        self.tagline = label("cute & cozy ✧", "tagline")
        sl.addWidget(self.tagline)
        self.tagline_reset = QTimer(self, singleShot=True, interval=1800)
        self.tagline_reset.timeout.connect(lambda: self.tagline.setText("cute & cozy ✧"))
        sl.addSpacing(22)
        self.stack = QStackedWidget()
        self.history = History()
        self.download = DownloadPage(self.settings, self.history)
        self.library = LibraryPage(self.settings, self.history)
        self.library.busy = lambda key: self.download.running and self.download.key == key
        self.library.open_requested.connect(self._open_from_library)
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.changed.connect(self._settings_saved)
        for page in (self.download, self.library, self.settings_page):
            self.stack.addWidget(page)
        nav = QButtonGroup(self)
        self.nav_buttons = []
        for i, (text, icon_name) in enumerate([("  Download", "download"), ("  Library", "library"),
                                               ("  Settings", "settings")]):
            b = set_icon(QPushButton(text, objectName="nav", checkable=True), icon_name, "side_text", 20)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_page(i))
            nav.addButton(b)
            self.nav_buttons.append(b)
            sl.addWidget(b)
            if i == 0:
                b.setChecked(True)
        sl.addStretch(1)
        sites = QFrame(objectName="sitesBox")
        sbox = QVBoxLayout(sites)
        sbox.setContentsMargins(12, 10, 12, 12)
        sbox.setSpacing(6)
        sbox.addWidget(label("SUPPORTED SITES", "sitesTitle"))
        for site in core.SITES:
            pill = QPushButton(f"♥  {site.name}", objectName="sitePill")
            pill.setCursor(Qt.PointingHandCursor)
            pill.setToolTip(f"Open {site.name} in your browser")
            pill.clicked.connect(lambda _=False, url=site.home: QDesktopServices.openUrl(QUrl(url)))
            sbox.addWidget(pill)
        sl.addWidget(sites)
        sl.addSpacing(6)
        self.toggle = QPushButton(objectName="themeToggle")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setIconSize(QSize(18, 18))
        self.toggle.clicked.connect(self._toggle_theme)
        sl.addWidget(self.toggle)
        sl.addSpacing(10)
        if greeted():
            sl.addWidget(label("HI LIL GOMIEE!!", "greeting"))
        version = QPushButton(f"version {__version__}", objectName="version")
        version.setCursor(Qt.PointingHandCursor)
        version.setToolTip("What's new in this version ✧")
        version.clicked.connect(self._show_all_notes)
        sl.addWidget(version, 0, Qt.AlignLeft)

        layout.addWidget(side)
        layout.addWidget(self.stack, 1)

        self.notification = Notification(self)
        self.download.completed.connect(self.notification.popup)

        # Look for a new version a moment after opening, then every few hours.
        self.release: updater.Release | None = None
        self.offered = ""
        self.update_state = ""  # "", "available", "updating" or "failed"
        self.pill = UpdatePill(self)
        self.pill.clicked.connect(self._pill_clicked)
        self.notification.dismissed.connect(self._sync_pill)
        self.download.completed.connect(lambda *_: self._sync_pill())
        self.updates = UpdateBridge()
        self.updates.found.connect(self._update_found)
        self.updates.progress.connect(self._update_progress)
        self.updates.ready.connect(self._update_ready)
        self.updates.failed.connect(self._update_failed)
        self.notification.update_requested.connect(self._start_update)
        if updater.can_install():
            QTimer.singleShot(3000, lambda: self.check_updates(first=True))
            self.update_timer = QTimer(self, interval=self.UPDATE_CHECK_MS)
            self.update_timer.timeout.connect(self.check_updates)
            self.update_timer.start()

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):  # Qt 6.5+: follow the system switching light/dark
            hints.colorSchemeChanged.connect(lambda *_: self.apply_theme(self.settings.theme))
        self.apply_theme(self.settings.theme)
        QTimer.singleShot(500, lambda: self._greet_update(had_data))

    def _greet_update(self, had_data: bool) -> None:
        """After an update, shows once what changed since the version last opened."""
        seen = self.settings.seen_version
        if not any(updater.parse(__version__)) or seen == __version__:
            return  # running from source, or nothing new since last time
        if seen:
            releases = updater.notes_since(seen)
        else:  # first open of a fresh install (nothing to show), or an update from before this screen existed
            releases = [r for r in updater.notes_since("0.0.0") if r["version"] == __version__] if had_data else []
        self.settings.seen_version = __version__
        try:
            self.settings.save()
        except OSError:
            pass  # shows again next time, no harm
        if releases:
            WhatsNew(self, releases, f"Nyanga just updated to version {__version__}. Here's what changed ♡").exec()

    def _show_all_notes(self) -> None:
        releases = updater.notes_since("0.0.0")
        if not releases:  # running from source: nothing bundled, so show the changelog online
            QDesktopServices.openUrl(QUrl(updater.notes_url()))
            return
        WhatsNew(self, releases, f"You're on version {__version__}. Every update so far, newest first ♡").exec()

    @staticmethod
    def _resolve(choice: str) -> str:
        if choice in (theme.LIGHT, theme.DARK):
            return choice
        hints = QGuiApplication.styleHints()
        dark = hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark
        return theme.DARK if dark else theme.LIGHT

    def apply_theme(self, choice: str) -> None:
        mode = self._resolve(choice)
        CURRENT["mode"] = mode
        QApplication.instance().setStyleSheet(theme.stylesheet(mode))
        for button, name, key in _ICON_BUTTONS:
            _paint_icon(button, name, key)
        for frame in self.findChildren(QFrame, "card"):
            if frame.graphicsEffect():
                frame.graphicsEffect().setColor(theme.color(mode, "shadow"))
        if hasattr(self, "pill"):
            self.pill.set_state(self.pill.text.text(), self.pill.busy, self.pill.widest)  # re-measure in the new style
            self._place_pill()
        dark = mode == theme.DARK
        self.toggle.setText("  Light mode" if dark else "  Dark mode")
        self.toggle.setIcon(theme.icon("sun" if dark else "moon", theme.color(mode, "side_text")))
        self.download.refresh_cover()

    def _toggle_theme(self) -> None:
        self.settings.theme = theme.LIGHT if CURRENT["mode"] == theme.DARK else theme.DARK
        self.settings_page.theme.setCurrentIndex(self.settings_page.theme.findData(self.settings.theme))
        try:
            self.settings.save()
        except OSError:
            pass  # the toggle still works for this session
        self.settings_page._update_dirty()
        self.apply_theme(self.settings.theme)

    MEOWS = ["nya~ ♡", "mrrp! ✧", "purr purr ♡", "meow? ✿", "*happy tail swish* ✧", "nyaa~ ✿"]

    def _mascot_clicked(self) -> None:
        options = [m for m in self.MEOWS if m != self.tagline.text()]
        self.tagline.setText(random.choice(options))
        self.tagline_reset.start()

    def _settings_saved(self, old: Settings) -> None:
        self.apply_theme(self.settings.theme)
        self.download.apply_defaults(old)

    def show_page(self, index: int) -> None:
        if self.stack.currentWidget() is self.settings_page and index != 2 and self.settings_page.dirty():
            self.nav_buttons[2].setChecked(True)  # stay until the changes are saved or undone
            self.settings_page.nag()
            return
        self.nav_buttons[index].setChecked(True)
        self.stack.setCurrentIndex(index)
        if self.stack.currentWidget() is self.library:
            self.library.refresh()
        elif self.stack.currentWidget() is self.download:
            self.download.sync_library_btn()  # it may have been removed on the Library page

    def _open_from_library(self, url: str, action: str) -> None:
        if self.download.running:
            self.download._status("A download is still running", "Wait for it to finish, then try again ✧")
        else:
            self.download.open_manga(url, action)
        self.show_page(0)

    # ----------------------------------------------------------------------- updates

    def check_updates(self, first: bool = False) -> None:
        def work():
            try:
                if first:
                    updater.cleanup()
                release = updater.latest()
            except (requests.RequestException, ValueError, KeyError):
                return  # offline or GitHub is busy; try again at the next check
            if release and updater.is_newer(release):
                self.updates.found.emit(release)

        threading.Thread(target=work, daemon=True).start()

    def _update_found(self, release: updater.Release) -> None:
        if self.update_state in ("updating", "ready"):
            return
        self.release = release
        self._set_update_state("available", f"Update to {release.version} · {fmt_size(release.size)}")
        if release.version != self.offered:  # don't nag again about one that was put off
            self.offered = release.version
            self.notification.offer_update(release.version)
        self._sync_pill()

    def _set_update_state(self, state: str, pill_text: str) -> None:
        self.update_state = state
        self.pill.set_state(pill_text, busy=state == "updating")
        self._sync_pill()

    def _sync_pill(self) -> None:
        """The pill stands in for the update card whenever the card isn't up."""
        show = bool(self.update_state) and not self.notification.showing_update
        self.pill.setVisible(show)
        if show:
            self.pill.raise_()
            self._place_pill()
        self.library.reserve_right(self.pill.width() + 12 if show else 0)

    def _place_pill(self) -> None:
        self.pill.adjustSize()
        self.pill.move(self.width() - self.pill.width() - 30, 24)

    def _pill_clicked(self) -> None:
        if self.update_state == "updating":
            self.notification.show_update()
            self._sync_pill()
        elif self.update_state == "ready":
            if self.download.running:
                self.notification.show_update()
                self._sync_pill()
            else:
                self._update_ready(self.installer)
        else:
            self._start_update()

    def _start_update(self) -> None:
        if self.update_state == "updating" or self.release is None:
            return
        if self.download.running:
            self.notification.show_update()
            self.notification.update_status("A download is still going. Update once it's finished ✧", busy=False)
            self._sync_pill()
            return
        self._set_update_state("updating", "Updating…")
        self.notification.update_status("Getting the update…")
        release = self.release

        def work():
            try:
                self.updates.ready.emit(updater.download(release, self.updates.progress.emit))
            except (requests.RequestException, OSError) as e:
                self.updates.failed.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def _update_progress(self, done: int, total: int) -> None:
        percent = done * 100 // max(total, 1)
        self.notification.update_status(f"Getting the update… {percent}% ({fmt_size(done)} of {fmt_size(total)})")
        self.pill.set_state(f"Updating… {percent}% · {fmt_size(done)} of {fmt_size(total)}", busy=True,
                            widest=f"Updating… 100% · {fmt_size(total)} of {fmt_size(total)}")
        self._place_pill()

    def _update_ready(self, installer: Path) -> None:
        if self.download.running:  # don't close the app under a download; install when they're ready
            self.installer = installer
            self._set_update_state("ready", "Install update")
            self.notification.update_status("The update is ready! Press Install update at the top right "
                                            "once your download is done ✧", busy=False)
            return
        try:
            updater.install(installer)
        except OSError as e:
            self._update_failed(str(e))
            return
        self.notification.update_status("Installing! The app reopens by itself in a few seconds ✧")
        self.pill.set_state("Installing…", busy=True)
        self._place_pill()
        QTimer.singleShot(800, QApplication.instance().quit)

    def _update_failed(self, message: str) -> None:
        self._set_update_state("failed", "Update didn't work · try again")
        self.notification.update_status(
            f"The update didn't work ({html.escape(message)}). Try again, or get it from "
            f'<a href="{updater.RELEASES_PAGE}">GitHub</a>.', busy=False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "notification"):
            self.notification.reposition()
        if hasattr(self, "pill"):
            self._place_pill()

    def closeEvent(self, event) -> None:
        # Let running workers stop after their current page instead of leaving half-written files.
        self.download.cancel.set()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("nyanga")
    app.setApplicationDisplayName("Nyanga")
    appmenu.follow()
    if desktop_id := appmenu.desktop_id():  # lets Linux docks match the window to its menu entry and icon
        app.setDesktopFileName(desktop_id)
    app.setFont(theme.load_font())
    app.setWindowIcon(theme.app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
