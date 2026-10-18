"""Colors (light and dark), the stylesheet, the bundled font and the icon set."""

from __future__ import annotations

from pathlib import Path
from string import Template

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

import paths

ASSETS = paths.BUNDLE / "assets"
LIGHT, DARK, SYSTEM = "light", "dark", "system"

PALETTES = {
    LIGHT: {
        "text": "#5a2a41", "muted": "#a86b88", "accent": "#e0457f", "accent_soft": "#c2457a",
        "bg": "#fff0f6", "side_top": "#ffd6e7", "side_bottom": "#ffc0d9", "side_text": "#8a3b62",
        "nav_hover": "rgba(255, 255, 255, 0.45)", "nav_checked": "#ffffff", "sites_bg": "rgba(255, 255, 255, 0.4)",
        "card": "#ffffff", "border": "#ffd6e7", "button": "#ffe3ef", "button_hover": "#ffd1e4",
        "disabled_bg": "#f6e9ef", "disabled_text": "#d3b3c2", "primary_a": "#ff7eb3", "primary_b": "#ff5c9a",
        "primary_hover": "#ff4f90", "primary_disabled": "#f3c6d8", "primary_disabled_text": "#fff6fa",
        "input": "#fffafc", "input_disabled": "#fbf3f7", "input_disabled_text": "#c9a5b6", "focus": "#ff7eb3",
        "header": "#fff0f6", "alt_row": "#fff6fa", "selection": "#ffe3ef", "chip": "#ffe3ef",
        "track": "#ffe3ef", "chunk_a": "#ffb0d0", "chunk_b": "#ff6fa6", "scroll": "#ffc4dc",
        "check_border": "#ffb3d0", "check_bg": "#ffffff", "error": "#d6336c", "ok": "#2f9e6a",
        "failed_chunk": "#ffd1dc", "shadow": (255, 92, 154, 38),
    },
    DARK: {
        "text": "#f6dbe8", "muted": "#c08aa5", "accent": "#ff8fbf", "accent_soft": "#ff9ec6",
        "bg": "#1d1420", "side_top": "#2c1b2c", "side_bottom": "#231623", "side_text": "#e7b6cf",
        "nav_hover": "rgba(255, 143, 191, 0.10)", "nav_checked": "#3a2338", "sites_bg": "rgba(255, 143, 191, 0.07)",
        "card": "#291d2b", "border": "#3d2a3e", "button": "#3a2338", "button_hover": "#4a2b46",
        "disabled_bg": "#2a2029", "disabled_text": "#6b5566", "primary_a": "#ff7eb3", "primary_b": "#ff5c9a",
        "primary_hover": "#ff6fa6", "primary_disabled": "#4b2f43", "primary_disabled_text": "#9c7890",
        "input": "#221824", "input_disabled": "#251c26", "input_disabled_text": "#6b5566", "focus": "#ff7eb3",
        "header": "#241a26", "alt_row": "#2e2130", "selection": "#45293f", "chip": "#3a2338",
        "track": "#3a2338", "chunk_a": "#c45a8c", "chunk_b": "#ff6fa6", "scroll": "#4f3048",
        "check_border": "#7a4a6c", "check_bg": "#221824", "error": "#ff6b8e", "ok": "#5fd39a",
        "failed_chunk": "#5a2534", "shadow": (0, 0, 0, 90),
    },
}

_STYLE = Template("""
* { color: $text; }
QWidget#root, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget { background: $bg; }
QToolTip { background: $card; color: $text; border: 1px solid $border; border-radius: 8px; padding: 6px; }
QFrame#sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $side_top, stop:1 $side_bottom);
    border: none;
}
QLabel#logo { font-size: 20px; font-weight: 700; color: $accent; }
QLabel#tagline { color: $muted; font-size: 12px; }
QFrame#sitesBox { background: $sites_bg; border-radius: 16px; }
QLabel#sitesTitle { color: $muted; font-size: 10px; font-weight: 600; }
QLabel#sitePill {
    background: $card; color: $accent_soft; border-radius: 10px; padding: 5px 10px;
    font-size: 12px; font-weight: 600;
}
QLabel#greeting { color: $accent; font-size: 17px; font-weight: 700; padding-left: 4px; }
QPushButton#version {
    background: transparent; color: $muted; padding: 0 0 0 4px; text-align: left;
    font-size: 11px; font-weight: 400;
}
QPushButton#version:hover { background: transparent; color: $accent; text-decoration: underline; }
QPushButton#nav {
    background: transparent; border: none; border-radius: 14px;
    padding: 11px 14px; text-align: left; font-size: 15px; font-weight: 600; color: $side_text;
}
QPushButton#nav:hover { background: $nav_hover; }
QPushButton#nav:checked { background: $nav_checked; color: $accent; }
QPushButton#themeToggle { background: transparent; padding: 8px 12px; text-align: left; color: $side_text; }
QPushButton#themeToggle:hover { background: $nav_hover; }
QLabel#h1 { font-size: 26px; font-weight: 700; color: $accent; }
QLabel#h2 { font-size: 16px; font-weight: 600; }
QLabel#hint, QLabel#meta { color: $muted; }
QLabel#hint[error="true"] { color: $error; font-weight: 600; }
QLabel#mangaTitle { font-size: 22px; font-weight: 700; }
QLabel#chip { background: $chip; color: $accent_soft; border-radius: 10px; padding: 3px 10px; font-size: 12px; }
QFrame#card { background: $card; border: 1px solid $border; border-radius: 20px; }
QMessageBox { background: $card; }
QMessageBox QLabel { color: $text; }
QFrame#result { background: $alt_row; border: 2px solid transparent; border-radius: 16px; }
QFrame#result:hover { background: $selection; border-color: $focus; }
QLabel#resultTitle { color: $text; font-size: 15px; font-weight: 600; }
QPushButton {
    background: $button; color: $accent_soft; border: none; border-radius: 13px;
    padding: 9px 16px; font-weight: 600; font-size: 13px;
}
QPushButton:hover { background: $button_hover; }
QPushButton:disabled { background: $disabled_bg; color: $disabled_text; }
QPushButton#viewToggle { background: transparent; padding: 7px; border-radius: 11px; }
QPushButton#viewToggle:hover { background: $button_hover; }
QPushButton#viewToggle:checked { background: $button; }
QPushButton#link { background: transparent; color: $accent; padding: 0; border-radius: 0; }
QPushButton#link:hover { text-decoration: underline; }
QLabel#about { color: $text; }
QPushButton#pager { min-width: 34px; max-width: 34px; padding: 4px 0; font-size: 20px; font-weight: 700; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $primary_a, stop:1 $primary_b);
    color: white; padding: 11px 24px; font-size: 15px;
}
QPushButton#primary:hover { background: $primary_hover; }
QPushButton#primary:disabled { background: $primary_disabled; color: $primary_disabled_text; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $input; border: 2px solid $border; border-radius: 12px;
    padding: 7px 10px; selection-background-color: $primary_a; font-size: 13px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $focus; }
QLineEdit[error="true"] { border-color: $error; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: $input_disabled_text; background: $input_disabled;
}
QComboBox { combobox-popup: 0; }  /* a plain list popup, without the strips above and below */
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: url($chevron); width: 14px; height: 14px; }
QComboBox QAbstractItemView {
    background: $card; border: 2px solid $border; border-radius: 14px; padding: 6px; outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 32px; padding: 0 10px; border-radius: 9px; color: $text;
}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {
    background: $selection; color: $accent_soft;
}
QFrame#toast { background: $chip; border-radius: 13px; }
QDialog#whatsNew { background: $bg; }
QFrame#noteItem { background: $card; border: 1px solid $border; border-radius: 14px; }
QLabel#noteSection { font-size: 15px; font-weight: 700; color: $accent; padding-top: 4px; }
QLabel#noteTitle { font-size: 14px; font-weight: 600; }
QLabel#noteDetail { color: $muted; font-size: 13px; }
QFrame#notify { background: $card; border: 2px solid $border; border-radius: 22px; }
QFrame#updatePill {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $primary_a, stop:1 $primary_b);
    border-radius: 21px;
}
QFrame#updatePill:hover { background: $primary_hover; }
QFrame#updatePill[busy="true"] { background: $card; border: 2px solid $border; }
QFrame#updatePill[busy="true"]:hover { background: $button_hover; }
QLabel#updatePillText { color: white; font-size: 14px; font-weight: 700; background: transparent; }
QFrame#updatePill[busy="true"] QLabel#updatePillText { color: $accent; }
QLabel#libTitle { font-size: 17px; font-weight: 700; }
QLabel#newBadge {
    background: $primary_b; color: white; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700;
}
QProgressBar#libBar { color: $accent_soft; font-size: 12px; }
QLabel#notifyTitle { font-size: 19px; font-weight: 700; color: $accent; }
QLabel#notifyBody { font-size: 13px; color: $text; }
QPushButton#notifyClose { background: transparent; padding: 5px; border-radius: 10px; }
QPushButton#notifyClose:hover { background: $button; }
QLabel#toastText { background: transparent; color: $accent_soft; font-size: 14px; font-weight: 600; }
QFrame#toast[error="true"] QLabel#toastText { color: $error; }
QLabel#pathTitle { font-size: 14px; font-weight: 600; }
QLabel#pathChip {
    background: $input; border: 2px solid $border; border-radius: 12px; padding: 8px 12px;
    font-size: 13px; color: $muted;
}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 18px; border: none; background: transparent;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator, QTableWidget::indicator { width: 22px; height: 22px; border: none; background: transparent; }
QCheckBox::indicator:unchecked, QTableWidget::indicator:unchecked { image: url($paw_off); }
QCheckBox::indicator:checked, QTableWidget::indicator:checked { image: url($paw_on); }
QCheckBox::indicator:checked:disabled, QTableWidget::indicator:checked:disabled { image: url($paw_on_disabled); }
QTableWidget {
    background: $card; alternate-background-color: $alt_row; border: none; gridline-color: transparent;
    selection-background-color: $selection; selection-color: $text;
}
QTableWidget::item { padding: 4px 6px; }
QHeaderView::section { background: $header; color: $muted; border: none; padding: 8px 9px 8px 10px; font-weight: 600; }
QProgressBar {
    background: $track; border: none; border-radius: 9px;
    text-align: center; color: $side_text; font-size: 11px; font-weight: 600;
}
QProgressBar::chunk {
    border-radius: 9px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $chunk_a, stop:1 $chunk_b);
}
QProgressBar[state="Done"] { color: $ok; }
QProgressBar[state="Already exists"], QProgressBar[state="Cancelled"] { color: $muted; }
QProgressBar[state="Failed"] { color: $error; }
QProgressBar[state="Failed"]::chunk { background: $failed_chunk; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""")


def stylesheet(mode: str) -> str:
    icons = ASSETS / "icons"
    values = {k: v for k, v in PALETTES[mode].items() if isinstance(v, str)}
    values.update(  # tick boxes are cat paws: an outline when off, a pink paw when on
        paw_on=(icons / "paw-on.svg").as_posix(),
        paw_on_disabled=(icons / "paw-on-disabled.svg").as_posix(),
        paw_off=(icons / f"paw-off-{mode}.svg").as_posix(),
        chevron=(icons / f"chevron-{mode}.svg").as_posix(),
    )
    return _STYLE.substitute(values)


def color(mode: str, name: str) -> QColor:
    value = PALETTES[mode][name]
    return QColor(*value) if isinstance(value, tuple) else QColor(value)


# --------------------------------------------------------------------------- font


def load_font() -> QFont:
    """Register the bundled rounded font and return it, falling back to the system font."""
    families = []
    for path in sorted((ASSETS / "fonts").glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id != -1:
            families += QFontDatabase.applicationFontFamilies(font_id)
    font = QFont()
    font.setFamilies(list(dict.fromkeys(families)) + ["Nunito", "Segoe UI", "Noto Sans", "sans-serif"])
    font.setPointSize(10)
    return font


# --------------------------------------------------------------------------- icons

# 24x24, rounded strokes; COLOR is swapped for the theme color when drawn.
_ICONS = {
    "download": '<path d="M12 4v10m-4.5-4.5L12 14l4.5-4.5" fill="none" stroke="COLOR" stroke-width="2.4" '
                'stroke-linecap="round" stroke-linejoin="round"/><path d="M4.5 15.5v1.8A2.7 2.7 0 0 0 7.2 20h9.6a2.7 '
                '2.7 0 0 0 2.7-2.7v-1.8" fill="none" stroke="COLOR" stroke-width="2.4" stroke-linecap="round"/>',
    "settings": '<path d="M5 7h7m4 0h3M5 17h3m4 0h7" stroke="COLOR" stroke-width="2.4" stroke-linecap="round"/>'
                '<circle cx="14" cy="7" r="2.6" fill="none" stroke="COLOR" stroke-width="2.4"/>'
                '<circle cx="10" cy="17" r="2.6" fill="none" stroke="COLOR" stroke-width="2.4"/>',
    "search": '<circle cx="10.5" cy="10.5" r="5.8" fill="none" stroke="COLOR" stroke-width="2.4"/>'
              '<path d="M15 15l4.5 4.5" stroke="COLOR" stroke-width="2.6" stroke-linecap="round"/>'
              '<path d="M10.5 7.8l.7 1.9 1.9.8-1.9.8-.7 1.9-.7-1.9-1.9-.8 1.9-.8z" fill="COLOR"/>',
    "folder": '<path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h3.2l2 2.2H18a2.5 2.5 0 0 1 2.5 2.5v7.3A2.5 2.5 0 0 1 18 '
              '19.5H6A2.5 2.5 0 0 1 3.5 17z" fill="none" stroke="COLOR" stroke-width="2.2" stroke-linejoin="round"/>'
              '<path d="M12 16.6s-2.6-1.5-2.6-3.2c0-.9.7-1.5 1.4-1.5.5 0 .9.3 1.2.7.3-.4.7-.7 1.2-.7.7 0 1.4.6 '
              '1.4 1.5 0 1.7-2.6 3.2-2.6 3.2z" fill="COLOR"/>',
    "heart": '<path d="M12 20.3s-7.6-4.6-9-9.4C2.1 7.7 4.2 4.8 7.2 4.8c2 0 3.5 1.1 4.8 2.8 1.3-1.7 2.8-2.8 '
             '4.8-2.8 3 0 5.1 2.9 4.2 6.1-1.4 4.8-9 9.4-9 9.4z" fill="COLOR"/>',
    "paw": '<path d="M12 12.4c-2.9 0-5.7 3-5.7 5.3 0 1.7 1.3 2.6 2.9 2.6 1.1 0 1.9-.6 2.8-.6s1.7.6 2.8.6c1.6 0 2.9-.9 2.9-2.6 0-2.3-2.8-5.3-5.7-5.3z" fill="COLOR"/><ellipse cx="4.7" cy="10.6" rx="1.9" ry="2.4" transform="rotate(-22 4.7 10.6)" fill="COLOR"/><ellipse cx="8.9" cy="6.4" rx="2.0" ry="2.6" transform="rotate(-8 8.9 6.4)" fill="COLOR"/><ellipse cx="15.1" cy="6.4" rx="2.0" ry="2.6" transform="rotate(8 15.1 6.4)" fill="COLOR"/><ellipse cx="19.3" cy="10.6" rx="1.9" ry="2.4" transform="rotate(22 19.3 10.6)" fill="COLOR"/>',
    "paw_outline": '<path d="M12 12.4c-2.9 0-5.7 3-5.7 5.3 0 1.7 1.3 2.6 2.9 2.6 1.1 0 1.9-.6 2.8-.6s1.7.6 2.8.6c1.6 0 2.9-.9 2.9-2.6 0-2.3-2.8-5.3-5.7-5.3z" fill="none" stroke="COLOR" stroke-width="1.8"/><ellipse cx="4.7" cy="10.6" rx="1.9" ry="2.4" transform="rotate(-22 4.7 10.6)" fill="none" stroke="COLOR" stroke-width="1.8"/><ellipse cx="8.9" cy="6.4" rx="2.0" ry="2.6" transform="rotate(-8 8.9 6.4)" fill="none" stroke="COLOR" stroke-width="1.8"/><ellipse cx="15.1" cy="6.4" rx="2.0" ry="2.6" transform="rotate(8 15.1 6.4)" fill="none" stroke="COLOR" stroke-width="1.8"/><ellipse cx="19.3" cy="10.6" rx="1.9" ry="2.4" transform="rotate(22 19.3 10.6)" fill="none" stroke="COLOR" stroke-width="1.8"/>',
    "cat": '<path d="M5 10L5.6 4.4 9.6 7.2Q12 6.5 14.4 7.2L18.4 4.4 19 10Q20.4 12.2 19.9 14.6 18.8 19.6 12 19.8 '
           '5.2 19.6 4.1 14.6 3.6 12.2 5 10z" fill="none" stroke="COLOR" stroke-width="2" stroke-linejoin="round"/>'
           '<path d="M8.3 12.8q1.3-1.3 2.6 0M13.1 12.8q1.3-1.3 2.6 0" fill="none" stroke="COLOR" stroke-width="1.7" '
           'stroke-linecap="round"/><path d="M11.1 14.5h1.8l-.9 1.1z" fill="COLOR"/>'
           '<path d="M10.2 16.4q.9.8 1.8 0 .9.8 1.8 0" fill="none" stroke="COLOR" stroke-width="1.4" stroke-linecap="round"/>',
    "library": '<rect x="3.6" y="5" width="4.4" height="14.6" rx="1.4" fill="none" stroke="COLOR" stroke-width="2.1"/>'
               '<rect x="9.8" y="5" width="4.4" height="14.6" rx="1.4" fill="none" stroke="COLOR" stroke-width="2.1"/>'
               '<path d="M16 7.6l3.1-.9 2.9 12-3.1.9z" fill="none" stroke="COLOR" stroke-width="2.1" stroke-linejoin="round"/>'
               '<path d="M5.8 13.2s-1.4-.8-1.4-1.8c0-.5.4-.8.8-.8.3 0 .5.2.6.4.1-.2.3-.4.6-.4.4 0 .8.3.8.8 0 1-1.4 1.8-1.4 1.8z" fill="COLOR"/>',
    "undo": '<path d="M9 5.5L4.8 9.7 9 13.9" fill="none" stroke="COLOR" stroke-width="2.4" stroke-linecap="round" '
            'stroke-linejoin="round"/><path d="M5.5 9.7h8.3a5 5 0 0 1 0 10H10" fill="none" stroke="COLOR" '
            'stroke-width="2.4" stroke-linecap="round"/>',
    "close": '<path d="M7 7l10 10M17 7L7 17" stroke="COLOR" stroke-width="2.6" stroke-linecap="round"/>',
    "refresh": '<path d="M19 12a7 7 0 1 1-2.05-4.95" fill="none" stroke="COLOR" stroke-width="2.4" '
               'stroke-linecap="round"/><path d="M19.2 4.5v3.6h-3.6" fill="none" stroke="COLOR" stroke-width="2.4" '
               'stroke-linecap="round" stroke-linejoin="round"/>',
    "moon": '<path d="M19.5 14.6A7.8 7.8 0 0 1 9.4 4.5a7.8 7.8 0 1 0 10.1 10.1z" fill="COLOR"/>'
            '<path d="M17 4.5l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5z" fill="COLOR"/>',
    "sun": '<circle cx="12" cy="12" r="4.2" fill="COLOR"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 '
           '12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" stroke="COLOR" '
           'stroke-width="2.2" stroke-linecap="round"/>',
    "check": '<path d="M5.5 12.5l4.2 4.2 8.8-9.4" fill="none" stroke="COLOR" stroke-width="2.6" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
    "select_none": '<rect x="4.5" y="4.5" width="15" height="15" rx="4.5" fill="none" stroke="COLOR" stroke-width="2.2"/>',
    "grid": '<rect x="4" y="4" width="6.6" height="6.6" rx="1.8" fill="COLOR"/><rect x="13.4" y="4" width="6.6" height="6.6" rx="1.8" fill="COLOR"/>'
            '<rect x="4" y="13.4" width="6.6" height="6.6" rx="1.8" fill="COLOR"/><rect x="13.4" y="13.4" width="6.6" height="6.6" rx="1.8" fill="COLOR"/>',
    "list": '<path d="M9 7h10M9 12h10M9 17h6" stroke="COLOR" stroke-width="2.4" stroke-linecap="round"/>'
            '<circle cx="5" cy="7" r="1.4" fill="COLOR"/><circle cx="5" cy="12" r="1.4" fill="COLOR"/>'
            '<circle cx="5" cy="17" r="1.4" fill="COLOR"/>',
}

# The app's mascot: a happy cat face (the same cat as in loader.py) with a heart. Drawn for this app.
_APP_ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#ff9cc6"/><stop offset="1" stop-color="#ff5c9a"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="18" fill="url(#g)"/>
<g fill="#fff6ee" stroke="#7a4a5f" stroke-width="1.8" stroke-linejoin="round">
<path d="M12.5 33 14.5 9.5 29 22z"/><path d="M51.5 33 49.5 9.5 35 22z"/>
<ellipse cx="32" cy="37.5" rx="21.5" ry="17"/></g>
<path d="M17.2 26.5 18 15.5 24.6 21.6z" fill="#ffc2d9"/><path d="M46.8 26.5 46 15.5 39.4 21.6z" fill="#ffc2d9"/>
<g fill="none" stroke="#7a4a5f" stroke-width="2.6" stroke-linecap="round">
<path d="M19.5 37.5q4.5-5.5 9 0"/><path d="M35.5 37.5q4.5-5.5 9 0"/>
<path d="M28 46q2 2.2 4 0q2 2.2 4 0" stroke-width="1.8"/></g>
<ellipse cx="17.5" cy="43.5" rx="3.6" ry="2.1" fill="#ffb3cf"/><ellipse cx="46.5" cy="43.5" rx="3.6" ry="2.1" fill="#ffb3cf"/>
<path d="M32 45s-3.4-2-3.4-4.1c0-1.1.9-1.9 1.9-1.9.7 0 1.2.4 1.5.9.3-.5.8-.9 1.5-.9 1 0 1.9.8 1.9 1.9 0 2.1-3.4 4.1-3.4 4.1z" fill="#ff6fa6"/>
<path d="M51 7.5s-2.6-1.5-2.6-3.2c0-.9.7-1.5 1.5-1.5.5 0 .9.3 1.1.7.2-.4.6-.7 1.1-.7.8 0 1.5.6 1.5 1.5 0 1.7-2.6 3.2-2.6 3.2z" fill="#fff" transform="translate(-19 5)"/>
</svg>"""


def _render(svg: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pix


def icon(name: str, color: str | QColor, size: int = 48) -> QIcon:
    hex_color = QColor(color).name()
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{_ICONS[name].replace("COLOR", hex_color)}</svg>'
    return QIcon(_render(svg, size))


def app_pixmap(size: int = 128) -> QPixmap:
    return _render(_APP_ICON, size)


def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        result.addPixmap(app_pixmap(size))
    return result
