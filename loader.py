"""A sleepy cat reading a book: the loading animation, drawn live so it follows the theme."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

import theme

# Fur and detail colors per theme; the book uses the theme's own colors.
CAT = {
    theme.LIGHT: {"fur": "#fff6ee", "line": "#7a4a5f", "ear": "#ffc2d9", "blush": "#ffb3cf", "nose": "#ff6fa6"},
    theme.DARK: {"fur": "#f6e7ea", "line": "#5a3346", "ear": "#ff9ec6", "blush": "#ff8fbf", "nose": "#ff5c9a"},
}


class CatLoader(QWidget):
    """Call start() to show and animate it, stop() to hide it.

    With celebrate=True the cat hops happily and hearts float up instead of sleepy z's.
    """

    W, H = 120.0, 96.0  # drawing coordinates; scaled to the widget size

    def __init__(self, mode: Callable[[], str], size: tuple[int, int] = (120, 96), parent: QWidget | None = None,
                 celebrate: bool = False):
        super().__init__(parent)
        self._mode = mode
        self._celebrate = celebrate
        self.setFixedSize(*size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self.update)
        self.hide()

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    # ---- drawing

    def paintEvent(self, _event) -> None:
        t = time.monotonic() - self._t0
        mode = self._mode()
        cat = {k: QColor(v) for k, v in CAT[mode].items()}
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale = min(self.width() / self.W, self.height() / self.H)
        p.translate((self.width() - self.W * scale) / 2, (self.height() - self.H * scale) / 2)
        p.scale(scale, scale)

        if self._celebrate:
            breathe = -abs(math.sin(t * 3.4)) * 3.5  # happy little hops
        else:
            breathe = math.sin(t * 2.2) * 1.2  # slow sleepy bob
        self._tail(p, t * (1.8 if self._celebrate else 1), cat)
        self._head(p, t, breathe, cat)
        self._book(p, mode)
        self._paws(p, breathe, cat)
        if self._celebrate:
            self._hearts(p, t, mode)
        else:
            self._sparkle(p, t, mode)
        p.end()

    def _tail(self, p: QPainter, t: float, cat: dict) -> None:
        swish = math.sin(t * 3.0) * 9
        path = QPainterPath(QPointF(88, 66))
        path.cubicTo(QPointF(104, 64), QPointF(108 + swish * 0.4, 46), QPointF(100 + swish, 36))
        p.setPen(QPen(cat["line"], 9, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(cat["fur"], 6, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)

    def _head(self, p: QPainter, t: float, bob: float, cat: dict) -> None:
        cx, cy = 60.0, 40.0 + bob
        # One ear gives a quick twitch every few seconds.
        twitch = max(0.0, math.sin((t % 3.2) / 0.35 * math.pi)) * 14 if t % 3.2 < 0.35 else 0.0
        for side, angle in ((-1, 0.0), (1, twitch)):
            p.save()
            p.translate(cx + side * 17, cy - 14)
            p.rotate(side * (8 + angle))
            outer = QPainterPath()
            outer.moveTo(-9, 6)
            outer.quadTo(-6, -14, 0, -16)
            outer.quadTo(6, -14, 9, 6)
            outer.closeSubpath()
            p.setPen(QPen(cat["line"], 2))
            p.setBrush(cat["fur"])
            p.drawPath(outer)
            inner = QPainterPath()
            inner.moveTo(-4.5, 3)
            inner.quadTo(-3, -8, 0, -9.5)
            inner.quadTo(3, -8, 4.5, 3)
            inner.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(cat["ear"])
            p.drawPath(inner)
            p.restore()

        p.setPen(QPen(cat["line"], 2))
        p.setBrush(cat["fur"])
        p.drawEllipse(QRectF(cx - 25, cy - 21, 50, 42))

        # Sleepy closed eyes, little blush, heart nose and a soft "w" mouth.
        p.setPen(QPen(cat["line"], 2.2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        for ex in (cx - 10, cx + 10):
            p.drawArc(QRectF(ex - 5, cy - 3, 10, 7), 20 * 16, 140 * 16)
        p.setPen(Qt.NoPen)
        blush = QColor(cat["blush"])
        blush.setAlphaF(0.65)
        p.setBrush(blush)
        for bx in (cx - 16, cx + 16):
            p.drawEllipse(QRectF(bx - 5, cy + 4, 10, 5.5))
        self._heart(p, QPointF(cx, cy + 5), 3.2, cat["nose"])
        p.setPen(QPen(cat["line"], 1.6, Qt.SolidLine, Qt.RoundCap))
        mouth = QPainterPath(QPointF(cx - 5, cy + 9))
        mouth.quadTo(QPointF(cx - 2.5, cy + 12), QPointF(cx, cy + 9.5))
        mouth.quadTo(QPointF(cx + 2.5, cy + 12), QPointF(cx + 5, cy + 9))
        p.drawPath(mouth)
        if self._celebrate:
            return
        # Sleepy "z" drifting up now and then.
        phase = (t % 2.6) / 2.6
        z = QColor(cat["line"])
        z.setAlphaF(max(0.0, 1 - phase) * 0.8)
        p.setPen(QPen(z, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        zx, zy, s = cx + 27 + phase * 6, cy - 18 - phase * 12, 4 + phase * 2
        p.drawPolyline([QPointF(zx, zy), QPointF(zx + s, zy), QPointF(zx, zy + s), QPointF(zx + s, zy + s)])

    def _book(self, p: QPainter, mode: str) -> None:
        page = theme.color(mode, "card")
        edge = theme.color(mode, "accent")
        cover = theme.color(mode, "primary_b")
        p.setPen(Qt.NoPen)
        p.setBrush(cover)
        p.drawRoundedRect(QRectF(20, 62, 80, 24), 6, 6)
        p.setPen(QPen(edge, 1.6))
        p.setBrush(page)
        for side in (-1, 1):
            leaf = QPainterPath(QPointF(60, 66))
            leaf.quadTo(QPointF(60 + side * 20, 58), QPointF(60 + side * 37, 62))
            leaf.lineTo(QPointF(60 + side * 37, 82))
            leaf.quadTo(QPointF(60 + side * 20, 78), QPointF(60, 84))
            leaf.closeSubpath()
            p.drawPath(leaf)
        p.drawLine(QPointF(60, 66), QPointF(60, 84))
        lines = QColor(edge)
        lines.setAlphaF(0.35)
        p.setPen(QPen(lines, 1.2, Qt.SolidLine, Qt.RoundCap))
        for side in (-1, 1):
            for i in range(3):
                y = 69 + i * 4.5
                p.drawLine(QPointF(60 + side * 9, y + 1), QPointF(60 + side * 30, y))

    def _paws(self, p: QPainter, bob: float, cat: dict) -> None:
        p.setPen(QPen(cat["line"], 2))
        p.setBrush(cat["fur"])
        for px in (44, 76):
            p.drawRoundedRect(QRectF(px - 7, 58 + bob * 0.4, 14, 9), 4.5, 4.5)

    def _sparkle(self, p: QPainter, t: float, mode: str) -> None:
        phase = (t % 1.8) / 1.8
        size = math.sin(phase * math.pi) * 4.5
        if size <= 0.3:
            return
        x, y = (22, 22) if int(t / 1.8) % 2 else (96, 16)
        star = QPainterPath(QPointF(x, y - size))
        for dx, dy in ((0.25, -0.25), (1, 0), (0.25, 0.25), (0, 1), (-0.25, 0.25), (-1, 0), (-0.25, -0.25)):
            star.lineTo(QPointF(x + dx * size, y + dy * size))
        star.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(mode, "accent"))
        p.drawPath(star)

    def _hearts(self, p: QPainter, t: float, mode: str) -> None:
        """Little hearts floating up and fading, for the celebrating cat."""
        base = theme.color(mode, "primary_b")
        for k, x0 in enumerate((24, 96, 60)):
            phase = (t * 0.55 + k / 3) % 1
            color = QColor(base)
            color.setAlphaF(max(0.0, 1 - phase) * 0.9)
            x = x0 + math.sin(phase * 6 + k) * 4
            self._heart(p, QPointF(x, 46 - phase * 42), 3.4 + k * 0.6, color)

    @staticmethod
    def _heart(p: QPainter, c: QPointF, r: float, color: QColor) -> None:
        heart = QPainterPath(QPointF(c.x(), c.y() + r * 1.1))
        heart.cubicTo(QPointF(c.x() - r * 1.6, c.y() - r * 0.2), QPointF(c.x() - r * 0.7, c.y() - r * 1.4),
                      QPointF(c.x(), c.y() - r * 0.5))
        heart.cubicTo(QPointF(c.x() + r * 0.7, c.y() - r * 1.4), QPointF(c.x() + r * 1.6, c.y() - r * 0.2),
                      QPointF(c.x(), c.y() + r * 1.1))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(heart)
