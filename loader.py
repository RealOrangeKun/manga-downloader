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


def paint_mini_cat(p: QPainter, rect: QRectF, t: float, mode: str) -> None:
    """A tiny version of the loading cat (head and tail) for tight spots, centered in rect."""
    cat = {k: QColor(v) for k, v in CAT[mode].items()}
    p.save()
    scale = min(rect.width() / 40, rect.height() / 24)
    p.translate(rect.center().x() - 20 * scale, rect.center().y() - 12 * scale)
    p.scale(scale, scale)

    swish = math.sin(t * 3.2) * 4
    tail = QPainterPath(QPointF(25, 18))
    tail.cubicTo(QPointF(32, 19), QPointF(35 + swish * 0.3, 12), QPointF(33 + swish, 6))
    p.setPen(QPen(cat["line"], 3.4, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(tail)
    p.setPen(QPen(cat["fur"], 1.8, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(tail)

    p.translate(17, 14 + math.sin(t * 4) * 0.8)
    p.rotate(math.sin(t * 2.6) * 9)  # curious head tilt
    p.setPen(QPen(cat["line"], 1.4))
    p.setBrush(cat["fur"])
    for side in (-1, 1):
        ear = QPainterPath(QPointF(side * 8, -2))
        ear.lineTo(QPointF(side * 7, -10.5))
        ear.lineTo(QPointF(side * 2, -6))
        ear.closeSubpath()
        p.drawPath(ear)
    p.drawEllipse(QRectF(-10, -8, 20, 16))
    p.setPen(Qt.NoPen)
    p.setBrush(cat["ear"])
    for side in (-1, 1):
        inner = QPainterPath(QPointF(side * 6.6, -4))
        inner.lineTo(QPointF(side * 6.4, -8.6))
        inner.lineTo(QPointF(side * 3.6, -6.2))
        inner.closeSubpath()
        p.drawPath(inner)

    blink = (t % 3.0) > 2.82  # a quick blink every few seconds
    p.setPen(QPen(cat["line"], 1.3, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for ex in (-4.2, 4.2):
        if blink:
            p.drawLine(QPointF(ex - 1.8, 0.4), QPointF(ex + 1.8, 0.4))
        else:
            p.drawArc(QRectF(ex - 2.2, -1.2, 4.4, 3.2), 20 * 16, 140 * 16)
    blush = QColor(cat["blush"])
    blush.setAlphaF(0.6)
    p.setPen(Qt.NoPen)
    p.setBrush(blush)
    for bx in (-6.4, 6.4):
        p.drawEllipse(QRectF(bx - 2, 2, 4, 2.2))
    CatLoader._heart(p, QPointF(0, 2.6), 1.4, cat["nose"])
    p.restore()


def _sparkle(p: QPainter, c: QPointF, r: float, color: QColor) -> None:
    """A four-point twinkle."""
    star = QPainterPath(QPointF(c.x(), c.y() - r))
    for dx, dy in ((0.24, -0.24), (1, 0), (0.24, 0.24), (0, 1), (-0.24, 0.24), (-1, 0), (-0.24, -0.24)):
        star.lineTo(QPointF(c.x() + dx * r, c.y() + dy * r))
    star.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(star)


def _happy_head(p: QPainter, cat: dict, t: float) -> None:
    """The cat's face with ^ ^ eyes, centred on (0, 0) and 18 wide; the left ear flicks now and then."""
    twitch = 10 if (t % 2.6) > 2.42 else 0  # the left ear flicks now and then
    p.setPen(QPen(cat["line"], 1.4))
    p.setBrush(cat["fur"])
    for side in (-1, 1):
        p.save()
        p.translate(side * 6, -5)
        p.rotate(-twitch if side < 0 else 0)
        ear = QPainterPath(QPointF(side * 1.5, 3))
        ear.lineTo(QPointF(side * 0.8, -5))
        ear.lineTo(QPointF(side * -4, -1))
        ear.closeSubpath()
        p.drawPath(ear)
        p.setPen(Qt.NoPen)
        p.setBrush(cat["ear"])
        inner = QPainterPath(QPointF(side * 0.6, 1))
        inner.lineTo(QPointF(side * 0.4, -3))
        inner.lineTo(QPointF(side * -2.4, -0.8))
        inner.closeSubpath()
        p.drawPath(inner)
        p.restore()
    p.drawEllipse(QRectF(-9, -7, 18, 14))
    p.setPen(QPen(cat["line"], 1.3, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for ex in (-3.8, 3.8):  # happy closed eyes: ^ ^
        p.drawArc(QRectF(ex - 2, -1.4, 4, 3.4), 20 * 16, 140 * 16)
    blush = QColor(cat["blush"])
    blush.setAlphaF(0.6)
    p.setPen(Qt.NoPen)
    p.setBrush(blush)
    for bx in (-5.8, 5.8):
        p.drawEllipse(QRectF(bx - 1.9, 1.6, 3.8, 2.1))
    CatLoader._heart(p, QPointF(0, 2.2), 1.3, cat["nose"])


def paint_update_cat(p: QPainter, rect: QRectF, t: float, mode: str) -> None:
    """The cat bringing the new version: it hugs a hopping gift box while sparkles twinkle around."""
    cat = {k: QColor(v) for k, v in CAT[mode].items()}
    box = theme.color(mode, "accent")
    p.save()
    scale = min(rect.width() / 40, rect.height() / 34)
    p.translate(rect.center().x() - 20 * scale, rect.center().y() - 17 * scale)
    p.scale(scale, scale)

    for i, (x, y, r) in enumerate(((4.5, 10, 3.4), (36, 5, 2.8), (35.5, 15, 2.1))):
        k = (math.sin(t * 3 - i * 2.1) + 1) / 2  # each one twinkles in turn
        if k > 0.15:
            color = QColor(box)
            color.setAlphaF(0.35 + 0.65 * k)
            _sparkle(p, QPointF(x, y), r * (0.5 + 0.5 * k), color)

    p.translate(0, -abs(math.sin(t * 3.4)) * 2.4)  # hop, hop

    swish = math.sin(t * 3.2) * 3
    tail = QPainterPath(QPointF(29, 25))
    tail.cubicTo(QPointF(35, 25), QPointF(37 + swish * 0.3, 19), QPointF(35 + swish, 13))
    p.setPen(QPen(cat["line"], 3.4, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(tail)
    p.setPen(QPen(cat["fur"], 1.8, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(tail)

    # The head peeks over the box, so the box is drawn after it.
    p.save()
    p.translate(20, 13)
    p.rotate(math.sin(t * 2.4) * 6)
    _happy_head(p, cat, t)
    p.restore()

    line = QPen(cat["line"], 1.4)
    p.setPen(line)
    p.setBrush(box)
    p.drawRoundedRect(QRectF(8, 19, 24, 13), 3, 3)
    p.setBrush(box.darker(115))
    p.drawRoundedRect(QRectF(6.5, 17, 27, 5), 2, 2)  # the lid
    p.setPen(Qt.NoPen)
    p.setBrush(cat["fur"])
    p.drawRect(QRectF(18.6, 22.7, 2.8, 8.6))  # ribbon
    p.drawRect(QRectF(18.6, 17.7, 2.8, 3.6))
    p.setPen(line)
    for side in (-1, 1):  # the bow, and paws holding the lid
        p.drawEllipse(QRectF(20 + side * 3.2 - 2.4, 14.4, 4.8, 3.6))
        p.drawEllipse(QRectF(20 + side * 8.6 - 2.6, 15.6, 5.2, 3.8))
    p.drawEllipse(QRectF(18.7, 15, 2.6, 2.6))
    p.restore()


def paint_transfer_cat(p: QPainter, rect: QRectF, t: float, mode: str, phones: int = 1) -> None:
    """Send to your phone: the cat takes a file off the computer, hops it over to the phone (which
    sparkles as it lands) and hops back for the next one. With several devices downloading, up to
    three phones stand in a row (more get a "+N") and each trip's file goes to the next in turn."""
    cat = {k: QColor(v) for k, v in CAT[mode].items()}
    accent = theme.color(mode, "accent")
    screen = theme.color(mode, "chip")
    line = QPen(cat["line"], 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    shown = max(1, min(phones, 3))
    width = 100 + 13.5 * (shown - 1)  # the scene grows a little to the right for each extra phone
    p.save()
    scale = min(rect.width() / width, rect.height() / 60)
    p.translate(rect.center().x() - width / 2 * scale, rect.center().y() - 30 * scale)
    p.scale(scale, scale)

    trip = (t % 2.6) / 2.6  # one file per trip: there with it, then back for another
    landed = 0.5 < trip < 0.72  # the phone's little celebration
    target = int(t // 2.6) % shown  # whose turn it is
    phone_w = 13 if shown == 1 else 11.5
    phone_x = [84 + 13.5 * i for i in range(shown)]
    aim = QPointF(phone_x[target] + phone_w / 2, 28)

    # The computer, with a file waiting on its screen while the cat is away.
    p.setPen(line)
    p.setBrush(screen)
    p.drawRoundedRect(QRectF(2, 18, 26, 19), 3, 3)
    p.drawLine(QPointF(15, 37), QPointF(15, 42))
    p.drawLine(QPointF(9, 43), QPointF(21, 43))
    if trip > 0.62 or trip < 0.06:
        _file(p, QPointF(15, 27.5), 0.75, accent, cat["line"])

    # The phones, the one getting a file glowing for a moment as it lands.
    for i, px in enumerate(phone_x):
        p.setPen(line)
        p.setBrush(screen)
        p.drawRoundedRect(QRectF(px, 16, phone_w, 25), 3, 3)
        if i == target and landed:
            glow = QColor(accent)
            glow.setAlphaF(0.45 * math.sin((trip - 0.5) / 0.22 * math.pi))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(QRectF(px + 1.5, 18.5, phone_w - 3, 19), 2, 2)
            p.setPen(line)
        p.drawLine(QPointF(px + phone_w / 2 - 1.5, 38.6), QPointF(px + phone_w / 2 + 1.5, 38.6))
    if phones > shown:  # "+2" over the last phone: more devices than fit
        p.setPen(cat["line"])
        font = p.font()
        font.setPixelSize(7)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(phone_x[-1] - 4, 4, phone_w + 8, 10), Qt.AlignCenter, f"+{phones - shown}")
    if landed:
        k = math.sin((trip - 0.5) / 0.22 * math.pi)
        sparkle = QColor(accent)
        sparkle.setAlphaF(k)
        _sparkle(p, QPointF(aim.x() + 6.5, 12), 2.6 * k, sparkle)
        _sparkle(p, QPointF(aim.x() - 9.5, 11), 1.8 * k, sparkle)

    # Where the cat is: over to the phone with the file, a pause, then back.
    if trip < 0.06:
        x, carrying, going = 38.0, True, True  # picking it up
    elif trip < 0.44:
        x, carrying, going = 38 + 33 * _ease((trip - 0.06) / 0.38), True, True
    elif trip < 0.56:
        x, carrying, going = 71.0, trip < 0.5, True  # handing it over
    else:
        x, carrying, going = 71 - 33 * _ease((trip - 0.56) / 0.44), False, False
    walking = 0.06 < trip < 0.44 or trip > 0.56
    hop = abs(math.sin(t * 9)) * 2.2 if walking else 0

    p.save()
    p.translate(x, -hop)
    if walking:  # leaning into each hop, from its feet
        p.translate(0, 49)
        p.rotate(4 if going else -4)
        p.translate(0, -49)

    # Tail behind, swishing the other way from where it's headed.
    swish = math.sin(t * 6) * 2.5
    side = -1 if going else 1
    tail = QPainterPath(QPointF(side * 5, 46))
    tail.cubicTo(QPointF(side * 11, 46), QPointF(side * (12 + swish * 0.3), 40), QPointF(side * 10 + swish, 35))
    p.setBrush(Qt.NoBrush)  # or the open curve gets filled with whatever was used last
    p.setPen(QPen(cat["line"], 3.2, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(tail)
    p.setPen(QPen(cat["fur"], 1.7, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(tail)

    # Body and little feet, stepping in turn.
    p.setPen(line)
    p.setBrush(cat["fur"])
    step = math.sin(t * 9) * 1.6 if walking else 0
    for fx, lift in ((-3.6, step), (3.6, -step)):
        p.drawEllipse(QRectF(fx - 2.6, 47 - max(lift, 0), 5.2, 3.6))
    p.drawEllipse(QRectF(-7.5, 34, 15, 14))

    p.save()
    p.translate(0, 28)
    p.rotate(math.sin(t * 4.5) * 4)
    _happy_head(p, cat, t)
    p.restore()

    # Paws up holding the file over its head, or tucked in on the way back.
    if carrying:
        _file(p, QPointF(0, 15), 1, accent, cat["line"])
        for px in (-5.2, 5.2):
            p.setPen(line)
            p.setBrush(cat["fur"])
            p.drawEllipse(QRectF(px - 2.3, 17.6, 4.6, 3.8))
    else:  # paws at its sides, swinging with each step
        for px, swing in ((-7.4, step), (7.4, -step)):
            p.drawEllipse(QRectF(px - 2, 38.6 + swing * 0.6, 4, 3.4))
    p.restore()

    # The file flying between the cat and the screens (in front of the cat).
    if trip < 0.06:
        k = trip / 0.06
        _file(p, QPointF(15 + (x - 15) * k, 27.5 + (15 - 27.5) * k), 0.75 + 0.25 * k, accent, cat["line"])
    elif 0.44 <= trip < 0.5:
        k = (trip - 0.44) / 0.06
        _file(p, QPointF(x + (aim.x() - x) * k, 15 - hop + (aim.y() - 15) * k - math.sin(k * math.pi) * 6),
              1 - 0.6 * k, accent, cat["line"])  # a little arc, so it can reach the farther phones

    p.restore()


def _file(p: QPainter, c: QPointF, size: float, color: QColor, line: QColor) -> None:
    """A little manga file: a page with a folded corner and a few lines of text, centred on c."""
    if size <= 0.05:
        return
    w, h, fold = 9 * size, 11 * size, 3 * size
    x, y = c.x() - w / 2, c.y() - h / 2
    page = QPainterPath(QPointF(x, y))
    page.lineTo(QPointF(x + w - fold, y))
    page.lineTo(QPointF(x + w, y + fold))
    page.lineTo(QPointF(x + w, y + h))
    page.lineTo(QPointF(x, y + h))
    page.closeSubpath()
    p.setPen(QPen(line, 1.1 * size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(color)
    p.drawPath(page)
    p.setPen(QPen(QColor("#ffffff"), 1.1 * size, Qt.SolidLine, Qt.RoundCap))
    for i in range(3):
        ly = y + h * (0.42 + 0.18 * i)
        p.drawLine(QPointF(x + w * 0.22, ly), QPointF(x + w * (0.78 if i < 2 else 0.55), ly))


def _ease(k: float) -> float:
    """Slow out, quick middle, slow in: how a little cat sets off and arrives."""
    return 0.5 - math.cos(min(max(k, 0), 1) * math.pi) / 2


class MiniCat(QWidget):
    """A tiny cat "please wait". start() shows and animates it, stop() hides it.
    `painter` picks which cat: the peeking head by default, paint_update_cat or paint_transfer_cat;
    anything in `options` is passed on to it (paint_transfer_cat's `phones`)."""

    def __init__(self, mode: Callable[[], str], size: tuple[int, int] = (40, 24), parent: QWidget | None = None,
                 painter: Callable[[QPainter, QRectF, float, str], None] = paint_mini_cat):
        super().__init__(parent)
        self._mode = mode
        self._painter = painter
        self.options: dict = {}
        self.setFixedSize(*size)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self.update)
        self.hide()

    def start(self) -> None:
        if not self._timer.isActive():
            self._t0 = time.monotonic()
            self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._painter(p, QRectF(self.rect()), time.monotonic() - self._t0, self._mode(), **self.options)
        p.end()
