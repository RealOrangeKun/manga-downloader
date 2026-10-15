"""The pink Qt window: a Download page and a Settings page."""

from __future__ import annotations

import html
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import core
import theme
from loader import CatLoader
from builders import FORMATS

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

    @staticmethod
    def path() -> Path:
        return Path(__file__).resolve().parent / "settings.json"  # next to the script, ignored by git

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
    fetched = Signal(object, object)  # site, MangaInfo
    fetch_failed = Signal(str)
    status = Signal(int, str, float, str)  # table row, state, fraction, message
    finished = Signal(list, bool)  # failed rows, cancelled


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


class DownloadPage(QWidget):
    completed = Signal(str, int, str)  # title, number of files, folder

    def __init__(self, settings: Settings):
        super().__init__(objectName="page")
        self.settings = settings
        self.bridge = Bridge()
        self.bridge.fetched.connect(self._on_fetched)
        self.bridge.fetch_failed.connect(self._on_fetch_failed)
        self.bridge.status.connect(self._on_status)
        self.bridge.finished.connect(self._on_finished)
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
        self.url = QLineEdit(placeholderText="Paste a manga link, like https://fanfox.net/manga/<title>/")
        self.url.returnPressed.connect(self._fetch)
        self.fetch_btn = set_icon(QPushButton(" Find", objectName="primary"), "search", "white")
        self.fetch_btn.clicked.connect(self._fetch)
        row.addWidget(self.url, 1)
        row.addWidget(self.fetch_btn)
        fl.addLayout(row)
        sites = ", ".join(s.name for s in core.SITES)
        self.find_hint = label(f"Supported sites: {sites}", "hint")
        fl.addWidget(self.find_hint)
        col.addWidget(find)

        # shown while a title is being looked up
        self.lookup_card, lk = card()
        lrow = QHBoxLayout()
        lrow.addStretch(1)
        self.lookup_cat = CatLoader(lambda: CURRENT["mode"], (150, 120))
        lrow.addWidget(self.lookup_cat)
        ltext = QVBoxLayout()
        ltext.addStretch(1)
        ltext.addWidget(label("Looking it up…", "h2"))
        ltext.addWidget(label("Reading the chapter list and cover ✧", "hint"))
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
        tl.addLayout(head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "File", "Chapters", "Count", "Progress"])
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
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
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
        self.status_lbl = label("Paste a link to get started ♡", "meta")
        self.overall = QProgressBar(maximum=1000, textVisible=False)
        self.overall.setFixedHeight(12)
        info.addWidget(self.status_lbl)
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

    def _fetch(self) -> None:
        url = self.url.text().strip()
        site_cls = core.site_for(url)
        if site_cls is None:
            self._hint("That isn't a title link from a supported site: "
                       + ", ".join(s.example for s in core.SITES), error=True)
            return
        self._hint("Looking it up…")
        self.fetch_btn.setEnabled(False)
        self.manga_card.hide()
        self.files_card.hide()
        self.lookup_card.show()
        self.lookup_cat.start()
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

    def _on_fetched(self, site, info: core.MangaInfo) -> None:
        self._end_lookup()
        self.fetch_btn.setEnabled(True)
        self._hint("Supported sites: " + ", ".join(s.name for s in core.SITES))
        if not info.chapters:
            self._on_fetch_failed("No chapters found on that page.")
            return
        self.site, self.info = site, info
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
        self.open_btn.hide()
        self._regroup()

    def refresh_cover(self) -> None:
        if self.info:
            self.cover.setPixmap(rounded_pixmap(self.info.cover, 132, 188))

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
            bar = QProgressBar(maximum=1000, value=0, format="")
            bar.setFixedHeight(18)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 0, 10, 0)
            hl.addWidget(bar)
            self.table.setCellWidget(i, 4, holder)
        self.table.blockSignals(False)
        # Show every row; the page itself scrolls, so the table never needs its own scrollbar.
        rows_h = sum(self.table.rowHeight(i) for i in range(self.table.rowCount()))
        self.table.setFixedHeight(self.table.horizontalHeader().height() + rows_h + 4)
        self.first_n.setMaximum(len(self.groups))
        self._update_summary()

    def _bar(self, row: int) -> QProgressBar:
        return self.table.cellWidget(row, 4).findChild(QProgressBar)

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
        self.summary.setText(f"{len(rows)} of {len(self.groups)} files  ·  {chapters} chapters selected")
        if not self.running:
            self.start_btn.setEnabled(bool(rows))
            self.status_lbl.setText(f"Ready to download {len(rows)} files ({chapters} chapters)"
                                    if rows else "Pick at least one file")

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
        self._set_locked(True)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText(" Cancel")
        self.cancel_btn.show()
        self.open_btn.hide()
        self.bar_cat.start()
        self.overall.setValue(0)
        for i in range(self.table.rowCount()):
            bar = self._bar(i)
            bar.setValue(0)
            bar.setFormat(core.QUEUED if i in rows else "")
            bar.setProperty("state", "")
            repolish(bar)
        self.status_lbl.setText(f"Downloading {len(rows)} files with {workers} "
                                f"{'worker' if workers == 1 else 'workers'} ({mode})…")

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
            bar.setFormat(msg)
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
        done = sum(self.fractions.values())
        self.overall.setValue(int(done / len(self.fractions) * 1000))

    def _on_finished(self, failed: list[int], cancelled: bool) -> None:
        self.running = False
        self.bar_cat.stop()
        self._set_locked(False)
        self.cancel_btn.hide()
        self.open_btn.show()
        self._update_summary()
        if cancelled:
            self.status_lbl.setText("Cancelled. Run it again with the same choices to resume.")
        elif failed:
            self.status_lbl.setText(f"{len(failed)} of {len(self.fractions)} files failed (hover a bar for "
                                    "the reason). Run again to resume ✧")
        else:
            self.overall.setValue(1000)
            self.status_lbl.setText(f"All done ♡  Files are in {self.book_dir}")
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
    changed = Signal()

    def __init__(self, settings: Settings):
        super().__init__(objectName="page")
        self.settings = settings
        col = QVBoxLayout(self)
        col.setContentsMargins(32, 28, 32, 28)
        col.setSpacing(18)
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
        self.save_btn = set_icon(QPushButton(" Save", objectName="primary"), "heart", "white")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.saved)
        row.addStretch(1)
        row.addWidget(reset)
        row.addWidget(self.save_btn)
        col.addLayout(row)
        col.addStretch(1)
        self._show(settings)
        # Save is only clickable while the form differs from what is saved.
        for w in (self.download_dir, self.temp_dir):
            w.textChanged.connect(self._update_dirty)
        for w in (self.theme, self.fmt, self.mode):
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
        )

    def _toast(self, text: str, error: bool = False) -> None:
        self.toast_text.setText(text)
        color = theme.color(CURRENT["mode"], "error" if error else "accent_soft")
        self.toast_icon.setPixmap(theme.icon("cat", color).pixmap(22, 22))
        self.saved.setProperty("error", error)
        repolish(self.saved)
        self.saved.show()
        QTimer.singleShot(2500, self.saved.hide)

    def _update_dirty(self, *_) -> None:
        self.save_btn.setEnabled(self._form() != self.settings)

    def _save(self) -> None:
        # Update in place: the download page holds the same Settings object.
        for f in fields(Settings):
            setattr(self.settings, f.name, getattr(self._form(), f.name))
        try:
            self.settings.save()
            self._toast("Saved")
        except OSError as e:
            self._toast(f"Could not save: {e}", error=True)
        self._update_dirty()
        self.changed.emit()


# --------------------------------------------------------------------------- window


class Notification(QWidget):
    """A card that fades in at the bottom right with a happy cat when a download is finished."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.folder = ""
        self.fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)  # room for the shadow
        box = QFrame(objectName="notify")
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
        head.addWidget(label("Yay, it's ready!", "notifyTitle"))
        head.addStretch(1)
        close = set_icon(QPushButton(objectName="notifyClose"), "close", "muted", 14)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        head.addWidget(close)
        col.addLayout(head)
        self.body = label("", "notifyBody", wrap=True)
        col.addWidget(self.body)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        open_btn = set_icon(QPushButton(" Open folder"), "folder")
        open_btn.clicked.connect(self._open)
        buttons.addWidget(open_btn)
        col.addSpacing(4)
        col.addLayout(buttons)
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
        self.body.setText(f"<b>{html.escape(title)}</b> is all downloaded! "
                          f"{files} {'file is' if files == 1 else 'files are'} waiting for you. Happy reading ✧")
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self.cat.start()
        self._fade(1.0)
        self.timer.start()

    def dismiss(self) -> None:
        self.timer.stop()
        self._fade(0.0)

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
        if self.isVisible():
            self.timer.start(4000)
        super().leaveEvent(event)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__(objectName="root")
        self.setWindowTitle("Manga Downloader")
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
        brand.addWidget(label("Manga\nDownloader", "logo"))
        brand.addStretch(1)
        sl.addLayout(brand)
        sl.addSpacing(4)
        sl.addWidget(label("cute & cozy ✧", "tagline"))
        sl.addSpacing(22)
        self.stack = QStackedWidget()
        self.download = DownloadPage(self.settings)
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.changed.connect(lambda: self.apply_theme(self.settings.theme))
        self.stack.addWidget(self.download)
        self.stack.addWidget(self.settings_page)
        nav = QButtonGroup(self)
        for i, (text, icon_name) in enumerate([("  Download", "download"), ("  Settings", "settings")]):
            b = set_icon(QPushButton(text, objectName="nav", checkable=True), icon_name, "side_text", 20)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i))
            nav.addButton(b)
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

        layout.addWidget(side)
        layout.addWidget(self.stack, 1)

        self.notification = Notification(self)
        self.download.completed.connect(self.notification.popup)

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "notification"):
            self.notification.reposition()

    def closeEvent(self, event) -> None:
        # Let running workers stop after their current page instead of leaving half-written files.
        self.download.cancel.set()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("manga-downloader")
    app.setApplicationDisplayName("Manga Downloader")
    app.setFont(theme.load_font())
    app.setWindowIcon(theme.app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
