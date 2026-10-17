"""The pink Qt window: Download, Library and Settings pages, and the update check."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import requests
from PySide6.QtCore import QCoreApplication, QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QStyledItemDelegate, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QGridLayout, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

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


def _paint_icon(button: QPushButton, name: str, color_key: str) -> None:
    color = "#ffffff" if color_key == "white" else theme.color(CURRENT["mode"], color_key)
    button.setIcon(theme.icon(name, color))


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

    @staticmethod
    def path() -> Path:
        return paths.DATA / "settings.json"  # next to the script (git-ignored), or %APPDATA% in the exe

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
    searched = Signal(int, object, str, list)  # search id, site class, query, SearchResults
    search_failed = Signal(int, str)
    cover_ready = Signal(int, int, object)  # search id, result index, image bytes (or None)
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
        p.setFont(QFont(p.font().family(), 40))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "♡")
    p.end()
    return out


def spin(cls=QSpinBox, **kw):
    box = cls(**kw)
    box.lineEdit().setTextMargins(6, 0, 0, 0)  # match the padding of the line edits
    return box


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

    def __init__(self, result: core.SearchResult):
        super().__init__(objectName="result")
        self.result = result
        self.data: bytes | None = None
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 14, 10)
        row.setSpacing(14)
        self.cover = QLabel()
        self.cover.setFixedSize(54, 76)
        self.set_cover(None)
        row.addWidget(self.cover, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(result.title, "resultTitle", wrap=True))
        meta = "  ·  ".join(x for x in (result.status, result.latest) if x)
        if meta:
            text.addWidget(label(meta, "meta", wrap=True))
        if result.author:
            text.addWidget(label(f"by {result.author}", "hint", wrap=True))
        text.addStretch(1)
        row.addLayout(text, 1)

    def set_cover(self, data: bytes | None) -> None:
        self.data = data
        self.cover.setPixmap(rounded_pixmap(data, 54, 76, 10))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


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
        font = QFont(self.font())
        font.setWeight(QFont.DemiBold)  # as styled in theme.py
        width = QFontMetrics(font).horizontalAdvance(text)
        if align & Qt.AlignRight:  # 9 and 10: the section padding in theme.py
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
        self.search_id = 0  # results of older searches are ignored
        self.results: list[ResultItem] = []
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
        self.source.currentIndexChanged.connect(lambda *_: self._hint(self._idle_hint()))
        self.query = QLineEdit(placeholderText="Type a manga name, like One Piece ✧")
        self.query.returnPressed.connect(self._find)
        self.fetch_btn = set_icon(QPushButton(" Search", objectName="primary"), "search", "white")
        self.fetch_btn.clicked.connect(self._find)
        row.addWidget(self.source)
        row.addWidget(self.query, 1)
        row.addWidget(self.fetch_btn)
        fl.addLayout(row)
        hint_row = QHBoxLayout()
        self.find_hint = label(self._idle_hint(), "hint", wrap=True)
        hint_row.addWidget(self.find_hint, 1)
        self.back_btn = set_icon(QPushButton(" Back to results"), "list")
        self.back_btn.clicked.connect(self._show_results)
        self.back_btn.hide()
        hint_row.addWidget(self.back_btn)
        fl.addLayout(hint_row)
        col.addWidget(find)

        # search results
        self.results_card, rl = card()
        rhead = QHBoxLayout()
        rhead.addWidget(label("Pick one ✧", "h2"))
        rhead.addStretch(1)
        self.results_count = label("", "meta")
        rhead.addWidget(self.results_count)
        rl.addLayout(rhead)
        self.results_grid = QGridLayout()
        self.results_grid.setHorizontalSpacing(12)
        self.results_grid.setVerticalSpacing(12)
        self.results_grid.setColumnStretch(0, 1)
        self.results_grid.setColumnStretch(1, 1)
        rl.addLayout(self.results_grid)
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
        self.cover.setFixedSize(132, 188)
        top.addWidget(self.cover, 0, Qt.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(8)
        self.title_lbl = label("", "mangaTitle", wrap=True)
        self.meta_lbl = label("", "meta", wrap=True)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        right.addWidget(self.title_lbl)
        right.addWidget(self.meta_lbl)
        right.addLayout(self.chips)
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
        form.addRow("Save to", folder_row(self.save_to, "Download folder"))
        right.addLayout(form)
        self.loose_note = label("", "hint", wrap=True)
        right.addWidget(self.loose_note)
        right.addStretch(1)
        top.addLayout(right, 1)
        ml.addLayout(top)
        self.manga_card.hide()
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
        self.table.setHorizontalHeaderLabels(["", "File", "Chapters", "Count", "Size", "Progress"])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = self.table.horizontalHeader()
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
        picks = QHBoxLayout()
        self.all_btn = set_icon(QPushButton(" Select all"), "heart")
        self.all_btn.clicked.connect(lambda: self._check(lambda i: True))
        self.none_btn = set_icon(QPushButton(" Select none"), "select_none")
        self.none_btn.clicked.connect(lambda: self._check(lambda i: False))
        self.first_n = spin(minimum=1, maximum=1, prefix="First ")
        self.first_btn = set_icon(QPushButton(" Select"), "list")
        self.first_btn.clicked.connect(lambda: self._check(lambda i: i < self.first_n.value()))
        for w in (self.all_btn, self.none_btn):
            picks.addWidget(w)
        picks.addStretch(1)
        picks.addWidget(self.first_n)
        picks.addWidget(self.first_btn)
        tl.addLayout(picks)
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
        return f"Searching {self.source.currentData()}. A link to a title works too ✧"

    def _start_lookup(self, title: str, text: str) -> None:
        self.lookup_title.setText(title)
        self.lookup_text.setText(text)
        self.fetch_btn.setEnabled(False)
        self.results_card.hide()
        self.back_btn.hide()
        self.lookup_card.show()
        self.lookup_cat.start()

    def _find(self) -> None:
        text = self.query.text().strip()
        if not text:
            self._hint("Type a manga name first ♡", error=True)
            return
        if core.site_for(text):
            self._fetch(text)
            return
        if re.match(r"https?://", text):
            self._hint("That isn't a title link from a supported site: "
                       + ", ".join(s.example for s in core.SITES), error=True)
            return
        site_cls = core.site_named(self.source.currentData())
        self.search_id += 1
        sid = self.search_id
        self._hint(f"Searching {site_cls.name}…")
        self._start_lookup("Searching…", f"Asking {site_cls.name} for matches ✧")
        limiter = core.RateLimiter(self.settings.request_delay)

        def work() -> None:
            try:
                self.bridge.searched.emit(sid, site_cls, text, site_cls.search(text, limiter))
            except Exception as e:
                self.bridge.search_failed.emit(sid, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_search_failed(self, sid: int, message: str) -> None:
        if sid == self.search_id:
            self._on_fetch_failed(message)

    def _on_searched(self, sid: int, site_cls, query: str, results: list) -> None:
        if sid != self.search_id:
            return
        self._end_lookup()
        self.fetch_btn.setEnabled(True)
        for item in self.results:
            item.deleteLater()
        self.results = []
        if not results:
            self._hint(f"Nothing called “{query}” on {site_cls.name}. Try another spelling ✧", error=True)
            return
        self._hint(f"Found {len(results)} on {site_cls.name}. Pick the one you want ♡")
        self.results_count.setText(f"{len(results)} {'match' if len(results) == 1 else 'matches'}")
        for i, result in enumerate(results):
            item = ResultItem(result)
            item.clicked.connect(lambda r=result: self._pick(r))
            self.results_grid.addWidget(item, i // 2, i % 2)
            self.results.append(item)
        self.manga_card.hide()
        self.files_card.hide()
        self.results_card.show()
        limiter = core.RateLimiter(self.settings.request_delay)

        def covers() -> None:
            site = site_cls("", limiter)
            for i, result in enumerate(results):
                if sid != self.search_id:
                    return  # a newer search replaced these
                self.bridge.cover_ready.emit(sid, i, site.cover(result.cover_url) if result.cover_url else None)

        threading.Thread(target=covers, daemon=True).start()

    def _on_cover(self, sid: int, index: int, data) -> None:
        if sid == self.search_id and index < len(self.results):
            self.results[index].set_cover(data)

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
        entry = self.history.remember(self.key, site.title_url, info.title, len(info.chapters), info.status,
                                      info.cover)
        keys = [chapter_key(c.number) for c in info.chapters]
        self.new_keys = {k for k in keys if k not in set(entry.get("known", []))} if entry.get("known") else set()
        self.history.mark_seen(self.key, keys)
        self.refresh_cover()
        self.title_lbl.setText(info.title)
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for g in info.genres[:6]:
            self.chips.addWidget(label(g, "chip"))
        self.chips.addStretch(1)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(self.settings.default_format)))
        self.save_to.setText(self.settings.download_dir)

        loose = sum(1 for c in info.chapters if c.volume == core.NO_VOLUME)
        self.per_file.blockSignals(True)
        self.per_file.setMaximum(max(1, loose))
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

    def refresh_cover(self) -> None:
        if self.info:
            self.cover.setPixmap(rounded_pixmap(self.info.cover, 132, 188))
        for item in self.results:
            item.set_cover(item.data)  # the placeholder follows the theme

    # ---- file table

    def _regroup(self) -> None:
        if not self.info:
            return
        self.groups = core.make_groups(self.info.chapters, self.per_file.value())
        vols = sum(1 for c in self.info.chapters if c.volume != core.NO_VOLUME)
        status = f"{self.info.status}  ·  " if self.info.status else ""
        self.meta_lbl.setText(f"{status}{len(self.info.chapters)} chapters  ·  "
                              f"{'volume numbers available' if vols else 'no volume numbers'}")
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.groups))
        for i, g in enumerate(self.groups):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
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
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 0, 10, 0)
            hl.addWidget(bar)
            self.table.setCellWidget(i, 5, holder)
        self.table.blockSignals(False)
        self.order = list(range(len(self.groups)))
        self.row_of = list(self.order)
        self._apply_sort()
        self._show_page(0)
        self.anchor = None
        numbers = [c.number for c in self.info.chapters]
        for box in (self.range_from, self.range_to):
            box.setRange(int(min(numbers)), math.ceil(max(numbers)))
        self.range_from.setValue(self.range_from.minimum())
        self.range_to.setValue(self.range_to.maximum())
        self._mark_history()
        self._fill_sizes()
        self._update_summary()

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
                self.table.item(i, 0).setCheckState(Qt.Unchecked)
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
        return self.table.cellWidget(row, 5).findChild(QProgressBar)

    def _checked_rows(self) -> list[int]:
        return [i for i in range(self.table.rowCount()) if self.table.item(i, 0).checkState() == Qt.Checked]

    def _check(self, rule) -> None:
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(Qt.Checked if rule(i) else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_) -> None:
        rows = self._checked_rows()
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
            item = self.table.item(i, 4)
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
        for w in (self.url, self.fetch_btn, self.fmt, self.per_file, self.save_to, self.all_btn,
                  self.none_btn, self.first_n, self.first_btn):
            w.setEnabled(not locked)
        self.table.setEnabled(True)
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            flags = Qt.ItemIsEnabled | (Qt.NoItemFlags if locked else Qt.ItemIsUserCheckable)
            item.setFlags(flags)

    def _start(self) -> None:
        rows = self._checked_rows()
        if not rows or not self.site:
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
        self.history.start_run(self.key, [k for r in rows for k in group_keys(self.groups[r])],
                               fmt, self.per_file.value(), str(save_to))
        self._refresh_run_status()

        groups = [self.groups[r] for r in rows]

        def on_status(index: int, state: str, frac: float, msg: str) -> None:
            self.bridge.status.emit(rows[index], state, frac, msg)

        def work() -> None:
            failed = core.run_jobs(self.site, title, groups, fmt, self.book_dir, work_dir,
                                   self.settings.keep_temp, workers, self.cancel, on_status, mode)
            self.bridge.finished.emit([rows[i] for i in failed], self.cancel.is_set())

        threading.Thread(target=work, daemon=True).start()

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
        for w in (self.per_file, self.workers, self.delay):
            w.valueChanged.connect(self._update_dirty)
        self.keep_temp.toggled.connect(self._update_dirty)
        self._update_dirty()

    def _show(self, s: Settings) -> None:
        self.download_dir.setText(s.download_dir)
        self.temp_dir.setText(s.temp_dir)
        self.keep_temp.setChecked(s.keep_temp)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(s.default_format)))
        self.per_file.setValue(s.chapters_per_file)
        self.workers.setValue(s.workers)
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.download_mode)))
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.source.setCurrentIndex(max(0, self.source.findData(s.default_source)))
        self.delay.setValue(s.request_delay)

    def _form(self) -> Settings:
        """The settings as currently entered in the form."""
        return Settings(
            download_dir=self.download_dir.text().strip() or Settings().download_dir,
            temp_dir=self.temp_dir.text().strip(),
            workers=self.workers.value(),
            download_mode=self.mode.currentData(),
            request_delay=round(self.delay.value(), 1),
            default_format=self.fmt.currentData(),
            chapters_per_file=self.per_file.value(),
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
        forget.clicked.connect(lambda: (self.history.forget(key), self.refresh()))
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


class MainWindow(QWidget):
    UPDATE_CHECK_MS = 6 * 60 * 60 * 1000

    def __init__(self):
        super().__init__(objectName="root")
        self.setWindowTitle("Nyanga")
        self.setWindowIcon(theme.app_icon())
        self.resize(1120, 840)
        self.settings = Settings.load()
        CURRENT["mode"] = self._resolve(self.settings.theme)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        side = QFrame(objectName="sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 26, 18, 18)
        sl.setSpacing(6)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        mascot = QLabel()
        mascot.setPixmap(theme.app_pixmap(96).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(mascot)
        brand.addWidget(label("Nyanga", "logo"))
        brand.addStretch(1)
        sl.addLayout(brand)
        sl.addSpacing(4)
        sl.addWidget(label("cute & cozy ✧", "tagline"))
        sl.addSpacing(22)
        self.stack = QStackedWidget()
        self.history = History()
        self.download = DownloadPage(self.settings, self.history)
        self.library = LibraryPage(self.settings, self.history)
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
            sbox.addWidget(label(f"♥  {site.name}", "sitePill"))
        sl.addWidget(sites)
        sl.addSpacing(6)
        self.toggle = QPushButton(objectName="themeToggle")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setIconSize(QSize(18, 18))
        self.toggle.clicked.connect(self._toggle_theme)
        sl.addWidget(self.toggle)
        sl.addSpacing(10)
        sl.addWidget(label("HI LIL GOMIEE!!", "greeting"))
        version = QPushButton(f"version {__version__}", objectName="version")
        version.setCursor(Qt.PointingHandCursor)
        version.setToolTip("What's new in this version ✧")
        version.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(updater.notes_url())))
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
    app.setFont(theme.load_font())
    app.setWindowIcon(theme.app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
